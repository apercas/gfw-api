# Global Forest Watch API
# Copyright (C) 2014 World Resource Institute
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

"""This module supports acessing NASA fires data."""

import datetime

from gfw.forestchange.common import CartoDbExecutor
from gfw.forestchange.common import Sql


class FiresSql(Sql):

    WORLD = """
        SELECT COUNT(pt.*) AS value
        FROM global_7d pt
        WHERE acq_date::date >= '{begin}'::date
            AND acq_date::date <= '{end}'::date
            AND CAST(confidence AS INT)> 30
            AND ST_INTERSECTS(
                ST_SetSRID(ST_GeomFromGeoJSON('{geojson}'), 4326), the_geom)"""

    ISO = """
        SELECT COUNT(pt.*) AS value
        FROM global_7d pt,
            (SELECT
                *
            FROM gadm2_countries_simple
            WHERE iso = UPPER('{iso}')) as p
        WHERE ST_Intersects(pt.the_geom, p.the_geom)
            AND acq_date::date >= '{begin}'::date
            AND acq_date::date <= '{end}'::date
            AND CAST(confidence AS INT)> 30"""

    ID1 = """
        SELECT COUNT(pt.*) AS value
        FROM global_7d pt,
             (SELECT
                *
             FROM gadm2_provinces_simple
             WHERE iso = UPPER('{iso}')
                   AND id_1 = {id1}) as p
        WHERE ST_Intersects(pt.the_geom, p.the_geom)
            AND acq_date::date >= '{begin}'::date
            AND acq_date::date <= '{end}'::date
            AND CAST(confidence AS INT)> 30"""

    WDPA = """
        SELECT COUNT(pt.*) AS value
        FROM global_7d pt,
            (SELECT * FROM wdpa_all WHERE wdpaid = {wdpaid}) as p
        WHERE ST_Intersects(pt.the_geom, p.the_geom)
            AND acq_date::date >= '{begin}'::date
            AND acq_date::date <= '{end}'::date
            AND CAST(confidence AS INT)> 30"""

    USE = """
        SELECT COUNT(pt.*) AS value
        FROM global_7d pt,
            (SELECT * FROM {use_table} WHERE cartodb_id = {pid}) as p
        WHERE ST_Intersects(pt.the_geom, p.the_geom)
            AND acq_date::date >= '{begin}'::date
            AND acq_date::date <= '{end}'::date
            AND CAST(confidence AS INT)> 30"""

    @classmethod
    def download(cls, sql):
        return ' '.join(
            sql.replace("SELECT COUNT(pt.*) AS value", "SELECT pt.*").split())


def _get_meta_timecale(params):
    """Return the timescale label based on begin/end dates."""
    import logging
    logging.info('PARAMS: %s' % params)
    if 'begin' in params and 'end' in params:
        begin = datetime.datetime.strptime(
            params['begin'], '%Y-%m-%d').date()
        end = datetime.datetime.strptime(
            params['end'], '%Y-%m-%d').date()
        days = (end - begin).days
        logging.info('%s %s %s' % (begin, end, days))
        if days == 1:
            return 'Past 24 hours'
        elif days == 2:
            return 'Past 48 hours',
        elif days == 3:
            return 'Past 72 hours',
        else:
            return 'Past week'
    return 'Past week'


def _processResults(action, data):
    if 'rows' in data:
        result = data['rows'][0]
        data.pop('rows')
    else:
        result = dict(value=None)

    data['value'] = result['value']
    data['period'] = _get_meta_timecale(data['params'])

    return action, data


def execute(args):
    action, data = CartoDbExecutor.execute(args, FiresSql)
    if action == 'redirect' or action == 'error':
        return action, data
    return _processResults(action, data)
