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

"""This module supports pubsub."""

import arrow
import json
import webapp2
import monitor
import datetime
from gfw import polyline
from gfw import forma
from gfw import cdb
from appengine_config import runtime_config
from google.appengine.ext import ndb
from google.appengine.api import mail
from google.appengine.api import taskqueue
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
import logging
import re
from google.appengine.api import users


class Subscription(ndb.Model):
    topic = ndb.StringProperty()
    email = ndb.StringProperty()
    params = ndb.JsonProperty()
    confirmed = ndb.BooleanProperty(default=False)
    created = ndb.DateTimeProperty(auto_now_add=True)

    @classmethod
    def get_by_topic(cls, topic):
        """Return all confirmed Subscription entities for supplied topic."""
        return cls.query(cls.topic == topic, cls.confirmed == True).iter()

    @classmethod
    def get_by_email(cls, email):
        return cls.query(cls.email == email).iter()

    @classmethod
    def unsubscribe(cls, topic, email):
        x = cls.query(cls.topic == topic, cls.email == email).get()
        if x:
            x.key.delete()


class Event(ndb.Model):
    topic = ndb.StringProperty()
    params = ndb.JsonProperty()
    multicasted = ndb.BooleanProperty(default=False)
    created = ndb.DateTimeProperty(auto_now_add=True)


class Notification(ndb.Model):
    """Key = subscription+event"""
    topic = ndb.StringProperty()
    params = ndb.JsonProperty()  # subscription+event JSON
    sent = ndb.BooleanProperty(default=False)
    created = ndb.DateTimeProperty(auto_now_add=True)

    @classmethod
    def get(cls, event, subscription):
        return cls.get_by_id('%s+%s' % (event.key.id(), subscription.key.id()))

    @classmethod
    def create(cls, event, subscription):
        id = '%s+%s' % (event.key.id(), subscription.key.id())
        return cls(
            id=id,
            topic=event.topic,
            params=dict(event=event.params, subscription=subscription.params))


def publish(params, dry_run=True):
    topic = params['topic']
    event_key = Event(topic=topic, params=params).put()
    taskqueue.add(
        url='/pubsub/publish',
        queue_name='pubsub-publish',
        params=dict(event=event_key.urlsafe(), dry_run=dry_run))


def subscribe(params):
    topic, email = map(params.get, ['topic', 'email'])
    s = Subscription(topic=topic, email=email, params=params).put()
    reply_to = 'sub+%s@gfw-apis.appspotmail.com' % s.urlsafe()
    conf_url = '%s/pubsub/confirm?token=%s' % \
        (runtime_config['APP_BASE_URL'], s.urlsafe())
    mail.send_mail(
        sender=reply_to,
        to=email,
        reply_to=reply_to,
        subject='You subscribed to Global Forest Watch',
        body="""To receive monthly FORMA updates please confirm your subscription by replying to this email or by clicking here:\n%s\n\nTerms of Service: http://globalforestwatch.org/terms""" % conf_url)


def unsubscribe(params):
    topic, email = map(params.get, ['topic', 'email'])
    Subscription.unsubscribe(topic, email)


class Subscriber(InboundMailHandler):
    def receive(self, message):
        if message.to.find('<') > -1:
            urlsafe = message.to.split('<')[1].split('+')[1].split('@')[0]
        else:
            urlsafe = message.to.split('+')[1].split('@')[0]
        s = ndb.Key(urlsafe=urlsafe).get()
        s.confirmed = True
        s.put()


NOTIFY_BODY = """You have subscribed to forest change alerts through Global
Forest Watch. This message reports new forest change alerts for one of your
areas of interest (a country or self-drawn polygon).

<br><br>

A total of {value} {name} {unit} were detected within your area of interest in
the past {interval}. Explore the details of this dataset on Global Forest
Watch by <a href='{link}'>clicking here</a>.

<br><br>

You can unsubscribe or manage your subscriptions by emailing: gfw@wri.org

<br><br>

You will receive a separate e-mail for each distinct polygon, country, or shape
on the GFW map. You will also receive a separate e-mail for each dataset for
which you have requested alerts (FORMA alerts, Imazon SAD Alerts, and NASA
QUICC alerts.)

<br><br>

Please note that this information is subject to the Global Forest Watch <a
href='http://globalforestwatch.com/terms'>Terms of Service</a>.
"""

LINK_GEOM = """http://www.globalforestwatch.org/map/3/{lat}/{lon}/ALL/grayscale/forma?geojson={geom}&begin={begin}&end={end}"""

# LINK_ISO = """http://www.globalforestwatch.org/country/{iso}"""

LINK_ISO = """http://www.globalforestwatch.org/map/4/0/0/{iso}/grayscale/forma?begin={begin}&end={end}"""


class Notify(webapp2.RequestHandler):

    def _center(self, geom):
        return json.loads(geom)['coordinates'][0][0]

    def _get_max_forma_date(self):
        sql = 'SELECT MAX(date) FROM forma_api;'
        response = cdb.execute(sql)
        if response.status_code == 200:
            max_date = json.loads(response.content)['rows'][0]['max']
            return arrow.get(max_date)

    def _period(self):
        max_forma_date = self._get_max_forma_date()
        past_month = max_forma_date.replace(months=-1)
        #month = int(datetime.datetime.now().strftime("%m"))
        #year = datetime.datetime.now().strftime("%Y")
        end = '%s-01' % max_forma_date.format('YYYY-MM')
        begin = '%s-01' % past_month.format('YYYY-MM')
        return begin, end
        #return '%s-%i-01' % (year, month), '%s-%s-01' % (year, month + 1)

    def _body(self, result, n, e, s):
        begin, end = self._period()
        result['end'] = end
        result['begin'] = begin
        result['interval'] = 'month'
        logging.info(s)
        if not result['value']:
            result['value'] = 0
        if 'geom' in s:
            result['aoi'] = 'a user drawn polygon'
            lat, lon = self._center(s['geom'])
            result['lat'] = lat
            result['lon'] = lon
            result['geom'] = s['geom']
            result['link'] = LINK_GEOM.format(**result)
        else:
            result['aoi'] = 'a country (%s)' % s['iso']
            result['iso'] = s['iso'].upper()
            result['link'] = LINK_ISO.format(**result)
        result['link'] = re.sub('\s+', '', result['link']).strip()
        return NOTIFY_BODY.format(**result)

    def post(self):
        try:
            n = ndb.Key(urlsafe=self.request.get('notification')).get()
            if n.sent:
                logging.info("skipping notification, already sent...")
                return
            e = n.params['event']
            s = n.params['subscription']
            s['forma_date'] = self._get_max_forma_date().format('YYYY-MM-DD')
            response = forma.subsription(s)
            if response.status_code == 200:
                result = json.loads(response.content)['rows'][0]
                body = self._body(result, n, e, s)
                to = s['email']
                logging.info('E %s' % e)
                if 'dry_run' in e:
                    # eightysteele@gmail.com,asteele.wri.org
                    tester, subscriber = e['dry_run'].split(',')
                    logging.info('PUB DRYRUN tester=%s subscriber=%s to=%s' %
                                (tester, subscriber, to))
                    if subscriber == to:
                        to = tester
                        logging.info('PUB DRYRUN sending email to %s' % to)
                    else:
                        return
                mail.send_mail(
                    sender='noreply@gfw-apis.appspotmail.com',
                    to=to,
                    subject='New Alerts from Global Forest Watch',
                    body=body,
                    html=body)
                n.sent = True
                n.put()
            else:
                raise Exception('CartoDB Failed (status=%s, content=%s)' %
                               (response.status_code, response.content))
        except Exception, e:
            logging.exception(e)


class Confirmer(webapp2.RequestHandler):
    def get(self):
        urlsafe = self.request.get('token')
        if not urlsafe:
            self.error(404)
            return
        try:
            s = ndb.Key(urlsafe=urlsafe).get()
        except:
            self.error(404)
            return
        if not s:
            self.error(404)
            return
        if s.confirmed:
            self.error(404)
            return
        else:
            s.confirmed = True
            s.put()
        self.response.write('Subscription confirmed!')


class Publisher(webapp2.RequestHandler):
    def post(self):
        """Publish notifications to all event subscribers."""
        e = ndb.Key(urlsafe=self.request.get('event')).get()
        if not e.multicasted:
            for s in Subscription.get_by_topic(e.topic):
                n = Notification.get(e, s)
                if not n:
                    n = Notification.create(e, s)
                    n.put()
                taskqueue.add(
                    url='/pubsub/notify',
                    queue_name='pubsub-notify',
                    params=dict(notification=n.key.urlsafe()))
        e.multicasted = True
        e.put()


class SubscriptionDump(webapp2.RequestHandler):
    def get(self):
        email = self.request.get('email')
        subs = [x.to_dict(exclude=['created']) for x in Subscription.get_by_email(email)]
        self.response.headers.add_header('charset', 'utf-8')
        self.response.headers["Content-Type"] = "application/json"
        self.response.out.write(json.dumps(subs, sort_keys=True))


handlers = webapp2.WSGIApplication([Subscriber.mapping()], debug=True)
