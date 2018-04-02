#!/usr/bin/env python
# -*- coding: utf-8 -*-

import decimal
import math
from datetime import datetime, timedelta
import requests

import arrow
import ephem
import geocoder
from flask import Flask
from flask import render_template
from flask import request
from pytz import timezone

# ephemeris elevations
RISE_SET_ANGLE, CIVIL_ANGLE, NAUTICAL_ANGLE, AMATEUR_ANGLE, ASTRONOMICAL_ANGLE = '-0:34', '-6', '-12', '-15', '-18'

# some useful time spans
A_DAY, AN_HOUR, TWELVE_HOURS = timedelta(days=1), timedelta(hours=1), timedelta(hours=12)

# Google API key
GOOGLE_API_KEY = 'AIzaSyDHhHgOtNxf7Wa5cOY7Mt2ZU8IaqVTuaLo'


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

    if zone is None:
        zone = 'Europe/London'

    if kind == 'rise':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object rising
                result = ephem.Date(obs.next_rising(body)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone(zone))}
            else:
                result = ephem.Date(obs.next_rising(body, use_center=True)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone(zone))}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude", 'data': None}
    elif kind == 'set':
        try:
            if obs.horizon == RISE_SET_ANGLE:  # object setting
                result = ephem.Date(obs.next_setting(body)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone(zone))}
            else:
                result = ephem.Date(obs.next_setting(body, use_center=True)).datetime()
                result = result.replace(tzinfo=timezone('UTC'))
                event_time = {'printable': result.astimezone(timezone(zone)).strftime("%b %d %H:%M:%S %Z"),
                              'data': result.astimezone(timezone(zone))}
        except ephem.CircumpolarError:
            event_time = {'printable': "N/A for this latitude",
                          'data': None}
    else:
        event_time = 'None'

    return event_time


def lunar_phase(dt, zone):
    if zone is None:
        zone = 'Europe/London'

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


def twilight(which_one, place='nc', requester_geocode=None):
    elev = requester_geocode.elevation.meters
    zone = requester_geocode.timeZoneId
    # Setup for the observer (default location is above).
    if place == 'nc':
        lat, lng, elev = '35.6921944', '-80.4357413', 214
    elif place == 'gammelhus':
        # erikshus, specifically, the telescope pier in my front yard.
        lat, lng, elev = '42.106485', '-76.262458', 248.7168
    elif place == 'kopernik':
        lat, lng, elev = '42.001994', '-76.033467', 528
    elif place == 'stjohns':
        lat, lng, elev = '47.5675', '-52.7072', 248.7168  # test St. John's for another timezone
    elif place == 'greenwich':
        lat, lng, elev = '51.476853', '-0.0005002', 47.15256
    elif place == 'geocode' and requester_geocode is not None:
        lat, lng = str(requester_geocode.lat), str(requester_geocode.lng)
    else:  # Greenwich
        lat, lng, elev = '51.476853', '-0.0005002', 47.15256

    obs = ephem.Observer()
    obs.lat, obs.long, latlng, obs.elev = lat, lng, "{}, {}".format(lat, lng), elev
    dt = start_of_astronomical_day(arrow.utcnow().datetime)

    # Here comes the Sun
    if which_one == 'sunset':
        # noinspection PyUnresolvedReferences
        sun = ephem.Sun(obs)
        return object_ephemeris(sun, obs, dt, zone, 'set')['printable']
    if which_one == 'sunrise':
        # noinspection PyUnresolvedReferences
        sun = ephem.Sun(obs)
        return object_ephemeris(sun, obs, dt + AN_HOUR, zone, 'rise')['printable']

    templates = [(CIVIL_ANGLE, "civil"), (NAUTICAL_ANGLE, "nautical"),
                 (AMATEUR_ANGLE, "amateur"), (ASTRONOMICAL_ANGLE, "astronomical")]
    ones = {'civil_end', 'nautical_end', 'amateur_end', 'astronomical_end',
            'civil_begin', 'nautical_begin', 'amateur_begin', 'astronomical_begin'}

    # iterate over the various twilights.
    if which_one in ones:
        for template in templates:
            if which_one == ("{}_end".format(template[1])):
                # noinspection PyUnresolvedReferences
                sun = ephem.Sun(obs)
                return object_ephemeris(sun, obs, dt, zone, 'set', template[0])['printable']
            if which_one == ("{}_begin".format(template[1])):
                # noinspection PyUnresolvedReferences
                sun = ephem.Sun(obs)
                return object_ephemeris(sun, obs, dt, zone, 'rise', template[0])['printable']

    # Now the Moon
    if which_one == 'moonrise':
        moon = ephem.Moon(obs)
        moonrise = object_ephemeris(moon, obs, dt, zone, 'rise')
        return moonrise['printable']

    if which_one == 'moonset':
        moon = ephem.Moon(obs)
        moonrise = object_ephemeris(moon, obs, dt, zone, 'rise')
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if not (12 <= moonset['data'].hour <= 23) and (moonset['data'] < moonrise['data']):
            moonset = object_ephemeris(moon, obs, dt + A_DAY, zone, 'set')
        return moonset['printable']

    if which_one == 'moon_phase':
        return lunar_phase(dt, zone)

    if which_one == 'moonset_ante_astro_noon_p':
        moon = ephem.Moon(obs)
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if moonset['data'].day == dt.day and 12 <= moonset['data'].hour <= 23:
            return 'True'
        else:
            return 'False'


application = Flask(__name__)


# noinspection PyUnusedLocal
@application.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404


# noinspection PyUnusedLocal
@application.route('/')
@application.route('/nc')
@application.route('/gammelhus')
@application.route('/stjohns')
@application.route('/kopernik')
@application.route('/greenwich')
def print_ephemeris():
    # set the location to report for
    with requests.Session() as session:
        if str(request.path) == '/nc':
            place = 'nc'
            requester_ip = request.access_route[0]
            requester_geocode = geocoder.google('35.6921944, -80.4357413', key=GOOGLE_API_KEY)
            latlng = requester_geocode.latlng
            address = u'On Library Park: 35\N{DEGREE SIGN} 41\' 31.9\"N 80\N{DEGREE SIGN} 26\' 8.67\"W'
        if str(request.path) == '/gammelhus':
            place = 'gammelhus'
            requester_ip = request.access_route[0]
            requester_geocode = geocoder.google('42.106485, -76.262458', key=GOOGLE_API_KEY)
            latlng = requester_geocode.latlng
            address = u'Under the streetlamp: 42\N{DEGREE SIGN} 06\' 23.4\"N 76\N{DEGREE SIGN} 15\' 44.9\"W'
        elif str(request.path) == '/stjohns':
            place = 'stjohns'
            requester_ip = request.access_route[0]
            requester_geocode = geocoder.google('47.5675, -52.7072', key=GOOGLE_API_KEY)
            latlng = requester_geocode.latlng
            address = u'St. John\'s: 47.5675\N{DEGREE SIGN}N 52.7072\N{DEGREE SIGN}W'
        elif str(request.path) == '/kopernik':
            place = 'kopernik'
            requester_ip = request.access_route[0]
            requester_geocode = geocoder.google('42.001994, -76.033467', key=GOOGLE_API_KEY)
            latlng = requester_geocode.latlng
            address = u'Kopernik Observatory: 42\N{DEGREE SIGN} 0\' 7.18\"N 76\N{DEGREE SIGN} 2\' 0.48\"W'
        elif str(request.path) == '/greenwich':
            place = 'greenwich'
            requester_ip = request.access_route[0]
            requester_geocode = geocoder.google('51.476853, -0.0005002', key=GOOGLE_API_KEY)
            latlng = requester_geocode.latlng
            address = u'Greenwich Observatory: 51\N{DEGREE SIGN} 28\' 38\"N 0\N{DEGREE SIGN} 0\' 0\"'
        else:
            requester_ip = request.access_route[0]

            if requester_ip != '127.0.0.1':
                place = 'geocode'
                requester_geocode = geocoder.ip(requester_ip, key=GOOGLE_API_KEY)
                latlng = requester_geocode.latlng
                address = str(requester_geocode.address)  # save the address first,
            else:
                place = 'nc'
                requester_geocode = geocoder.google('35.6921944, -80.4357413', key=GOOGLE_API_KEY)
                latlng = requester_geocode.latlng
                address = u'On Library Park: 35\N{DEGREE SIGN} 41\' 31.9\"N 80\N{DEGREE SIGN} 26\' 8.67\"W'

        requester_geocode.elevation = geocoder.elevation(latlng,
                                                         key=GOOGLE_API_KEY,
                                                         session=session)  # get an elevation for it.
        requester_geocode.timeZoneId = geocoder.timezone(latlng,
                                                         key=GOOGLE_API_KEY,
                                                         session=session).timeZoneId

    # noinspection PyPep8
    return render_template('print_times.html',
                       place=place,
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
                       latlng=latlng,
                       elevation=requester_geocode.elevation.meters,
                       ip=requester_ip)


if __name__ == '__main__':
    application.run()

# eof #
