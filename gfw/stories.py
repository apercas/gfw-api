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

"""This module supports stories."""

import json
from appengine_config import runtime_config
from gfw import cdb
import datetime


TABLE = 'stories_dev_copy' if runtime_config.get('IS_DEV') else 'community_stories'


INSERT = """INSERT INTO {table}
  (details, email, name, title, token, visible, date, location,
   the_geom, media)
  VALUES
  ('{details}', '{email}', '{name}', '{title}',
   '{token}', {visible}::boolean, '{date}'::date, '{location}',
   ST_SetSRID(ST_GeomFromGeoJSON('{geom}'), 4326), '{media}')
  RETURNING details, email, name, title, visible, date,
    location, cartodb_id as id, media, ST_AsGeoJSON(the_geom) as the_geom"""


LIST = """SELECT details, email, created_at, name, title, visible, date,
    location, cartodb_id as id, ST_Y(the_geom) AS lat, ST_X(the_geom) AS lng,
    media
FROM {table}
WHERE visible = True {and_where} ORDER BY created_at ASC"""


GET = """SELECT details, email, name, title, visible, date,
    location, cartodb_id as id, ST_Y(the_geom) AS lat, ST_X(the_geom) AS lng,
    media, ST_AsGeoJSON(the_geom) as the_geom
FROM {table}
WHERE cartodb_id = {id}"""


def _prep_story(story):
    if 'geom' in story:
        story['geom'] = json.loads(story['geom'])
    if 'media' in story:
        story['media'] = json.loads(story['media'])
    return story


def create(params):
    """Create new story with params."""
    props = dict(details='', email='', name='',
                 title='', token='', visible='True', date='',
                 location='', geom='', media='[]', table=TABLE)
    props.update(params)
    for key in ['details', 'title', 'name', 'email', 'location']:
        props[key] = props[key].encode('utf-8')
    if not props.get('date'):
        props['date'] = str(datetime.datetime.now())
    props['geom'] = json.dumps(props['geom'])
    if 'media' in props:
        props['media'] = json.dumps(props['media'])
    sql = INSERT.format(**props)
    return cdb.execute(sql, auth=True)


def list(params):
    and_where = ''
    if 'geom' in params:
        and_where = """AND ST_Intersects(the_geom::geography,
            ST_SetSRID(ST_GeomFromGeoJSON('{geom}'),4326)::geography)"""
    if 'since' in params:
        and_where += """ AND date >= '{since}'::date"""
    if and_where:
        and_where = and_where.format(**params)
    result = cdb.execute(
        LIST.format(and_where=and_where, table=TABLE), auth=True)
    if result:
        data = json.loads(result.content)
        if 'total_rows' in data and data['total_rows'] > 0:
            return map(_prep_story, data['rows'])


def get(params):
    params['table'] = TABLE
    result = cdb.execute(GET.format(**params), auth=True)
    if result.status_code != 200:
        raise Exception('CaroDB error getting story (%s)' % result.content)
    if result:
        data = json.loads(result.content)
        if 'total_rows' in data and data['total_rows'] == 1:
            story = data['rows'][0]
            return _prep_story(story)
