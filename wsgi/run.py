#!/usr/bin/env python
# -*- coding: utf-8 -*-

import decimal
import math

import ephem
import geocoder
from datetime import datetime, timedelta, tzinfo
from pytz import timezone

import arrow
from flask import Flask
from flask import request
from flask import render_template


# ephemeris elevations
RISE_SET_ANGLE, CIVIL_ANGLE, NAUTICAL_ANGLE, AMATEUR_ANGLE, ASTRONOMICAL_ANGLE = '-0:34', '-6', '-12', '-15', '-18'

# some useful time spans
A_DAY, AN_HOUR, TWELVE_HOURS = timedelta(days=1), timedelta(hours=1), timedelta(hours=12)


def start_of_astronomical_day(dt):
    # This takes a date and returns a date which would be the beginning of the astronomical day (local noon)

    # Use today if we are past local noon. Use yesterday if we are before local noon (but after midnight).
    # dt needs to be 15 minutes past in order to work for sunrise for some reason
    if 0 <= dt.hour < 12:
        dt = dt.replace(hour=13, minute=15, second=0, microsecond=0) - A_DAY
    else:
        dt = dt.replace(hour=13, minute=15, second=0, microsecond=0)

    return dt


def object_ephemeris(body, obs, dt, zone, kind, elev_angle=RISE_SET_ANGLE):
    obs.horizon, obs.date = elev_angle, dt

    if kind == 'rise':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object rising
                result = ephem.Date(obs.next_rising(body)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone('UTC'))}
            else:
                result = ephem.Date(obs.next_rising(body, use_center=True)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone('UTC'))}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude", 'data': None}
    elif kind == 'set':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object setting
                result = ephem.Date(obs.next_setting(body)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone('UTC'))}
            else:
                result = ephem.Date(obs.next_setting(body, use_center=True)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone('UTC'))}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude",
                          'data': None}
    else:
        event_time = 'None'

    return event_time


def lunar_phase(dt=None, zone='UTC'):
    dec = decimal.Decimal

    description = ["New Moon", "Waxing Crescent Moon", "First Quarter Moon", "Waxing Gibbous Moon",
                   "Full Moon", "Waning Gibbous Moon", "Last Quarter Moon", "Waning Crescent Moon"]

    diff = dt - datetime(2001, 1, 1, tzinfo=timezone(zone))
    days = dec(diff.days) + (dec(diff.seconds) / dec(86400))
    lunations = dec("0.20439731") + (days * dec("0.03386319269"))

    pos = lunations % dec(1)

    index = (pos * dec(8)) + dec("0.5")
    index = math.floor(index)

    return description[int(index) & 7]


def twilight(which_one, place='erikshus', requester_geocode=None):
    # Setup for the observer (default location is above).
    if place == 'home' or place == 'erikshus':
        # erikshus, specifically, the telescope pier in my front yard.
        lat, lng, elev = '42.106485', '-76.262458', 248.7168
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = lat, lng, elev
    elif place == 'stjohns':
        lat, lng, elev = '47.5675', '-52.7072', 248.7168  # test St. John's for another timezone
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = lat, lng, elev
    elif place == 'kopernik':
        lat, lng, elev = '42.001994', '-76.033467', 528
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = lat, lng, elev
    elif place == 'greenwich':
        lat, lng, elev = '51.476853', '-0.0005002', 47.15256
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = lat, lng, elev
    elif place == 'geocode' and requester_geocode is not None:
        lat, lng, elev = requester_geocode.lat, requester_geocode.lng, requester_geocode.elevation
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = str(lat), str(lng), elev
    else:  # Greenwich
        lat, lng, elev = '51.476853', '-0.0005002', 47.15256
        obs = ephem.Observer()
        obs.lat, obs.long, obs.elev = lat, lng, elev

    latlng = "{}, {}".format(lat, lng)
    zone = geocoder.timezone(latlng).timezone_id
    dt = start_of_astronomical_day(arrow.utcnow().datetime)

    # Here comes the Sun
    sun = ephem.Sun(obs)
    if which_one == 'sunset':
        return object_ephemeris(sun, obs, dt, zone, 'set')['printable']
    if which_one == 'sunrise':
        return object_ephemeris(sun, obs, dt + AN_HOUR, zone, 'rise')['printable']

    templates = [(CIVIL_ANGLE, "civil"), (NAUTICAL_ANGLE, "nautical"),
                 (AMATEUR_ANGLE, "amateur"), (ASTRONOMICAL_ANGLE, "astronomical")]
    ones = {'civil_end', 'nautical_end', 'amateur_end', 'astronomical_end',
            'civil_begin', 'nautical_begin', 'amateur_begin', 'astronomical_begin'}

    # iterate over the various twilights.
    if which_one in ones:
        for template in templates:
            if which_one == ("{}_end".format(template[1])):
                return object_ephemeris(sun, obs, dt, zone, 'set', template[0])['printable']
            if which_one == ("{}_begin".format(template[1])):
                return object_ephemeris(sun, obs, dt, zone, 'rise', template[0])['printable']

    # Now the Moon
    moon = ephem.Moon(obs)
    if which_one == 'moon_phase':
        return lunar_phase(dt, zone)

    moonrise = object_ephemeris(moon, obs, dt, zone, 'rise')
    moonset = object_ephemeris(moon, obs, dt, zone, 'set')

    if which_one == 'moonset_ante_astro_noon_p':
        if moonset['data'].day == dt.day and 12 <= moonset['data'].hour <= 23:
            return 'True'
        else:
            return 'False'

    if which_one == 'moonset':
        if not (12 <= moonset['data'].hour <= 23) and (moonset['data'] < moonrise['data']) :
            moonset = object_ephemeris(moon, obs, dt + A_DAY, zone, 'set')
        return moonset['printable']
    if which_one == 'moonrise':
        return moonrise['printable']


app = Flask(__name__)


@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404


@app.route('/')
@app.route('/home')
@app.route('/erikshus')
@app.route('/stjohns')
@app.route('/kopernik')
@app.route('/greenwich')
def print_ephemeris():
    # set the location to report for
    if str(request.path) in {'/home', '/erikshus'}:
        place = 'home'
        requester_ip = request.access_route[0]
        address = u'Under the streetlamp: 42\N{DEGREE SIGN} 06\' 23.4\"N 76\N{DEGREE SIGN} 15\' 44.9\"W'
        requester_geocode = None
    elif str(request.path) == '/stjohns':
        place = 'stjohns'
        requester_ip = request.access_route[0]
        address = u'St. John\'s: 47.5675\N{DEGREE SIGN}N 52.7072\N{DEGREE SIGN}W'
        requester_geocode = None
    elif str(request.path) == '/kopernik':
        place = 'kopernik'
        requester_ip = request.access_route[0]
        address = u'Kopernik Observatory: 42\N{DEGREE SIGN} 0\' 7.18\"N 76\N{DEGREE SIGN} 2\' 0.48\"W'
        requester_geocode = None
    elif str(request.path) == '/greenwich':
        place = 'greenwich'
        requester_ip = request.access_route[0]
        address = u'Greenwich Observatory: 51\N{DEGREE SIGN} 28\' 38\"N 0\N{DEGREE SIGN} 0\' 0\"'
        requester_geocode = None
    else:
        place = 'geocode'
        requester_ip = request.access_route[0]
        requester_geocode = geocoder.ip(requester_ip)                     # this is more accurate for locations,
        address = str(requester_geocode.address)                          # save the address first,
        requester_geocode = geocoder.elevation(requester_geocode.latlng)  # and this gets a correct elevation for it.

    return render_template('print_times.html', place=place,
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
                           moonset_ante_astro_noon_p=twilight('moonset_ante_astro_noon_p', place, requester_geocode),
                           address=address,
                           ip=requester_ip)


if __name__ == '__main__':
    app.run()

# eof #
