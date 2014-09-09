import os
import urllib
import json
from datetime import datetime, timedelta

import requests


outdir = "/tmp/test"
START = "2013-01-01"
END = "2014-01-01"

URLHEAD = "http://beta.gfw-apis.appspot.com/forest-change/"

DATASETS = ['forma-alerts', 'imazon-alerts', 'quicc-alerts',
            'nasa-active-fires']

# fires table is only good for about 7 days, so we shouldn't
# look for old stuff
today = datetime.today()
tminus5 = today - timedelta(days=5)

FIRESTART = tminus5.strftime('%Y-%m-%d')
FIREEND = today.strftime('%Y-%m-%d')

# we need a big area for fires (e.g. Riau)
# we need a small area for forest change (e.g. SE Para)
RIAU = 'riau.geojson'
PARA = 'para.geojson'


def save(r, dataset, outdir, fmt):
    outpath = os.path.join(outdir, '%s.%s')
    if fmt == 'shp':
        suffix = 'zip'
        fname = outpath % (dataset, suffix)
        fp = open(fname, 'wb')
    else:
        suffix = fmt
        fname = outpath % (dataset, suffix)
        fp = open(fname, 'w')
    print "Saving to %s" % fname
    fp.write(r.content)
    fp.close()

    return


def request_url(start, end, geom, dataset):
    date_param = "%s,%s" % (start, end)

    params_dict = dict(period=date_param, geojson=geom)

    params = urllib.urlencode(params_dict)

    url = "%s%s" % (URLHEAD, dataset)

    return requests.get(url, params=params)


def has_results(r, dataset):
    js = r.json()
    if dataset == 'imazon-alerts':
        hits_a = js['value'][0]['value']  # defor
        hits_b = js['value'][1]['value']  # degrad
        print "Affected area: %0.1f" % (hits_a + hits_b)
        return hits_a > 0 or hits_b > 0
    else:
        hits = js['value']
        print "Hits: %i" % hits
        return hits > 0


def get_files(start, end, geom, dataset, outdir):

    r = request_url(start, end, geom, dataset)

    if has_results(r, dataset):
        download_urls = r.json()['download_urls']

        for fmt in download_urls:
            r = requests.get(download_urls[fmt])

            if 'error' in r.content:
                print "Error: %s" % r.content
                print "Skipping format: %s" % fmt
                continue
            save(r, dataset, outdir, fmt)
    else:
        print "No data - skipping"

    return


def extract_geom(path):
    json_str = open(path).read().strip().replace(' ', '').replace('\n', '')
    geo = json.loads(json_str)
    geom = geo['features'][0]['geometry']
    return json.dumps(geom)


def main(start, end, jsonpath, outdir):
    geom = extract_geom(jsonpath)

    for dataset in DATASETS:
        print "Getting %s" % dataset
        if dataset == 'nasa-active-fires':
            start, end = FIRESTART, FIREEND
            geom = extract_geom(RIAU)
        get_files(start, end, geom, dataset, outdir)

if __name__ == '__main__':
    main(START, END, PARA, outdir)
