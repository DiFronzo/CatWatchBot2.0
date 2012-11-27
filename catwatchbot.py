#!/usr/bin/env python
#encoding=utf-8
#from __future__ import unicode_literals
from datetime import datetime, timedelta
import re
import sys
import time
import codecs
import locale
import argparse
import urllib

import sqlite3
import mwclient
from odict import odict

from wp_private import botlogin, mailfrom, mailto

import logging
import logging.handlers
from progressbar import ProgressBar, Percentage, Bar, ETA, SimpleProgress

parser = argparse.ArgumentParser( description = 'CatWatchBot' )
#parser.add_argument('--page', required=False, help='Name of the contest page to work with')
parser.add_argument('--simulate', action='store_true', help='Do not write results to wiki')
parser.add_argument('--silent', action='store_true', help='No output to console')
parser.add_argument('--verbose', action='store_true', help='Output debug messages')

#parser.add_argument('--output', nargs='?', default='', help='Write results to file')
#parser.add_argument('--log', nargs='?', default = '', help='Log file')
#parser.add_argument('--verbose', action='store_true', default=False, help='More verbose logging')
#parser.add_argument('--close', action='store_true', help='Close contest')
args = parser.parse_args()

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s')

smtp_handler = logging.handlers.SMTPHandler( mailhost = ('localhost', 25),
                fromaddr = mailfrom, toaddrs = mailto, 
                subject=u"[toolserver] CatWatchBot crashed!")
smtp_handler.setLevel(logging.ERROR)
logger.addHandler(smtp_handler)

file_handler = logging.handlers.RotatingFileHandler('catwatchbot.log', maxBytes=100000, backupCount=2)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

if not args.silent:
    console_handler = logging.StreamHandler()
    if args.verbose:
        console_handler.setLevel(logging.DEBUG)
    else:
        console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

cats = {
    u'opprydning': { 
        'categories': [u'Opprydning-statistikk', u'Viktig opprydning'],
        'templates': [u'opprydning', u'opprydningfordi', u'opprydding', u'viktig opprydning', u'opprydning-viktig']
    },
    u'oppdatering': {
        'categories': [u'Trenger oppdatering'],
        'templates': [u'trenger oppdatering', u'best før']
    },
    u'interwiki': {
        'categories': [u'Mangler interwiki'],
        'templates': [u'mangler interwiki']
    },
    u'flytting': {
        'categories': [u'Artikler som bør flyttes'],
        'templates': [u'flytting', u'flytt']
    },
    u'fletting': {
        'categories': [u'Artikler som bør flettes'],
        'templates': [u'fletting', u'flett fra', u'flett-fra', u'flett til', u'flett-til', u'flett']
    },
    u'språkvask': {
        'categories': [u'Artikler som trenger språkvask'],
        'templates': [u'språkvask', u'dårlig språk', u'språkrøkt']
    },
    u'kilder': {
        'categories': [u'Artikler uten referanser', u'Artikler som trenger referanser', u'Artikler uten kilder'],
        'templates': [u'referanseløs', u'trenger referanse', u'tr', u'referanse', u'citation needed', u'cn', u'fact', u'kildeløs', u'refforbedreavsnitt']
    },
    u'ukategorisert': {
        'categories': [u'Ukategorisert'],
        'templates': [u'ukategorisert', u'mangler kategori', u'ukat']
    }
}

class CatWatcher(object):

    def __init__(self, sql, site, category, subcategories = False, articlesonly = False, dryrun = False):

        now = datetime.now().strftime('%F')

        members0 = []
        cur = sql.cursor()
        for row in cur.execute(u'SELECT page FROM catmembers WHERE category=?', (category.page_title,)):
            members0.append(row[0])
        
        members1 = []
        for p in category.members():
            if articlesonly == False or p.namespace == 0:
                members1.append(p.name)
            #if p.namespace == 14 and subcategories:
                # check subcats

        members0 = set(members0)
        members1 = set(members1)

        self.members = members1
        self.count = len(members1)

        self.removals = members0.difference(members1)
        self.additions = members1.difference(members0)
        
        for p in self.removals:
            if not dryrun:
                cur.execute('INSERT INTO catlog (date,category,page,added,new) VALUES (?,?,?,0,0)', (now, category.page_title, p))
                cur.execute('DELETE FROM catmembers WHERE category=? AND page=?', (category.page_title, p))

        #print len(self.additions)
        #if len(self.additions) > 0:
            #pbar = ProgressBar(maxval=len(self.additions), widgets=['Category: %s ' % category.page_title.encode('utf-8'), SimpleProgress(), Percentage()])
            #pbar.start()
        for i,p in enumerate(self.additions):
            #pbar.update(i)
            isnew = 0
            res = site.api('query', prop='revisions', rvprop='timestamp', rvlimit=1, rvdir='newer', titles=p)
            if 'query' in res and 'pages' in res['query']:
                pageid = res['query']['pages'].keys()[0]
                #print pageid
                rv = res['query']['pages'][pageid]['revisions']
                if len(rv) == 1:
                    ts = datetime.strptime(rv[0]['timestamp'],'%Y-%m-%dT%H:%M:%SZ')
                    if ts > (datetime.now() - timedelta(days = 7)):
                        isnew = 1

            if not dryrun:
                cur.execute('INSERT INTO catmembers (date,category,page) VALUES (?,?,?)', (now, category.page_title, p))
                cur.execute('INSERT INTO catlog (date,category,page,added,new) VALUES (?,?,?,1,?)', (now, category.page_title, p, isnew))
        
        sql.commit()
        cur.close()


class StatBot(object):

    def __init__(self, login, dryrun = False):

        self.dryrun = dryrun

        logger.info("============== This is StatBot ==============")

        self.site = mwclient.Site('no.wikipedia.org')
        self.site.login(*botlogin)

        self.sql = sqlite3.connect('vedlikehold.db')

        # Update DB
        self.check_cats()

        # Update stats
        for k in cats.keys():
            self.update_wpstatpage(k)
        
        n = datetime.now()
        page = self.site.Pages['Wikipedia:Underprosjekter/Vedlikehold og oppussing/Statistikk']
        text = u'{{#switch:{{{1|}}}\n| dato = %04d%02d%02d%02d%02d%02d\n| {{Feil|Ukjent nøkkel}}\n}}' % (n.year, n.month, n.day, n.hour, n.minute, n.second)
        if not self.dryrun:
            page.save(text)

        # And ticker
        self.update_ticker()

    def check_cats(self):

        # Check all categories
        logger.info(u'Looking for member changes in maintenance categories')
        counts = {}
        fikset = {}
        merket = {}
        for k in cats:
            counts[k] = 0
            fikset[k] = []
            merket[k] = []
            for catname in cats[k]['categories']:
                cat = self.site.Categories[catname]
                watcher = CatWatcher(self.sql, self.site, cat, dryrun = self.dryrun)
                counts[k] += watcher.count
                fikset[k].extend(watcher.removals)
                merket[k].extend(watcher.additions)
            if len(fikset[k]) > 0 or len(merket[k]) > 0:
                logger.info('    %s: %d -> %d members' % (k, counts[k]-len(merket[k])+len(fikset[k]), counts[k]))
                logger.debug("      fikset (%d): " % len(fikset[k]))
                for r in fikset[k]:
                    logger.debug("%s, " % r)
                logger.debug("      merket (%d): " % len(merket[k]))
                for r in merket[k]:
                    logger.debug("%s, " % r)
            else:
                logger.info('    %s: no changes' % (k))

        # Look for templates in each page that was added or removed
        logger.info(u'Locating revisions when templates were inserted/removed')
        for k in cats:
            for p in fikset[k]:
                self.check_page(p, 'fikset', k, cats[k]['templates'])
            for p in merket[k]:
                self.check_page(p, 'merket', k, cats[k]['templates'])

        # Update database
        logger.info(u'Updating database')
        cur = self.sql.cursor()
        stats = self.site.api('query', meta='siteinfo', siprop='statistics')['query']['statistics']
        narticles = stats['articles']

        now = datetime.now().strftime('%F')
        data = [now, narticles, counts['opprydning'], counts['oppdatering'], counts['interwiki'], counts['flytting'], counts['fletting'], counts[u'språkvask'], counts[u'kilder'], counts['ukategorisert']]
        if not self.dryrun:
            cur.execute(u'''INSERT INTO stats (date,articlecount,opprydning,oppdatering,interwiki,flytting,fletting,språkvask,kilder,ukategorisert)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''', data)
        self.sql.commit()
        cur.close()


    def check_page(self, p, q, catkey, templates):
        #logger.info("    %s: " % (p)
        foundTemplateChange = False
        revschecked = 0
        parentid = -1
        lastrev = -1
        while foundTemplateChange == False:
            if parentid == 0:
                logger.info('    %s: %s %s, was tagged from beginning' % (p,q, catkey))
                break
            elif parentid == -1:
                logger.debug("API: titles=%s", p)
                query = self.site.api('query', prop='revisions', rvprop='ids|timestamp|user|content', rvdir='older', titles=p, rvlimit=10)['query']
            else:
                logger.debug("API: titles=%s rvstartid=%d", p, parentid)
                query = self.site.api('query', prop='revisions', rvprop='ids|timestamp|user|content', rvdir='older', titles=p, rvlimit=10, rvstartid=parentid)['query']
            pid = query['pages'].keys()[0]
            if pid == '-1':
                logger.info("(slettet, pid=-1)")
                break
            else:
                if 'revisions' in query['pages'][pid].keys():
                    revs = query['pages'][pid]['revisions']
                    for rev in revs:
                        revschecked += 1
                        logger.debug(" checking (%s)"%rev['revid'])
                        if '*' in rev.keys() and 'user' in rev.keys():   # revision text and/or user may be hidden
                            txt = rev['*']
                            if txt.find(u'#OMDIRIGERING [[') != -1 or txt.find(u'#REDIRECT[[') != -1:
                                logger.info('    %s: found redirect page' % (p))
                                #logger.info("   (omdirigeringsside) ")
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
                                lastrev = rev['revid']
                                lastrevuser = rev['user']
                                parentid = rev['parentid']
                                revts = rev['timestamp']
                                #print "sjekket",lastrev,lastrevuser
                        else:
                            parentid = rev['parentid']
        if lastrev == -1:
            logger.warning('    %s: %s %s, but no template was found! (checked %d revisions)' % (p, q, catkey, revschecked))
            #logger.info("Fant ikke merking!")
        else:
            revts = datetime.strptime(revts,'%Y-%m-%dT%H:%M:%SZ')
            
            logger.info('    %s: %s %s in rev %s by %s (checked %d revisions)' % (p, q, catkey, lastrev, lastrevuser, revschecked))
            cur = self.sql.cursor()
            if not self.dryrun:
                cur.execute(u'''INSERT INTO cleanlog (date, category, action, page, user, revision)
                    VALUES(?,?,?,?,?,?)''', tuple([revts.strftime('%F %T'), catkey, q, p, lastrevuser, lastrev]))
            cur.close()

        time.sleep(1)


    def update_wpstatpage(self, catkey):
        
        now = datetime.now()
        year = now.strftime('%Y')
        
        title = u'Wikipedia:Underprosjekter/Vedlikehold og oppussing/Statistikk/%s-%s' % (catkey, year)
        catstr = '\n'.join([u'*[[:Kategori:%s]]' % c for c in cats[catkey]['categories']])
        doc = u"""
Denne malen er en tabell over hvor mange sider det på ulike datoer i 2012 befant seg i kategorien(e):
%s
Tallet inkluderer både artikler og andre sider, men ikke sider i underkategorier. Malen har data siden 14. mai 2012.

'''Bruk:''' (NB! Malen er under arbeid, og vil på et tidspunkt bli flyttet til en ny plassering uten omdirigering)

: <code><nowiki>{{</nowiki>{{PAGENAME}}|YYYY-MM-DD<nowiki>}}</nowiki></code>

'''Eksempel:'''

: {{mlp|{{PAGENAME}}|2012-05-14}} → {{%s|2012-05-14}}
""" % (catstr, title)
        

        cur = self.sql.cursor()
        latest = u'0'
        text = ''
        for row in cur.execute(u'SELECT date,%s FROM stats WHERE date>? AND date<=? GROUP BY date ORDER by DATE asc'%catkey, (year+'-01-01',year+'-12-31')):
            text += ' | %s = %s\n' % (row[0],row[1])
            latest = row[1]
        text = u'<includeonly>{{#switch:{{{1|}}}\n| latest = %s\n%s' % (latest,text)

        cur.close()
        text += ' | {{Feil|Mangler data}}\n}}</includeonly><noinclude>' + doc + '</noinclude>'


        page = self.site.Pages[title]
        if not self.dryrun:
            page.save(text, summary='Oppdaterer')

    def update_ticker(self):
        
        # Miniticker
        miniticker = Ticker(
                sql = self.sql, limit = 12, extended = False,
                fikset_kat = [u'opprydning',u'opprydning2',u'interwiki',u'språkvask',u'kilder',u'ref2'], 
                merket_kat = [u'opprydning',u'opprydning2',u'språkvask']
            )
        text = u'{|\n'
        for dt in miniticker.entries.keys():
            fc = "'''{{nowrap|"+dt+"}}'''"
            text += u'|-\n! colspan=3 | ' + fc + '\n'
            for entry in miniticker.entries[dt]:
                #text += u'|-\n|'+fc+' || ' + entry + '\n'
                text += u'|-\n| ' + entry + '\n'
                fc = ''
        text += u'|}'
        page = self.site.Pages['Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-mini']
        if not self.dryrun:
            page.save(text, summary='Oppdaterer')
        
        # Big ticker
        bigticker = Ticker(sql = self.sql, limit = 60, extended = True)
        text = u'{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Toppnav}}{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-header}}\n'
        for dt in bigticker.entries.keys():
            text += u'<h4>%s</h4>\n{|\n' % dt
            #text += u'|-\n! colspan=3 style="text-align:left; font-size:larger;" | ' + dt + '\n'
            for entry in bigticker.entries[dt]:
                #text += u'|-\n|'+fc+' || ' + entry + '\n'
                text += u'|-\n| ' + entry + '\n'
                #fc = ''
            text += u'|}'
        page = self.site.Pages['Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker']
        if not self.dryrun:
            page.save(text, summary='Oppdaterer')
       


class Ticker(object):

    def __init__(self, sql, fikset_kat = [], merket_kat = [], limit = 10, extended = False):
        self.sql = sql
        self.run(fikset_kat, merket_kat, limit, extended)

    def format_ticker_entry(self, cursor, row, maxlen = -1, extended = False):
        verb = {
                'fikset': { 'opprydning': 'ryddet', 'opprydning2': 'ryddet', 'oppdatering': 'oppdatert',
                    'interwiki': 'interwikiet', u'språkvask': u'språkvasket', 'kilder': 'referansesjekket', 'ref2': 'referansesjekket',
                    'ukategorisert': 'kategorisert', 'flytting': '(flyttemerke fjernet)', 'fletting': '(flettemerke fjernet)' },
                'merket': { 'opprydning': 'trenger rydding', 'opprydning2': 'trenger rydding', 'oppdatering': 'trenger oppdatering',
                    'interwiki': 'mangler interwiki', u'språkvask': u'trenger språkvask', 'kilder': 'trenger kilder', 'ref2': 'trenger kilder',
                    'ukategorisert': 'mangler kategorier', 'flytting': u'foreslått flyttet', 'fletting': u'foreslått flettet' },
            }
        icons = { 
            'fikset': 'QsiconSupporting.svg', #'Broom icon.svg', 
            'merket': 'Qsicon Achtung.svg' 
            }
        caticons = {
            'opprydning': 'Broom icon.svg',
            'opprydning2': 'Broom icon.svg',
            'oppdatering': 'Gnome globe current event.svg',
            'interwiki': 'Farm-Fresh flag orange.png',
            'flytting': 'Merge-arrow.svg',
            'fletting': 'Merge-split-transwiki default.svg',
            u'språkvask': 'Spelling icon.svg',
            'kilder': 'Question book-new.svg',
            'ref2': 'Question book-new.svg',
            'ukategorisert': 'Farm-Fresh three tags.png'
            }

        revts = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        f = { 'title': row[3].encode('utf-8'), 'diff': 'prev', 'oldid': row[5] }
        link = u'http://no.wikipedia.org/w/index.php?%s' % urllib.urlencode(f)
            
        action = row[6]
        user = row[4]
        title = row[3]
        if maxlen > 0 and len(title) > maxlen:
            title = title + u'|' + title[:(maxlen-3)] + u'…'
        if title.find(u'Kategori:') == 0:
            title = u':'+title
        entry = u'[[%s]] %s' % (title, verb[action][row[2]])
        if action == 'fikset':
            entry += ' av [[Bruker:%s|%s]]' % (user, user)
        elif extended:
            entry += '. Merket av [[Bruker:%s|%s]]' % (user, user)
        icon = icons[action]
        caticon = caticons[row[2]]
        if action == 'fikset':
            cursor.execute('SELECT id FROM cleanlog WHERE page=? AND category=? AND action="merket" AND date>?',tuple([row[3],row[1],row[2]]))
            s = cursor.fetchall()
            if len(s) > 0:
                entry = u'<s>%s</s>' % entry
        if extended:
            icon = u'[[File:%s|14px|link=]] [[File:%s|16px|link=]]' % (icon, caticon)
        else:
            icon = u'[[File:%s|14px|link=]]' % (icon)

        entry = '%s || %s || ([%s diff])' % (icon, entry, link)
        if extended:
            entry = u'%s || %s' % (revts.strftime('%H:%M'), entry)
        shortdt = revts.strftime('%e. %b') 
        return shortdt, entry
    
    
    def run(self, fikset_kat = [], merket_kat = [], limit = 10, extended = True):
        ticker = odict()
        cur = self.sql.cursor()
        cur2 = self.sql.cursor()

        qargs = []
        whereClause = "" if len(fikset_kat) == 0 and len(merket_kat) == 0 else " WHERE"
        if len(fikset_kat) > 0:
            whereClause += ' (action="fikset" AND category IN (%s))' % ','.join(['?' for i in fikset_kat])
            qargs.extend(fikset_kat)
            if len(merket_kat) > 0:
                whereClause += ' OR'
        if len(merket_kat) > 0:
            whereClause += ' (action="merket" AND category IN (%s))' % ','.join(['?' for i in merket_kat])
            qargs.extend(merket_kat)
        
        qargs.append(limit)
        query = 'SELECT id,date,category,page,user,revision,action FROM cleanlog' + whereClause \
                + ' GROUP BY action,category,page ORDER BY date DESC LIMIT ?'
        
        for row in cur.execute(query, qargs):
            shortdt, entry = self.format_ticker_entry(cur2, row, extended = extended)
            if not shortdt in ticker.keys():
                ticker[shortdt] = []
            ticker[shortdt].append(entry)

        cur.close()
        cur2.close()

        self.entries = ticker


class CatOverview(object):

    def __init__(self, login, dryrun = False):
        
        site = mwclient.Site('no.wikipedia.org')
        site.login(*login)
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
                for row in cur.execute('''SELECT page FROM catmembers WHERE category=?''', [catname]):
                    pagename = row[0]
                    revts = 0
                    for row2 in cur2.execute(u'''SELECT date, revision FROM cleanlog WHERE page=? AND category=? AND action="merket" ORDER BY DATE DESC LIMIT 1''', [pagename,k]):
                        revts = datetime.strptime(row2[0], '%Y-%m-%d %H:%M:%S')
                        pages[k].append({ 'name': pagename, 'tagged': revts, 'rev': row2[1] })
                    if revts == 0:
                        pages[k].append({ 'name': pagename, 'tagged': 0, 'rev': 0 })

            taggedentries = [p for p in pages[k] if p['tagged'] != 0]
            untaggedentries = [p for p in pages[k] if p['tagged'] == 0]
            taggedentries.sort(key = lambda p: p['tagged'])
            pages[k] = untaggedentries + taggedentries
            logger.info("   Tagged: %d, untagged: %d" % (len(taggedentries), len(untaggedentries)))
        
        # Pages
        for k in [u'opprydning', u'oppdatering', u'interwiki', u'flytting', u'fletting', u'flytting', u'språkvask', u'kilder', u'ukategorisert']:
            pagename = u'Wikipedia:Underprosjekter/Vedlikehold og oppussing/' + k.capitalize()
            #print ":: ",pagename
            page = site.Pages[pagename]
            text = u'{{%s}}\n' % (pagename + '/intro')

            taggedentries = [p for p in pages[k] if p['tagged'] != 0]
            if len(taggedentries) > 50:
                text += self.formatsection('Eldste', [taggedentries[:10], taggedentries[10:20]])
                text += self.formatsection('Nyeste', [reversed(taggedentries[-10:]), reversed(taggedentries[-20:-10])])
            else:
                text += self.allpages('Merkede sider', pages[k])
                #text += self.formatsection('Nyeste', [reversed(pages[k][-10:]), reversed(pages[k][-20:-10])])

            text += '\n==Siste oppdateringer==\n{{Wikipedia:Underprosjekter/Vedlikehold og oppussing/Ticker-header}}\n' + self.ticker(sql, k) + '\n'

            if dryrun:
                print text
            else:
                logger.info('Saving to wiki: %s' % pagename)
                page.save(text, summary='CatOverview oppdaterer')

    def allpages(self, title, pages):
        half = int(len(pages)/2)
        return self.formatsection(title, [pages[:half], pages[half:]])

    def formatsection(self, title, cols):
        text = u"== %s ==\n" % title
        text += '{|\n'
        for col in cols:
            text += '|\n{| class="wikitable"\n! Artikkel !! Merket siden\n'
            for p in col:
                text += self.formatrow(p)
            text += '|}\n'
        text += '|}\n'
        return text

    def formatrow(self,p):
        name = p['name']
        if name[0:8] == 'Kategori':
            name = ':' + name
        if p['tagged'] == 0:
            return '|-\n| [[%s]] || %s\n' % (name, '--')
        else:
            return '|-\n| [[%s]] || %s\n' % (name, p['tagged'].strftime('%e. %B %Y'))
    
    def ticker(self, sql, cat):
        ticker = Ticker(sql = sql, limit = 60, extended = True, fikset_kat = [cat], merket_kat = [cat])
        text = '{|\n'
        for dt in ticker.entries.keys():
            text += u'|-\n| colspan=4 style="font-weight:bold; border-bottom: 1px solid #888;" | %s\n' % dt
            #text += u'|-\n! colspan=3 style="text-align:left; font-size:larger;" | ' + dt + '\n'
            for entry in ticker.entries[dt]:
                #text += u'|-\n|'+fc+' || ' + entry + '\n'
                text += u'|-\n| ' + entry + '\n'
                #fc = ''
        text += u'|}\n'
        return text
    
def total_seconds(td):
    # for backwards compability. td is a timedelta object
    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 10**6) / 10**6

try:

    runstart = datetime.now()
    
    import platform
    pv = platform.python_version()
    logger.info('running Python %s, setting locale to no_NO' % (pv))

    for loc in ['no_NO', 'nb_NO.utf8']:
        try:
            locale.setlocale(locale.LC_ALL, loc.encode('utf-8'))
        except locale.Error:
            logger.warning('Locale %s not found' % loc)

    logger.debug('testing æøå')

    StatBot(botlogin, dryrun=args.simulate)
    CatOverview(botlogin, dryrun=args.simulate)

    runend = datetime.now()
    runtime = total_seconds(runend - runstart)
    logger.info('Runtime was %.f seconds.' % (runtime))


except Exception:

    logger.exception('Unhandled Exception')
    #raise


