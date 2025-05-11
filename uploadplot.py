#encoding=utf-8
# run twice a day, at 12.30 and 00.30
import sys, os, datetime
import mwclient
import locale

from dotenv import load_dotenv
load_dotenv()

#for loc in ['no_NO', 'nb_NO.utf8']:
#    try:
#        print "Trying",loc
#        locale.setlocale(locale.LC_ALL, loc)
#    except locale.Error:
#        print 'Locale %s not found' % loc

now = datetime.datetime.now()

for cat in ['opprydning', 'oppdatering', 'interwiki', 'flytting', 'fletting', 'språkvask', 'kilder', 'ukategorisert']:
    fname = 'nowp vedlikeholdsutvikling - %s.svg' % cat
    print(fname)
    if not os.path.isfile(fname):
        sys.stderr.write('File "%s" was not found\n' % fname)
        sys.exit(1)

    commons = mwclient.Site('commons.wikimedia.org',
            consumer_token=os.getenv('MW_CONSUMER_TOKEN'),
            consumer_secret=os.getenv('MW_CONSUMER_SECRET'),
            access_token=os.getenv('MW_ACCESS_TOKEN'),
            access_secret=os.getenv('MW_ACCESS_SECRET')
    )

    p = commons.pages['File:' + fname]
    f = open(fname, 'rb')
    if p.exists:
        commons.upload(f, fname, comment = 'Bot: Updating plot', ignore = True)
        print("Ok")
    else:
        print("Error: File does not exist at Commons: %s",fname)
    f.close()