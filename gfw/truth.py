# Global Forest Watch API
# Copyright (C) 2013 World Resource Institute
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""This module supports the Truth API."""

import config
import ee
import logging
import datetime

from gfw.common import APP_BASE_URL
import cloudstorage as gcs

from google.appengine.api import urlfetch
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext import ndb
from google.appengine.ext import blobstore


GCS_BUCKET = '/gfw-apis-truth'


class TruthCache(ndb.Model):
    urls = ndb.StringProperty(repeated=True)
    result = ndb.JsonProperty()


def get_cached_url(blob_key):
    return '%s/truth/images?blob_key=%s' % (APP_BASE_URL, blob_key)


def get_url_content(url):
    rpc = urlfetch.create_rpc(deadline=60)
    urlfetch.make_fetch_call(rpc, url, method='GET')
    result = rpc.get_result()
    return result.content


def cache_boom(boom, rid):
    stack = boom['stack']
    urls = dict(final_image=stack['final_image'],
                reference_image=stack['reference_image'])

    for key, url in urls.iteritems():
        content = get_url_content(url)
        filename = '/%s.jpg' % url.split('thumbid=')[1]
        blob_key = gcs_create(content, filename)
        boom['stack'][key] = get_cached_url(blob_key)

    TruthCache(id=rid, result=boom).put()
    return boom


def gcs_path(filename):
    """Return GCS path for supplied filename or None if it doesn't exist."""
    try:
        path = '/'.join([GCS_BUCKET, filename])
        gcs.stat(path)
        return path
    except:
        return None


def gcs_create(value, filename):
    """Create GCS file with supplied value, filename, and content type."""
    path = ''.join([GCS_BUCKET, filename])
    blobstore_filename = '/gs%s' % path

    with gcs.open(path, 'w', content_type='image/jpeg') as f:
        f.write(value)

    return blobstore.create_gs_key(blobstore_filename)


def pixelCloudScore(img):
    """Calculate the cloud score for the supplied L8 image"""

    def _rescale(img, exp, thresholds):
        """A helper to apply an expression and linearly rescale the output."""
        img = img.expression(exp, {'img': img})
        res = img.subtract(thresholds[0]).divide(thresholds[1] - thresholds[0])
        return res

    score = ee.Image(1.0)
    # Clouds are reasonably bright in the blue band.
    score = score.min(_rescale(img, 'img.B2', [0.1, 0.3]))

    # Clouds are reasonably bright in all visible bands.
    score = score.min(_rescale(img, 'img.B4 + img.B3 + img.B2', [0.2, 0.8]))

    # Clouds are reasonably bright in all infrared bands.
    score = score.min(_rescale(img, 'img.B5 + img.B6 + img.B7', [0.3, 0.8]))

    # Clouds are reasonably cool in temperature.
    score = score.min(_rescale(img, 'img.B10', [300, 290]))

    # However, clouds are not snow.
    ndsi = img.normalizedDifference(['B3', 'B6'])

    return score.min(_rescale(ndsi, 'img', [0.8, 0.6]))


def cloudScore(img):
    pix = pixelCloudScore(img)
    binary = pix.gt(0.5)
    num = binary.reduceRegion(ee.Reducer.mean(), crs='EPSG:4326')
    return num.getInfo()['constant']


def hsvpan(rgb, gray):
    """Accepts the RGB and gray banded image for the same location.
    Returns a pan-sharpened image."""

    huesat = rgb.rgbtohsv().select(['hue', 'saturation'])
    upres = ee.Image.cat(huesat, gray).hsvtorgb()

    return upres


def cloudMask(img, cloud_scores, thresh):
    # Accepts an raw L8 image, a derived image of cloud scores corresponding
    # to each pixel and a threshold to screen out excessively cloudy pixels.
    # Returns the original image, with clouds masked.
    binary = cloud_scores.lte(thresh)
    return img.mask(binary)


def makeCloudFree(img):
    # Convenient wrapper `cloudMask` function that will only accept an L8
    # image and returns the cloud-masked image with the threshold set at 0.5
    clouds = pixelCloudScore(img)
    return cloudMask(img, clouds, 0.5)


def createComposite(start, end, polygon):
    # Accepts a start and end date, along with a bounding GEE polygon. Returns
    # the L8 cloud composite.
    collection = ee.ImageCollection('LC8_L1T_TOA').filterDate(start, end)
    coll = collection.map(makeCloudFree)
    return coll.min().clip(polygon)


def genReferenceImage(location, polygon):
    img = ee.Image(location)
    rgb = img.select('B6', 'B5', 'B4')
    pan = img.select('B8')
    sharp = hsvpan(rgb, pan)
    return dict(img=sharp, score=cloudScore(img.clip(polygon)))


def _create_box(lon, lat, w, h):
    """Returns the coordinates of the corners of a box around the with
    the supplied centroid (lon, lat) and dimensions (width, height).
    Counter-clockwise.

    Args:
      lon: longitude (degrees)
      lat: latitude (degrees)
      w: width of box (meters)
      h: height of box (meters)

    """
    h_deg = (h / 2) / (60. * 1602.)
    w_deg = (w / 2) / (60. * 1602.)
    coords = [
        [lon + w_deg, lat + h_deg],
        [lon - w_deg, lat + h_deg],
        [lon - w_deg, lat - h_deg],
        [lon + w_deg, lat - h_deg],
        [lon + w_deg, lat + h_deg]]
    return coords


def _hsvpan(color, gray):
    """Returns a pan-sharpened Landsat 8 image

    Args:
      color: GEE Landsat 8 image with three color bands
      gray: GEE Landsat 8 image at 15m resolution, gray scale

    """
    huesat = color.rgbtohsv().select(['hue', 'saturation'])
    upres = ee.Image.cat(huesat, gray).hsvtorgb()
    return upres


def _landsat_id(alert_date, coords, offset_days=120):
    """Returns the Asset ID of the Landsat 8 TOA adjusted image that
    is most recent to the supplied alert date, within the supplied
    polygon.

    Args:
      alert_date: A string of format 'YYYY-MM-DD'
      coords: nested list of box coordinates, counter-clockwise
      offset_days: integer number of days to start image search"""
    d = datetime.datetime.strptime(alert_date, '%Y-%m-%d')
    begin_date = d - datetime.timedelta(days=offset_days)
    poly = ee.Feature.Polygon(coords)
    coll = ee.ImageCollection('LANDSAT/LC8_L1T_TOA')
    filtered = coll.filterDate(begin_date, alert_date).filterBounds(poly)
    desc = filtered.sort('system:time_start', False).limit(1)
    return desc.getInfo()['features'][0]['id']


def _get_final_image(image_id, coords):
    """Returns the temporary URL of the given image within a bounding
    box.

    Args:
      image_id: The GEE Landsat asset ID, string
      coords: nested list of box coordinates, counter-clockwise"""
    loc = 'LANDSAT/%s' % image_id
    img = ee.Image(loc)
    color = img.select("B6", "B5", "B4")
    pan = img.select("B8")
    sharp = _hsvpan(color, pan)
    vis_params = {'min': 0.01, 'max': 0.5, 'gamma': 1.7}
    visual_image = sharp.visualize(**vis_params)
    params = {'scale': 30, 'crs': 'EPSG:4326', 'region': str(coords)}
    poly = ee.Feature.Polygon(coords)
    url = visual_image.getThumbUrl(params)
    return dict(
        final_image=url,
        final_score=cloudScore(img.clip(poly))
        )


def _get_reference_image(dater, coords, offset_days=180):
    """Accepts a date and returns the cloud free composite image for the
    supplied coordinates"""
    poly = ee.Feature.Polygon(coords)
    d = datetime.datetime.strptime(dater, '%Y-%m-%d')
    start = d - datetime.timedelta(days=offset_days)
    comp = createComposite(start.strftime('%Y-%m-%d'), dater, poly)
    color = comp.select("B6", "B5", "B4")
    pan = comp.select("B8")
    sharp = _hsvpan(color, pan)
    vis_params = {'min': 0.01, 'max': 0.4, 'gamma': 1.5}
    visual_image = sharp.visualize(**vis_params)
    params = {'scale': 30, 'crs': 'EPSG:4326', 'region': str(coords)}
    url = visual_image.getThumbUrl(params)
    return dict(
        reference_image=url,
        reference_score=cloudScore(comp.clip(poly))
        )


def _boom_hammer(lat, lon, h, w, date, res, asset, fmt):
    """Returns a dictionary of URLs for Landsat 8 imagery, app ready.

    Args:
        lat - decimal latitude
        lon - decimal longitude
        h - desired image pixel height
        w - desired image pixel width
        date - YYYY-MM-DD
        res - desired resolution (thumb | true)
        asset - Earth Engine asset
        fmt - desired output format (img | raw)

    """
    coords = _create_box(lon, lat, w, h)

    final = _get_final_image(_landsat_id(date, coords), coords)
    reference = _get_reference_image(date, coords)
    final.update(reference)
    return final


def _params_prep(params):
    """Return prepared params ready to go as dict."""
    lat, lon = map(float, params.get('ll').split(','))
    h, w = map(int, params.get('dim').split(','))
    res = 'true' if 'res' not in params else params.get('res')
    fmt = 'img' if 'fmt' not in params else params.get('fmt')
    date = params.get('date')
    asset = params.get('asset')
    keys = ['lat', 'lon', 'h', 'w', 'res', 'fmt', 'date', 'asset']
    return dict(zip(keys, [lat, lon, h, w, res, fmt, date, asset]))


def _fetch_url(url):
    """Return raw response content from supplied url."""
    rpc = urlfetch.create_rpc(deadline=50)
    urlfetch.make_fetch_call(rpc, url)
    return rpc.get_result()


def find(params, rid):
    """Find and return truth from supplied params."""
    cache = TruthCache.get_by_id(rid)
    if cache:
        return cache.result

    boom = _params_prep(params)
    ee.Initialize(config.EE_CREDENTIALS, config.EE_URL)
    ee.data.setDeadline(60000)
    urls = _boom_hammer(**boom)
    boom['stack'] = urls
    kaboom = cache_boom(boom, rid)
    return kaboom

coords = [
    [101.095, 1.505],
    [101.095, 1.495],
    [101.105, 1.495],
    [101.105, 1.505],
    [101.095, 1.505]
]

start_date = '2014-09-30'


class GCSServingHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self):
        blob_key = self.request.get('blob_key')
        self.send_blob(blob_key)
