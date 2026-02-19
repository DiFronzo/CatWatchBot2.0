#!/usr/bin/env python
# encoding=utf-8
"""
Generate SVG plots showing the time development of maintenance categories
for the Norwegian Wikipedia "Vedlikehold og oppussing" project.

Reads from the vedlikehold.db SQLite database (stats table) and produces
one SVG per category, matching the naming convention expected by uploadplot.py:
  "nowp vedlikeholdsutvikling - {category}.svg"
"""
import os
import sqlite3
import argparse
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker

# Category keys and their Norwegian display names
CATEGORIES = {
    'opprydning':    'opprydning',
    'oppdatering':   'oppdatering',
    'interwiki':     'interwiki',
    'flytting':      'flytting',
    'fletting':      'fletting',
    'språkvask':     'språkvask',
    'kilder':        'kilder',
    'ukategorisert': 'ukategorisert',
}

# Norwegian Wikipedia category titles for subtitle
CATEGORY_TITLES = {
    'opprydning':    'Artikler som trenger opprydning',
    'oppdatering':   'Artikler som trenger oppdatering',
    'interwiki':     'Artikler som mangler interwiki',
    'flytting':      'Artikler som bør flyttes',
    'fletting':      'Artikler som bør flettes',
    'språkvask':     'Artikler som trenger språkvask',
    'kilder':        'Artikler uten referanser',
    'ukategorisert': 'Ukategoriserte artikler',
}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vedlikehold.db')
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'charts')


def fetch_data(catkey):
    """Fetch date and count for a category from the stats table."""
    sql = sqlite3.connect(DB_PATH)
    cur = sql.cursor()
    rows = cur.execute(
        'SELECT date, %s FROM stats ORDER BY date ASC' % catkey
    ).fetchall()
    cur.close()
    sql.close()

    dates = []
    counts = []
    for row in rows:
        try:
            dt = datetime.strptime(row[0], '%Y-%m-%d')
        except (ValueError, TypeError):
            continue
        dates.append(dt)
        counts.append(row[1])

    return dates, counts


def plot_category(catkey):
    """Generate an SVG plot for a single category."""
    dates, counts = fetch_data(catkey)

    if not dates:
        print('  No data for %s, skipping' % catkey)
        return

    fig, ax = plt.subplots(figsize=(10, 4))

    # Plot the data
    ax.plot(dates, counts, color='#0645AD', linewidth=1.2)
    ax.fill_between(dates, counts, alpha=0.15, color='#0645AD')

    # Title
    cat_title = CATEGORY_TITLES.get(catkey, catkey)
    ax.set_title('Vedlikeholdsutvikling – %s' % cat_title,
                 fontsize=13, fontweight='bold', pad=10)

    # Axis labels
    ax.set_ylabel('Antall sider', fontsize=10)

    # X-axis: dates
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))

    # Y-axis: integer ticks
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=8))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: '{:,.0f}'.format(x).replace(',', ' ')))

    # Grid
    ax.grid(True, which='major', axis='both', linestyle='-', linewidth=0.5, color='#cccccc')
    ax.grid(True, which='minor', axis='x', linestyle=':', linewidth=0.3, color='#dddddd')

    # Style
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='both', labelsize=9)

    # Tight layout
    fig.tight_layout()

    # Save as SVG
    os.makedirs(CHART_DIR, exist_ok=True)
    fname = os.path.join(CHART_DIR, 'Nowp vedlikeholdsutvikling - %s.svg' % catkey)
    fig.savefig(fname, format='svg', bbox_inches='tight')
    plt.close(fig)
    print('  Created: %s' % fname)


def upload_to_commons():
    """Upload all generated SVGs to Wikimedia Commons."""
    from dotenv import load_dotenv
    load_dotenv()
    os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.abspath(__file__))
    import pywikibot

    commons = pywikibot.Site('commons', 'commons')
    commons.login()

    FILE_DESCRIPTION = (
        '== {{int:filedesc}} ==\n'
        '{{Information\n'
        '|description={{en|Time development of maintenance categories on Norwegian Wikipedia (Bokmål).}}\n'
        '|source={{own}}\n'
        '|author=[[User:IngeniousBot|IngeniousBot]]\n'
        '|date=%s\n'
        '}}\n'
        '\n'
        '== {{int:license-header}} ==\n'
        '{{self|Cc-zero}}\n'
        '\n'
        '[[Category:Norwegian (Bokmål) Wikipedia statistics]]'
    )

    for catkey in CATEGORIES:
        fname = os.path.join(CHART_DIR, 'Nowp vedlikeholdsutvikling - %s.svg' % catkey)
        if not os.path.isfile(fname):
            print('  Skipping %s (file not found)' % fname)
            continue

        remote_name = 'File:Nowp vedlikeholdsutvikling - %s.svg' % catkey
        page = pywikibot.FilePage(commons, remote_name)
        if page.exists():
            page.upload(fname, comment='Bot: Updating plot', ignore_warnings=True)
            print('  Uploaded: %s' % remote_name)
        else:
            description = FILE_DESCRIPTION % datetime.now().strftime('%Y-%m-%d')
            page.upload(fname, comment='Bot: Initial upload of maintenance plot',
                        text=description, ignore_warnings=True)
            print('  Created and uploaded: %s' % remote_name)


def main():
    parser = argparse.ArgumentParser(description='Generate maintenance category plots')
    parser.add_argument('--upload', action='store_true',
                        help='Upload generated SVGs to Wikimedia Commons')
    args = parser.parse_args()

    print('Generating plots from %s' % DB_PATH)

    if not os.path.exists(DB_PATH):
        print('Error: Database not found at %s' % DB_PATH)
        return

    for catkey in CATEGORIES:
        plot_category(catkey)

    if args.upload:
        print('Uploading to Wikimedia Commons...')
        upload_to_commons()

    print('Done.')


if __name__ == '__main__':
    main()
