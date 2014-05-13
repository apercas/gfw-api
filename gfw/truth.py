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
import copy
import ee
import json
import logging
import datetime

from google.appengine.api import urlfetch


def _cloud_mask(img):
    """Returns a masked image, with clouds filtered out

    Args:
      img: GEE Landsat 8 image instance

    Note that the following values in the 'BQA' quality band indicate
    different types of clouds and confidence:

    61440 = Cloudy (high probability) Cirrus
    53248 = Cloudy (high probability) Non-Cirrus
    28672 = Cloudy (low probability) Cirrus

    """
    quality = img.select('BQA')
    cloud_hc = quality.eq(61440)
    cloud_hn = quality.eq(53248)
    cloud_lc = quality.eq(28672)
    masked_image = img.mask().And(cloud_hc.Or(cloud_hn).Or(cloud_lc).Not())
    return img.mask(masked_image)


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
    h_deg = (h / 2) / (60.* 1602.) 
    w_deg = (w / 2) / (60.* 1602.) 
    coords= [[lon + w_deg, lat + h_deg],
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


def _landsat_id(alert_date, coords, offset_days=30):
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

    try:
        idx = desc.getInfo()['features'][0]['id']
    except IndexError:
        idx = None

    return idx


def _landsat_median(alert_date, coords, offset_days=90):
    """Returns the median of all images within 90 days of the supplied
    alert for the given bounding box.

    Args:
      alert_date: A string of format 'YYYY-MM-DD'
      coords: nested list of box coordinates, counter-clockwise
      offset_days: integer number of days to start image search"""
    d = datetime.datetime.strptime(alert_date, '%Y-%m-%d')
    begin_date = d - datetime.timedelta(days=offset_days)
    poly = ee.Feature.Polygon(coords)
    coll = ee.ImageCollection('LANDSAT/LC8_L1T_TOA').filterDate(
        begin_date, alert_date)
    return coll.clip(poly).median()


def _img_url(image_id, coords):
    """Returns the temporary URL of the given image within a bounding
    box.

    Args:
      image_id: The GEE Landsat asset ID, string
      coords: nested list of box coordinates, counter-clockwise"""
    if image_id:
        loc = 'LANDSAT/%s' % image_id
        img = ee.Image(loc)
        color = img.select("B6", "B5", "B4")
        pan = img.select("B8")
        sharp = _hsvpan(color, pan)
        vis_params = {'min': 0.01, 'max': 0.5, 'gamma': 1.7}
        visual_image = sharp.visualize(**vis_params)
        params = {'scale': 30, 'crs': 'EPSG:4326', 'region': str(coords)}
        url = visual_image.getThumbUrl(params)
    else:
        url = 'http://i.imgur.com/jRtVWde.png'
    return url


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

    def _get(d):
        # returns image associated with datetime instance
        str_date = datetime.datetime.strftime(d, '%Y-%m-%d')
        return _img_url(_landsat_id(str_date, coords), coords)

    def _d2s(d):
        return datetime.datetime.strftime(d, '%Y-%m-%d')

    init_date = datetime.datetime.strptime(date, '%Y-%m-%d')
    t_minus_one = init_date - datetime.timedelta(days=30)
    t_minus_two = init_date - datetime.timedelta(days=60)
    t_minus_three = init_date - datetime.timedelta(days=90)
    return {_d2s(init_date): _get(init_date),
            _d2s(t_minus_one): _get(t_minus_one),
            _d2s(t_minus_two): _get(t_minus_two),
            _d2s(t_minus_three): _get(t_minus_three)}


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


def find(params):
    """Find and return truth from supplied params."""
    boom = _params_prep(params)
    logging.info(boom)
    ee.Initialize(config.EE_CREDENTIALS, config.EE_URL)
    ee.data.setDeadline(60000)
    urls = _boom_hammer(**boom)
    boom['stack'] = urls
    return boom
