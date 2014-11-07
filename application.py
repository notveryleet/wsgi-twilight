#!/usr/bin/env python
# -*- coding: utf-8 -*-

import socket
import decimal
import math

import ephem
import geocoder
from datetime import datetime, timedelta
from dateutil.tz import *
from flask import Flask

from flask import request
from flask import render_template


# ephemeris elevations
RISE_SET_ANGLE, CIVIL_ANGLE, NAUTICAL_ANGLE, AMATEUR_ANGLE, ASTRONOMICAL_ANGLE = '-0:34', '-6', '-12', '-15', '-18'

# some useful time spans
A_DAY, TWELVE_HOURS, QUARTER_HOUR = timedelta(days=1), timedelta(hours=12), timedelta(minutes=15)


def start_of_astronomical_day(dt):
    # This takes a date and returns a date which would be the beginning of the astronomical day (local noon)

    # Use today if we are past local noon. Use yesterday if we are before local noon (but after midnight).
    # dt needs to be 15 minutes past in order to work for sunrise for some reason
    if 0 <= dt.hour < 12:
        dt = datetime(dt.year, dt.month, dt.day) - A_DAY + TWELVE_HOURS + QUARTER_HOUR
    else:
        dt = datetime(dt.year, dt.month, dt.day) + TWELVE_HOURS + QUARTER_HOUR

    return dt


def object_ephemeris(body, obs, dt, kind, elev_angle=RISE_SET_ANGLE):
    obs.horizon, obs.date = elev_angle, dt

    if kind == 'rise':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object rising
                result = ephem.localtime(obs.next_rising(body))
                event_time = {'printable': "{:%b %d %H:%M:%S} {}".format(result, tzlocal().tzname(dt)),
                              'data': result}
            else:
                result = ephem.localtime(obs.next_rising(body, use_center=True))
                event_time = {'printable': "{:%b %d %H:%M:%S} {}".format(result, tzlocal().tzname(dt)),
                              'data': result}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude", 'data': None}
    elif kind == 'set':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object setting
                result = ephem.localtime(obs.next_setting(body))
                event_time = {'printable': "{:%b %d %H:%M:%S} {}".format(result, tzlocal().tzname(dt)),
                              'data': result}
            else:
                result = ephem.localtime(obs.next_setting(body, use_center=True))
                event_time = {'printable': "{:%b %d %H:%M:%S} {}".format(result, tzlocal().tzname(dt)),
                              'data': result}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude", 'data': None}
    else:
        event_time = 'None'

    return event_time


def lunar_phase(dt=None):
    dec = decimal.Decimal

    description = ["New Moon", "Waxing Crescent Moon", "First Quarter Moon", "Waxing Gibbous Moon",
                   "Full Moon", "Waning Gibbous Moon", "Last Quarter Moon", "Waning Crescent Moon"]

    if dt is None:
        dt = datetime.now()

    diff = dt - datetime(2001, 1, 1)
    days = dec(diff.days) + (dec(diff.seconds) / dec(86400))
    lunations = dec("0.20439731") + (days * dec("0.03386319269"))

    pos = lunations % dec(1)

    index = (pos * dec(8)) + dec("0.5")
    index = math.floor(index)

    return description[int(index) & 7]


def twilight(which_one, place='geocode', requester_geocode=None):
    # Setup for the observer (default location is above).
    if place == 'home' or place == 'erikshus':
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = '42:06:25', '-76:15:47', 248.7168
    elif place == 'kopernik':
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = '42:0:7.18', '-76:2:0.48', 528
    elif place == 'greenwich':
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = '51:28:38', '0:0:0', 46
    elif place == 'geocode' and requester_geocode is not None:
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = str(requester_geocode.lat), \
                                      str(requester_geocode.lng), \
                                      requester_geocode.elevation
    else:  # Greenwich
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = '51:28:38', '0:0:0', 46

    dt = start_of_astronomical_day(datetime.now())

    # Here comes the Sun
    sun = ephem.Sun(obs)
    if which_one == 'sunset':
        return object_ephemeris(sun, obs, dt, 'set')['printable']
    if which_one == 'sunrise':
        return object_ephemeris(sun, obs, dt, 'rise')['printable']

    templates = [(CIVIL_ANGLE, "civil"), (NAUTICAL_ANGLE, "nautical"),
                 (AMATEUR_ANGLE, "amateur"), (ASTRONOMICAL_ANGLE, "astronomical")]
    ones = {'civil_end', 'nautical_end', 'amateur_end', 'astronomical_end',
            'civil_begin', 'nautical_begin', 'amateur_begin', 'astronomical_begin'}

    # iterate over the various twilights.
    if which_one in ones:
        for template in templates:
            if which_one == (template[1] + "_end"):
                return object_ephemeris(sun, obs, dt, 'set', template[0])['printable']
            if which_one == (template[1] + "_begin"):
                return object_ephemeris(sun, obs, dt, 'rise', template[0])['printable']

    # Now the Moon
    moon = ephem.Moon(obs)
    if which_one == 'moon_phase':
        return lunar_phase(dt)

    moonrise, moonset = object_ephemeris(moon, obs, dt, 'rise'), object_ephemeris(moon, obs, dt, 'set')

    if which_one == 'moonset_early':
        if (moonset['data'].day == moonrise['data'].day) and (moonrise['data'].day == dt.day):
            return False
        elif moonset['data'] < moonrise['data']:
            return True
        else:
            return False

    if which_one == 'moonset':
        return moonset['printable']
    if which_one == 'moonrise':
        return moonrise['printable']


app = Flask(__name__)


@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404


@app.route('/', methods=['GET'])
@app.route('/home', methods=['GET'])
@app.route('/erikshus', methods=['GET'])
@app.route('/kopernik', methods=['GET'])
@app.route('/greenwich', methods=['GET'])
def print_ephemeris():
    # set the location to report for
    if str(request.path) in {'/home', '/erikshus'}:
        place = 'home'
        address = u'Under the streetlamp: 42\N{DEGREE SIGN} 06\' 25\"N 76\N{DEGREE SIGN} 15\' 47\"W'
        requester_geocode = None
    elif str(request.path) == '/kopernik':
        place = 'kopernik'
        address = u'Kopernik Observatory: 42\N{DEGREE SIGN} 0\' 7.18\"N 76\N{DEGREE SIGN} 2\' 0.48\"W'
        requester_geocode = None
    elif str(request.path) == '/greenwich':
        place = 'greenwich'
        address = u'Greenwich Observatory: 51\N{DEGREE SIGN} 28\' 38\"N 0\N{DEGREE SIGN} 0\' 0\"'
        requester_geocode = None
    else:
        place = 'geocode'
        requester_geocode = geocoder.ip(str(request.remote_addr))  # this is more accurate for locations,
        address = requester_geocode.address  # save the address first,
        requester_geocode = geocoder.elevation(
            requester_geocode.latlng)  # and this gets a correct elevation for it.

    return render_template('print_times.html', error=None, place=place,
                           sunset_string=twilight('sunset', place, requester_geocode),
                           sunrise_string=twilight('sunrise', place, requester_geocode),
                           civil_end_string=twilight('civil_end', place, requester_geocode),
                           civil_begin_string=twilight('civil_begin', place, requester_geocode),
                           nautical_end_string=twilight('nautical_end', place, requester_geocode),
                           nautical_begin_string=twilight('nautical_begin', place, requester_geocode),
                           amateur_end_string=twilight('amateur_end', place, requester_geocode),
                           amateur_begin_string=twilight('amateur_begin', place, requester_geocode),
                           astro_end_string=twilight('astronomical_end', place, requester_geocode),
                           astro_begin_string=twilight('astronomical_begin', place, requester_geocode),
                           moonrise_string=twilight('moonrise', place, requester_geocode),
                           moonset_string=twilight('moonset', place, requester_geocode),
                           moon_phase_string=twilight('moon_phase', place, requester_geocode),
                           moonset_early=twilight('moonset_early', place, requester_geocode),
                           address=address,
                           ip=request.remote_addr)


if __name__ == '__main__':
    app.run(host=socket.gethostname(), port=5555)

### eof ###