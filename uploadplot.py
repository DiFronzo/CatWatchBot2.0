# encoding=utf-8
# run twice a day, at 12.30 and 00.30
import sys
import os

from dotenv import load_dotenv
load_dotenv()

# Tell pywikibot where to find user-config.py (same directory as this script)
os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.abspath(__file__))

import pywikibot

commons = pywikibot.Site('commons', 'commons')
commons.login()

for cat in ['opprydning', 'oppdatering', 'interwiki', 'flytting', 'fletting', 'språkvask', 'kilder', 'ukategorisert']:
    fname = os.path.join('charts', 'nowp vedlikeholdsutvikling - %s.svg' % cat)
    print(fname)
    if not os.path.isfile(fname):
        sys.stderr.write('File "%s" was not found\n' % fname)
        sys.exit(1)

    page = pywikibot.FilePage(commons, 'File:' + fname)
    if page.exists():
        page.upload(fname, comment='Bot: Updating plot', ignore_warnings=True)
        print("Ok")
    else:
        print("Error: File does not exist at Commons: %s" % fname)