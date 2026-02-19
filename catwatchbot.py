#!/usr/bin/env python
# encoding=utf-8
from datetime import datetime, timedelta, timezone
import os
import re
import sys
import time
import locale
import argparse
import urllib.parse
import sqlite3
import logging
import logging.handlers

from dotenv import load_dotenv
load_dotenv()

# Tell pywikibot where to find user-config.py (same directory as this script)
os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.abspath(__file__))

import pywikibot

parser = argparse.ArgumentParser(description='CatWatchBot')
parser.add_argument('--simulate', action='store_true', help='Do not write results to wiki')
parser.add_argument('--verbose', action='store_true', help='Output debug output')
parser.add_argument('--backfill', action='store_true',
                    help='Backfill missing cleanlog dates for seeded pages (slow, run once)')
args = parser.parse_args()

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s')

# Only add SMTP handler if mail settings are configured
mail_from = os.getenv('MAIL_FROM')
mail_to = os.getenv('MAIL_TO')
if mail_from and mail_to:
    try:
        smtp_handler = logging.handlers.SMTPHandler(
            mailhost=('localhost', 25),
            fromaddr=mail_from,
            toaddrs=[mail_to],
            subject="[toolserver] CatWatchBot crashed!"
        )
        smtp_handler.setLevel(logging.ERROR)
        logger.addHandler(smtp_handler)
    except Exception:
        pass

console_handler = logging.StreamHandler()
if args.verbose:
    console_handler.setLevel(logging.DEBUG)
else:
    console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

SIMULATE_OUTPUT_DIR = 'simulate_output'


def save_or_dump(page_title, text, site=None, summary='', dryrun=False):
    """Save to wiki or dump to local .txt file when simulating."""
    if dryrun:
        os.makedirs(SIMULATE_OUTPUT_DIR, exist_ok=True)
        safe_name = page_title.replace('/', '_').replace(':', '_').replace(' ', '_')
        filepath = os.path.join(SIMULATE_OUTPUT_DIR, safe_name + '.txt')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('=== Page: %s ===\n\n' % page_title)
            f.write(text)
        logger.info('    [simulate] Saved to %s' % filepath)
    else:
        page = pywikibot.Page(site, page_title)
        page.text = text
        page.save(summary=summary)


cats = {
    'opprydning': {
        'categories': ['Opprydning-statistikk', 'Viktig opprydning'],
        'templates': ['opprydning', 'opprydningfordi', 'opprydding', 'viktig opprydning', 'opprydning-viktig']
    },
    'oppdatering': {
        'categories': ['Trenger oppdatering'],
        'templates': ['trenger oppdatering', 'best før']
    },
    'interwiki': {
        'categories': ['Mangler interwiki'],
        'templates': ['mangler interwiki']
    },
    'flytting': {
        'categories': ['Artikler som bør flyttes'],
        'templates': ['flytting', 'flytt']
    },
    'fletting': {
        'categories': ['Artikler som bør flettes'],
        'templates': ['fletting', 'flett fra', 'flett-fra', 'flett til', 'flett-til', 'flett']
    },
    'språkvask': {
        'categories': ['Artikler som trenger språkvask'],
        'templates': ['språkvask', 'dårlig språk', 'språkrøkt']
    },
    'kilder': {
        'categories': ['Artikler uten referanser', 'Artikler som trenger referanser', 'Artikler uten kilder'],
        'templates': ['referanseløs', 'trenger referanse', 'tr', 'referanse', 'citation needed', 'cn', 'fact', 'kildeløs', 'refforbedreavsnitt']
    },
    'ukategorisert': {
        'categories': ['Ukategorisert'],
        'templates': ['ukategorisert', 'mangler kategori', 'ukat']
    }
}


class CatWatcher:

    def __init__(self, sql, site, category, subcategories=False, articlesonly=False, dryrun=False):

        now = datetime.now().strftime('%F')
        cat_title = category.title(with_ns=False)

        members0 = []
        cur = sql.cursor()
        for row in cur.execute('SELECT page FROM catmembers WHERE category=?', (cat_title,)):
            members0.append(row[0])

        members1 = []
        for p in category.members():
            if not articlesonly or p.namespace() == 0:
                members1.append(p.title())

        members0 = set(members0)
        members1 = set(members1)

        self.members = members1
        self.count = len(members1)

        self.removals = members0.difference(members1)
        self.additions = members1.difference(members0)

        # Detect first-run seeding: if DB was empty, skip per-page API lookups
        self.seeding = len(members0) == 0 and len(self.additions) > 0
        if self.seeding:
            logger.info('    First run for %s — seeding %d members (skipping per-page checks)',
                        cat_title, len(self.additions))

        for p in self.removals:
            cur.execute('INSERT INTO catlog (date,category,page,added,new) VALUES (?,?,?,0,0)',
                        (now, cat_title, p))
            cur.execute('DELETE FROM catmembers WHERE category=? AND page=?',
                        (cat_title, p))

        for i, p in enumerate(self.additions):
            isnew = 0
            if not self.seeding:
                try:
                    page_obj = pywikibot.Page(site, p)
                    oldest = next(page_obj.revisions(reverse=True, total=1))
                    ts = oldest.timestamp
                    # Compare as naive UTC datetimes (pywikibot timestamps are UTC but naive)
                    if ts.replace(tzinfo=None) > datetime.utcnow() - timedelta(days=7):
                        isnew = 1
                except (StopIteration, pywikibot.exceptions.Error):
                    pass

                # Throttle API requests to avoid 429 rate limiting
                time.sleep(1)

            cur.execute('INSERT INTO catmembers (date,category,page) VALUES (?,?,?)',
                        (now, cat_title, p))
            cur.execute('INSERT INTO catlog (date,category,page,added,new) VALUES (?,?,?,1,?)',
                        (now, cat_title, p, isnew))

        sql.commit()
        cur.close()


class StatBot:

    def __init__(self, dryrun=False):

        self.dryrun = dryrun

        logger.info("============== This is StatBot ==============")

        self.site = pywikibot.Site('no', 'wikipedia')
        self.site.login()

        self.sql = sqlite3.connect('vedlikehold.db')

        # Auto-create tables if they don't exist
        schema_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vedlikehold.sql')
        if os.path.exists(schema_file):
            with open(schema_file) as f:
                self.sql.executescript(f.read())
            logger.debug('Database schema ensured')

        # Update DB
        self.check_cats()

        # Update stats
        for k in cats.keys():
            self.update_wpstatpage(k)

        n = datetime.now()
        text = '{{#switch:{{{1|}}}\n| dato = %04d%02d%02d%02d%02d%02d\n| {{Feil|Ukjent nøkkel}}\n}}' % (
            n.year, n.month, n.day, n.hour, n.minute, n.second)
        save_or_dump('Wikipedia:Underprosjekter/Vedlikehold og oppussing/Statistikk',
                     text, site=self.site, summary='Oppdaterer', dryrun=self.dryrun)

        # And ticker
        self.update_ticker()

    def check_cats(self):

        # Check all categories
        logger.info('Looking for member changes in maintenance categories')
        counts = {}
        fikset = {}
        merket = {}
        self._seeded_keys = set()
        for k in cats:
            counts[k] = 0
            fikset[k] = []
            merket[k] = []
            any_seeded = False
            for catname in cats[k]['categories']:
                cat = pywikibot.Category(self.site, 'Kategori:' + catname)
                watcher = CatWatcher(self.sql, self.site, cat, dryrun=self.dryrun)
                if watcher.seeding:
                    any_seeded = True
                counts[k] += watcher.count
                fikset[k].extend(watcher.removals)
                merket[k].extend(watcher.additions)
            if len(fikset[k]) > 0 or len(merket[k]) > 0:
                logger.info('    %s: %d -> %d members' % (
                    k, counts[k] - len(merket[k]) + len(fikset[k]), counts[k]))
                logger.debug("      fikset (%d): " % len(fikset[k]))
                for r in fikset[k]:
                    logger.debug("%s, " % r)
                logger.debug("      merket (%d): " % len(merket[k]))
                for r in merket[k]:
                    logger.debug("%s, " % r)
            else:
                logger.info('    %s: no changes' % k)
            if any_seeded:
                self._seeded_keys.add(k)

        # Look for templates in each page that was added or removed
        # Skip on first run (seeding) — no meaningful diffs to check
        logger.info('Locating revisions when templates were inserted/removed')
        for k in cats:
            if k in self._seeded_keys:
                logger.info('    Skipping check_page for %s (first run seeding)', k)
                continue
            for p in fikset[k]:
                self.check_page(p, 'fikset', k, cats[k]['templates'])
            for p in merket[k]:
                self.check_page(p, 'merket', k, cats[k]['templates'])

        # Update database
        logger.info('Updating database')
        cur = self.sql.cursor()
        stats = self.site.siteinfo.get('statistics')
        narticles = stats['articles']

        now = datetime.now().strftime('%F')
        data = [now, narticles, counts['opprydning'], counts['oppdatering'],
                counts['interwiki'], counts['flytting'], counts['fletting'],
                counts['språkvask'], counts['kilder'], counts['ukategorisert']]
        cur.execute('''INSERT INTO stats (date,articlecount,opprydning,oppdatering,interwiki,
                flytting,fletting,språkvask,kilder,ukategorisert)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', data)
        self.sql.commit()
        cur.close()

    def backfill(self):
        """Backfill missing cleanlog entries for pages that were seeded without check_page."""
        logger.info('============== Backfill: finding pages with missing cleanlog entries ==============')
        cur = self.sql.cursor()
        total = 0
        processed = 0

        for k in cats:
            pages_to_check = []
            for catname in cats[k]['categories']:
                for row in cur.execute(
                    'SELECT m.page FROM catmembers m '
                    'WHERE m.category=? AND NOT EXISTS ('
                    '  SELECT 1 FROM cleanlog c WHERE c.page=m.page AND c.category=?)',
                    (catname, k)):
                    pages_to_check.append(row[0])

            if not pages_to_check:
                logger.info('    %s: all pages already have cleanlog entries', k)
                continue

            total += len(pages_to_check)
            logger.info('    %s: %d pages to backfill', k, len(pages_to_check))

            for i, p in enumerate(pages_to_check):
                logger.info('    [%d/%d] Backfilling %s (%s)', i + 1, len(pages_to_check), p, k)
                self.check_page(p, 'merket', k, cats[k]['templates'])
                processed += 1

                # Commit every 50 pages to save progress
                if processed % 50 == 0:
                    self.sql.commit()
                    logger.info('    Progress: %d/%d pages processed', processed, total)

        self.sql.commit()
        cur.close()
        logger.info('Backfill complete: %d pages processed', processed)

    def check_page(self, p, q, catkey, templates):
        foundTemplateChange = False
        revschecked = 0
        lastrev = -1
        tagged_from_beginning = False

        try:
            page_obj = pywikibot.Page(self.site, p)
            if not page_obj.exists():
                logger.info("    %s: page does not exist (deleted?)" % p)
                return

            for rev in page_obj.revisions(content=True, total=500):
                revschecked += 1
                logger.debug(" checking (%s)" % rev.revid)

                try:
                    txt = rev.text
                    user = rev.user
                except Exception:
                    # Revision text and/or user may be hidden/suppressed
                    continue

                if txt is None:
                    continue

                if '#OMDIRIGERING [[' in txt or '#REDIRECT[[' in txt:
                    logger.info('    %s: found redirect page' % p)
                    foundTemplateChange = True
                    lastrev = -1
                    break

                foundTemplateChange = True if q == 'merket' else False
                m = re.search(r'{{(%s)[\s]*(\||}})' % '|'.join(templates), txt, re.IGNORECASE)
                if m:
                    logger.debug("    Found template: %s" % m.group(1))
                    foundTemplateChange = False if q == 'merket' else True
                if foundTemplateChange:
                    break
                else:
                    lastrev = rev.revid
                    lastrevuser = rev.user
                    revts = rev.timestamp

                    # Check if we've reached the first revision
                    if rev.parentid == 0:
                        tagged_from_beginning = True
                        logger.info('    %s: %s %s, was tagged from beginning' % (p, q, catkey))
                        break

        except pywikibot.exceptions.Error as e:
            logger.warning('    %s: pywikibot error: %s' % (p, str(e)))
            return

        if lastrev == -1:
            if not foundTemplateChange and not tagged_from_beginning:
                logger.warning('    %s: %s %s, but no template change was found! (checked %d revisions)' % (
                    p, q, catkey, revschecked))
        else:
            revts_str = revts.strftime('%Y-%m-%d %H:%M:%S')

            logger.info('    %s: %s %s in rev %s by %s (checked %d revisions)' % (
                p, q, catkey, lastrev, lastrevuser, revschecked))
            cur = self.sql.cursor()
            cur.execute('''INSERT INTO cleanlog (date, category, action, page, user, revision)
                VALUES(?,?,?,?,?,?)''',
                (revts_str, catkey, q, p, lastrevuser, lastrev))
            cur.close()

        time.sleep(1)

    def update_wpstatpage(self, catkey):

        now = datetime.now()
        year = now.strftime('%Y')

        title = 'Wikipedia:Underprosjekter/Vedlikehold og oppussing/Statistikk/%s-%s' % (catkey, year)
        catstr = '\n'.join(['*[[:Kategori:%s]]' % c for c in cats[catkey]['categories']])
        doc = """
Denne malen er en tabell over hvor mange sider det på ulike datoer i %(year)s befant seg i kategorien(e):
%(cats)s
Tallet inkluderer både artikler og andre sider, men ikke sider i underkategorier. Malen har data siden 14. mai 2012.

'''Bruk:''' (NB! Malen er under arbeid, og vil på et tidspunkt bli flyttet til en ny plassering uten omdirigering)

: <code><nowiki>{{</nowiki>{{FULLPAGENAME}}|YYYY-MM-DD<nowiki>}}</nowiki></code>

'''Eksempel:'''

: <code><nowiki>{{</nowiki>{{FULLPAGENAME}}<nowiki>|%(year)s-05-14}}</nowiki></code> → {{%(templatename)s|%(year)s-05-14}}
""" % {'cats': catstr, 'templatename': title, 'year': year}

        cur = self.sql.cursor()
        latest = '0'
        text = ''
        for row in cur.execute(
                'SELECT date,%s FROM stats WHERE date>=? AND date<=? GROUP BY date ORDER by DATE asc' % catkey,
                (year + '-01-01', year + '-12-31')):
            text += ' | %s = %s\n' % (row[0], row[1])
            latest = row[1]
        text = '<includeonly>{{#switch:{{{1|}}}\n| latest = %s\n%s' % (latest, text)

        cur.close()
        text += ' | {{Feil|Mangler data}}\n}}</includeonly><noinclude>' + doc + '</noinclude>'

        save_or_dump(title, text, site=self.site, summary='Oppdaterer', dryrun=self.dryrun)

    def update_ticker(self):

        # Miniticker
        miniticker = Ticker(
            sql=self.sql, limit=12, extended=False,
            fikset_kat=['opprydning', 'opprydning2', 'interwiki', 'språkvask', 'kilder', 'ref2'],
            merket_kat=['opprydning', 'opprydning2', 'språkvask']
        )
        text = '{|\n'
        for dt in miniticker.entries.keys():
            fc = "'''{{nowrap|" + dt + "}}'''"
            text += '|-\n! colspan=3 | ' + fc + '\n'
            for entry in miniticker.entries[dt]:
                text += entry + '\n'
                fc = ''
        text += '|}'
        save_or_dump('Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-mini',
                     text, site=self.site, summary='Oppdaterer', dryrun=self.dryrun)

        # Big ticker
        bigticker = Ticker(sql=self.sql, limit=200, extended=True)
        text = '{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Toppnav}}'
        text += '{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-header}}\n'
        text += '{|\n'
        for dt in bigticker.entries.keys():
            text += '|-\n| colspan=4 style="font-weight:bold; border-bottom: 1px solid #888;" | %s\n' % dt
            for entry in bigticker.entries[dt]:
                text += entry + '\n'
        text += '|}'
        save_or_dump('Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker',
                     text, site=self.site, summary='Oppdaterer', dryrun=self.dryrun)


class Ticker:

    def __init__(self, sql, fikset_kat=None, merket_kat=None, limit=10, extended=False):
        self.sql = sql
        if fikset_kat is None:
            fikset_kat = []
        if merket_kat is None:
            merket_kat = []
        self.run(fikset_kat, merket_kat, limit, extended)

    def format_ticker_entry(self, cursor, row, maxlen=-1, extended=False):
        verb = {
            'fikset': {
                'opprydning': 'ryddet',
                'opprydning2': 'ryddet',
                'oppdatering': 'oppdatert',
                'interwiki': 'interwikiet',
                'språkvask': 'språkvasket',
                'kilder': 'kildebelagt',
                'ref2': 'kildebelagt',
                'ukategorisert': 'kategorisert',
                'flytting': ': flytteforslag avgjort av',
                'fletting': ': fletteforslag avgjort av'
            },
            'merket': {
                'opprydning': 'trenger rydding',
                'opprydning2': 'trenger rydding',
                'oppdatering': 'trenger oppdatering',
                'interwiki': 'mangler interwiki',
                'språkvask': 'trenger språkvask',
                'kilder': 'trenger kilder',
                'ref2': 'trenger kilder',
                'ukategorisert': 'mangler kategorier',
                'flytting': 'foreslått flyttet',
                'fletting': 'foreslått flettet'
            },
        }
        icons = {
            'fikset': 'QsiconSupporting.svg',
            'merket': 'Qsicon Achtung.svg'
        }
        caticons = {
            'opprydning': 'Broom icon.svg',
            'opprydning2': 'Broom icon.svg',
            'oppdatering': 'Gnome globe current event.svg',
            'interwiki': 'Farm-Fresh flag orange.png',
            'flytting': 'Merge-arrow.svg',
            'fletting': 'Merge-split-transwiki default.svg',
            'språkvask': 'Spelling icon.svg',
            'kilder': 'Question book-new.svg',
            'ref2': 'Question book-new.svg',
            'ukategorisert': 'Farm-Fresh three tags.png'
        }

        # id,date,category,page,user,revision,action
        revid = row[5]

        revts = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        f = {'title': row[3], 'diff': 'prev', 'oldid': row[5]}
        link = 'https://no.wikipedia.org/w/index.php?%s' % urllib.parse.urlencode(f)

        action = row[6]
        user = row[4]
        title = row[3]
        if 0 < maxlen < len(title):
            title = title + '|' + title[:(maxlen - 3)] + '…'
        if title.startswith('Kategori:'):
            title = ':' + title
        entry = '{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-rad'
        entry += '|%s|%s|%s|%s|%s|%s' % (revts.strftime('%H:%M'), action, row[2], title, user, revid)
        icon = icons[action]
        caticon = caticons[row[2]]
        if action == 'fikset':
            cursor.execute(
                'SELECT id FROM cleanlog WHERE page=? AND category=? AND action="merket" AND date>?',
                [row[3], row[2], row[1]])
            s = cursor.fetchall()
            if len(s) > 0:
                entry += '|strikeout=1'
        if extended:
            entry += '|extended=1'
        entry += '}}'
        shortdt = revts.strftime('%e. %b')
        return shortdt, entry

    def run(self, fikset_kat=None, merket_kat=None, limit=10, extended=True):
        if fikset_kat is None:
            fikset_kat = []
        if merket_kat is None:
            merket_kat = []
        ticker = {}
        cur = self.sql.cursor()
        cur2 = self.sql.cursor()

        qargs = []
        whereClause = "" if len(fikset_kat) == 0 and len(merket_kat) == 0 else " WHERE"
        if len(fikset_kat) > 0:
            whereClause += ' (action="fikset" AND category IN (%s))' % ','.join(['?' for _ in fikset_kat])
            qargs.extend(fikset_kat)
            if len(merket_kat) > 0:
                whereClause += ' OR'
        if len(merket_kat) > 0:
            whereClause += ' (action="merket" AND category IN (%s))' % ','.join(['?' for _ in merket_kat])
            qargs.extend(merket_kat)

        qargs.append(limit)
        query = 'SELECT id,date,category,page,user,revision,action FROM cleanlog' + whereClause \
                + ' GROUP BY action,category,page ORDER BY date DESC LIMIT ?'

        for row in cur.execute(query, qargs):
            shortdt, entry = self.format_ticker_entry(cur2, row, extended=extended)
            if shortdt not in ticker:
                ticker[shortdt] = []
            ticker[shortdt].append(entry)

        cur.close()
        cur2.close()

        self.entries = ticker


special_pages = {
    'flytting': 'Wikipedia:Flytteforslag'
}


class CatOverview:

    def __init__(self, dryrun=False):

        site = pywikibot.Site('no', 'wikipedia')
        site.login()

        sql = sqlite3.connect('vedlikehold.db')
        cur = sql.cursor()
        cur2 = sql.cursor()

        # Entries
        pages = {}
        logger.info("============== This is CatOverview ==============")
        for k in cats:
            logger.info("Checking category class: %s" % k)
            pages[k] = []
            for catname in cats[k]['categories']:
                for row in cur.execute('SELECT page FROM catmembers WHERE category=?', [catname]):
                    pagename = row[0]
                    revts = 0
                    for row2 in cur2.execute(
                            'SELECT date, revision FROM cleanlog WHERE page=? AND category=? '
                            'AND action="merket" ORDER BY DATE DESC LIMIT 1',
                            [pagename, k]):
                        revts = datetime.strptime(row2[0], '%Y-%m-%d %H:%M:%S')
                        pages[k].append({'name': pagename, 'tagged': revts, 'rev': row2[1]})
                    if revts == 0:
                        pages[k].append({'name': pagename, 'tagged': 0, 'rev': 0})

            taggedentries = [p for p in pages[k] if p['tagged'] != 0]
            untaggedentries = [p for p in pages[k] if p['tagged'] == 0]
            taggedentries.sort(key=lambda p: p['tagged'])
            pages[k] = untaggedentries + taggedentries
            logger.info("   Tagged: %d, untagged: %d" % (len(taggedentries), len(untaggedentries)))

        # Pages
        for k in ['opprydning', 'oppdatering', 'interwiki', 'flytting', 'fletting',
                   'språkvask', 'kilder', 'ukategorisert']:
            pagename = 'Wikipedia:Underprosjekter/Vedlikehold og oppussing/' + k.capitalize()
            text = '{{%s}}\n' % (pagename + '/intro')

            if k in special_pages:
                text += '{{%s}}\n' % special_pages[k]
            else:
                taggedentries = [p for p in pages[k] if p['tagged'] != 0]
                if len(taggedentries) > 50:
                    text += self.formatsection('Eldste', [taggedentries[:10], taggedentries[10:20]])
                    text += self.formatsection('Nyeste',
                                               [list(reversed(taggedentries[-10:])),
                                                list(reversed(taggedentries[-20:-10]))])
                else:
                    text += self.allpages('Merkede sider', pages[k])

            text += '\n==Siste oppdateringer==\n'
            text += '{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-header}}\n'
            text += self.ticker(sql, k) + '\n'

            save_or_dump(pagename, text, site=site, summary='CatOverview oppdaterer', dryrun=dryrun)

    def allpages(self, title, pages):
        half = int(len(pages) / 2)
        return self.formatsection(title, [pages[:half], pages[half:]])

    def formatsection(self, title, cols):
        text = "== %s ==\n" % title
        text += '{|\n'
        for col in cols:
            text += '|\n{| class="wikitable"\n! Artikkel !! Merket siden\n'
            for p in col:
                text += self.formatrow(p)
            text += '|}\n'
        text += '|}\n'
        return text

    def formatrow(self, p):
        name = p['name']
        if name[0:8] == 'Kategori':
            name = ':' + name
        if p['tagged'] == 0:
            return '|-\n| [[%s]] || %s\n' % (name, '--')
        else:
            return '|-\n| [[%s]] || %s\n' % (name, p['tagged'].strftime('%e. %B %Y'))

    def ticker(self, sql, cat):
        ticker = Ticker(sql=sql, limit=200, extended=True, fikset_kat=[cat], merket_kat=[cat])
        text = '{|\n'
        for dt in ticker.entries.keys():
            text += '|-\n| colspan=4 style="font-weight:bold; border-bottom: 1px solid #888;" | %s\n' % dt
            for entry in ticker.entries[dt]:
                text += entry + '\n'
        text += '|}\n'
        return text


try:

    runstart = datetime.now()

    import platform
    pv = platform.python_version()
    logger.info('running Python %s, setting locale to no_NO' % pv)

    for loc in ['no_NO', 'nb_NO.utf8']:
        try:
            locale.setlocale(locale.LC_ALL, loc)
        except locale.Error:
            logger.warning('Locale %s not found' % loc)

    logger.debug('testing æøå')

    bot = StatBot(dryrun=args.simulate)

    if args.backfill:
        bot.backfill()

    CatOverview(dryrun=args.simulate)

    runend = datetime.now()
    runtime = (runend - runstart).total_seconds()
    logger.info('Runtime was %.f seconds.' % runtime)

except Exception:

    logger.exception('Unhandled Exception')

