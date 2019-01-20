#!/usr/bin/env python
# -*- coding: utf-8 -*-

import decimal
import math
from datetime import datetime, timedelta

import arrow
import ephem
import geocoder
import requests
from flask import Flask
from flask import render_template
from flask import request
from flask import url_for
from pytz import timezone

# ephemeris elevations
RISE_SET_ANGLE, CIVIL_ANGLE, NAUTICAL_ANGLE, AMATEUR_ANGLE, ASTRONOMICAL_ANGLE = '-0:34', '-6', '-12', '-15', '-18'

# some useful time spans
A_DAY, AN_HOUR, TWELVE_HOURS = timedelta(days=1), timedelta(hours=1), timedelta(hours=12)

# Google API key
GOOGLE_API_KEY: str = 'AIzaSyAEZTiiZaWvCzOtJ6AKmSx_K949HKAzSMM'


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


def twilight(which_one, requester_geocode=None):
    try:
        lat, lng = str(requester_geocode.lat), str(requester_geocode.lng),
        elev = requester_geocode.elevation.meters
        zone = requester_geocode.timeZoneId
    except NameError:
        lat, lng, elev, zone = '51.4769', '-0.0005', 47.1526, 'GMT'

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
    with requests.Session() as session:
        requester_ip = request.access_route[0]

        if requester_ip == '127.0.0.1':
            place, latlng, elev = 'nc', [35.6921, -80.4357], 218.2
            address: str = u'On Library Park: 35\N{DEGREE SIGN} 41\' 31.9\"N 80\N{DEGREE SIGN} 26\' 8.67\"W'

        else:
            place, latlng = 'geocode', geocoder.ip(requester_ip, key=GOOGLE_API_KEY).latlng

        requester_geocode = geocoder.google(latlng, key=GOOGLE_API_KEY, method='reverse', session=session)

        # Use the defined address, implies we are using a static location, if undefined make it the geocoded one.
        try:
            address
        except NameError:
            address = str(requester_geocode.address)

        # Use the defined elevation, implies we are using a static location, if undefined make it the geocoded one.
        try:
            requester_geocode.elevation = lambda: None
            requester_geocode.elevation.meters = lambda: None
            setattr(requester_geocode.elevation, 'meters', elev)
        except NameError:
            requester_geocode.elevation = geocoder.elevation(latlng, key=GOOGLE_API_KEY, session=session)

        # Get the timezone
        requester_geocode.timeZoneId = geocoder.timezone(latlng, key=GOOGLE_API_KEY, session=session).timeZoneId

    return render_template('404.html',
                           place=place,
                           address=address,
                           latlng=latlng,
                           elevation=requester_geocode.elevation.meters,
                           ip=requester_ip), 404


# noinspection PyUnusedLocal
@application.route('/')
@application.route('/nc')
@application.route('/erikshus')
@application.route('/gammelhus')
@application.route('/kopernik')
@application.route('/deetop')
@application.route('/stjohns')
@application.route('/greenwich')
def print_ephemeris():
    # set the location to report for
    with requests.Session() as session:
        requester_ip = request.access_route[0]

        if str(request.path) == '/nc' or str(request.path) == '/erikshus':
            place, latlng, elev = 'nc', [35.6921, -80.4357], 218.2
            address: str = u'On Library Park: 35\N{DEGREE SIGN} 41\' 32\"N 80\N{DEGREE SIGN} 26\' 9\"W'
        elif str(request.path) == '/gammelhus':
            place, latlng, elev = 'gammelhus', [42.1064, -76.2624], 248.7168
            address: str = u'Under the streetlamp: 42\N{DEGREE SIGN} 06\' 23\"N 76\N{DEGREE SIGN} 15\' 45\"W'
        elif str(request.path) == '/kopernik':
            place, latlng, elev = 'kopernik', [42.0020, -76.0334], 528
            address: str = u'Kopernik Observatory: 42\N{DEGREE SIGN} 0\' 7\"N 76\N{DEGREE SIGN} 2\' 0\"W'
        elif str(request.path) == '/deetop':
            place, latlng, elev = 'deetop', [41.9700, -75.6700], 284
            address: str = u'Dee-Top Observatory: 41\N{DEGREE SIGN} 58\' 12\"N 75\N{DEGREE SIGN} 40\' 12\"W'
        elif str(request.path) == '/stjohns':
            place, latlng, elev = 'stjohns', [47.5675, -52.7072], 83
            address: str = u'St. John\'s: 47\N{DEGREE SIGN} 34\' 3\"N 52\N{DEGREE SIGN} 42\' 26\"W'
        elif str(request.path) == '/greenwich':
            place, latlng, elev = 'greenwich', [51.4768, -0.0005], 47.1526
            address: str = u'Greenwich Observatory: 51\N{DEGREE SIGN} 28\' 38\"N 0\N{DEGREE SIGN} 0\' 0\"'
        else:
            if requester_ip == '127.0.0.1':
                place, latlng, elev = 'nc', [35.6921, -80.4357], 218.2
                address: str = u'On Library Park: 35\N{DEGREE SIGN} 41\' 32\"N 80\N{DEGREE SIGN} 26\' 9\"W'
            else:
                place, latlng = 'geocode', geocoder.ip(requester_ip, key=GOOGLE_API_KEY, session=session).latlng

        # Start with a discovered geocode.
        requester_geocode = geocoder.google(latlng, method='reverse', key=GOOGLE_API_KEY, session=session)

        # Use the defined address, implies we are using a static location, if undefined make it the geocoded one.
        try:
            address
        except NameError:
            address = str(requester_geocode.address)

        # Use the defined elevation, implies we are using a static location, if undefined make it the geocoded one.
        try:
            requester_geocode.elevation = lambda: None
            requester_geocode.elevation.meters = lambda: None
            setattr(requester_geocode.elevation, 'meters', elev)
        except NameError:
            requester_geocode.elevation = geocoder.elevation(latlng, key=GOOGLE_API_KEY, session=session)

        # Get the timezone
        requester_geocode.timeZoneId = geocoder.timezone(latlng, key=GOOGLE_API_KEY, session=session).timeZoneId

    # noinspection PyPep8
    return render_template('print_times.html',
                           place=place,
                           sunset_string=twilight('sunset', requester_geocode),
                           sunrise_string=twilight('sunrise', requester_geocode),
                           civil_end_string=twilight('civil_end', requester_geocode),
                           civil_begin_string=twilight('civil_begin', requester_geocode),
                           nautical_end_string=twilight('nautical_end', requester_geocode),
                           nautical_begin_string=twilight('nautical_begin', requester_geocode),
                           amateur_end_string=twilight('amateur_end', requester_geocode),
                           amateur_begin_string=twilight('amateur_begin', requester_geocode),
                           astro_end_string=twilight('astronomical_end', requester_geocode),
                           astro_begin_string=twilight('astronomical_begin', requester_geocode),
                           moonrise_string=twilight('moonrise', requester_geocode),
                           moonset_string=twilight('moonset', requester_geocode),
                           moon_phase_string=twilight('moon_phase', requester_geocode),
                           moonset_ante_astro_noon_p=twilight('moonset_ante_astro_noon_p', requester_geocode),
                           address=address,
                           latlng=latlng,
                           elevation=requester_geocode.elevation.meters,
                           ip=requester_ip)


if __name__ == '__main__':
    application.run()

# xyzzy #
