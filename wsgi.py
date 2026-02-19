#!/usr/bin/env python
# -*- coding: utf-8 -*-

import decimal
import math
import os
from datetime import datetime, timedelta

import arrow
import ephem
import geocoder
import requests
from flask import Flask, render_template, request
from pytz import timezone

# Ephemeris horizon angles
RISE_SET_ANGLE = '-0:34'
CIVIL_ANGLE = '-6'
NAUTICAL_ANGLE = '-12'
AMATEUR_ANGLE = '-15'
ASTRONOMICAL_ANGLE = '-18'

# Time spans
A_DAY = timedelta(days=1)
AN_HOUR = timedelta(hours=1)

GOOGLE_API_KEY: str = os.environ.get('GOOGLE_API_KEY', '')

# Predefined locations: path -> (place_id, [lat, lng], elev_m, address)
NAMED_LOCATIONS = {
    '/nc':        ('nc',        [35.6921, -80.4357], 218.2,    u'On Library Park: 35\N{DEGREE SIGN} 41\' 32"N 80\N{DEGREE SIGN} 26\' 9"W'),
    '/erikshus':  ('nc',        [35.6921, -80.4357], 218.2,    u'On Library Park: 35\N{DEGREE SIGN} 41\' 32"N 80\N{DEGREE SIGN} 26\' 9"W'),
    '/gammelhus': ('gammelhus', [42.1064, -76.2624], 248.7168, u'Under the streetlamp: 42\N{DEGREE SIGN} 06\' 23"N 76\N{DEGREE SIGN} 15\' 45"W'),
    '/kopernik':  ('kopernik',  [42.0020, -76.0334], 528.0,    u'Kopernik Observatory: 42\N{DEGREE SIGN} 0\' 7"N 76\N{DEGREE SIGN} 2\' 0"W'),
    '/deetop':    ('deetop',    [41.9700, -75.6700], 284.0,    u'Dee-Top Observatory: 41\N{DEGREE SIGN} 58\' 12"N 75\N{DEGREE SIGN} 40\' 12"W'),
    '/stjohns':   ('stjohns',   [47.5675, -52.7072], 83.0,     u'St. John\'s: 47\N{DEGREE SIGN} 34\' 3"N 52\N{DEGREE SIGN} 42\' 26"W'),
    '/greenwich': ('greenwich', [51.4768, -0.0005],  47.1526,  u'Greenwich Observatory: 51\N{DEGREE SIGN} 28\' 38"N 0\N{DEGREE SIGN} 0\' 0"'),
}

_DEFAULT_LOCATION = ('nc', [35.6921, -80.4357], 218.2, u'On Library Park: 35\N{DEGREE SIGN} 41\' 32"N 80\N{DEGREE SIGN} 26\' 9"W')

# Twilight angle/name pairs, used to iterate over twilight types
TWILIGHT_TYPES = [
    (CIVIL_ANGLE,         'civil'),
    (NAUTICAL_ANGLE,      'nautical'),
    (AMATEUR_ANGLE,       'amateur'),
    (ASTRONOMICAL_ANGLE,  'astronomical'),
]


def start_of_astronomical_day(dt):
    """Return the start of the astronomical day (local noon) for the given UTC datetime."""
    if 0 <= dt.hour < 12:
        return dt.replace(hour=13, minute=15, second=0, microsecond=0) - A_DAY
    return dt.replace(hour=13, minute=15, second=0, microsecond=0)


def object_ephemeris(body, obs, dt, zone, kind, elev_angle=RISE_SET_ANGLE):
    """Calculate the next rise or set time for a celestial body."""
    obs.horizon = elev_angle
    obs.date = dt
    use_center = elev_angle != RISE_SET_ANGLE

    try:
        if kind == 'rise':
            result = ephem.Date(obs.next_rising(body, use_center=use_center)).datetime()
        elif kind == 'set':
            result = ephem.Date(obs.next_setting(body, use_center=use_center)).datetime()
        else:
            return {'printable': 'None', 'data': None}
        result = result.replace(tzinfo=timezone('UTC')).astimezone(timezone(zone))
        return {'printable': result.strftime("%b %d %H:%M:%S %Z"), 'data': result}
    except ephem.CircumpolarError:
        return {'printable': 'N/A for this latitude', 'data': None}


def lunar_phase(dt, zone):
    """Return a string description of the current lunar phase."""
    dec = decimal.Decimal
    descriptions = [
        "New Moon", "Waxing Crescent Moon", "First Quarter Moon", "Waxing Gibbous Moon",
        "Full Moon", "Waning Gibbous Moon", "Last Quarter Moon", "Waning Crescent Moon",
    ]
    diff = dt - datetime(2001, 1, 1, tzinfo=timezone(zone))
    days = dec(diff.days) + (dec(diff.seconds) / dec(86400))
    lunations = dec("0.20439731") + (days * dec("0.03386319269"))
    pos = lunations % dec(1)
    index = math.floor(pos * dec(8) + dec("0.5"))
    return descriptions[int(index) & 7]


def twilight(which_one: str, lat: str, lng: str, elev: float, zone: str) -> str:
    """Calculate a single twilight/ephemeris value for the given location."""
    obs = ephem.Observer()
    obs.lat, obs.long, obs.elev = lat, lng, elev
    dt = start_of_astronomical_day(arrow.utcnow().datetime)

    if which_one == 'sunset':
        return object_ephemeris(ephem.Sun(obs), obs, dt, zone, 'set')['printable']

    if which_one == 'sunrise':
        return object_ephemeris(ephem.Sun(obs), obs, dt + AN_HOUR, zone, 'rise')['printable']

    for angle, name in TWILIGHT_TYPES:
        if which_one == f'{name}_end':
            return object_ephemeris(ephem.Sun(obs), obs, dt, zone, 'set', angle)['printable']
        if which_one == f'{name}_begin':
            return object_ephemeris(ephem.Sun(obs), obs, dt, zone, 'rise', angle)['printable']

    moon = ephem.Moon(obs)

    if which_one == 'moonrise':
        return object_ephemeris(moon, obs, dt, zone, 'rise')['printable']

    if which_one == 'moonset':
        moonrise = object_ephemeris(moon, obs, dt, zone, 'rise')
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if moonset['data'] and moonrise['data']:
            if not (12 <= moonset['data'].hour <= 23) and (moonset['data'] < moonrise['data']):
                moonset = object_ephemeris(moon, obs, dt + A_DAY, zone, 'set')
        return moonset['printable']

    if which_one == 'moon_phase':
        return lunar_phase(dt, zone)

    if which_one == 'moonset_ante_astro_noon_p':
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if moonset['data'] and moonset['data'].day == dt.day and 12 <= moonset['data'].hour <= 23:
            return 'True'
        return 'False'

    return ''


def _resolve_location(path: str, requester_ip: str, session):
    """
    Resolve location data for a request.

    For named paths, uses hardcoded coordinates and only fetches timezone.
    For IP-based requests, performs full geolocation lookup.

    Returns (place, latlng, elev, address, zone).
    """
    if path in NAMED_LOCATIONS:
        place, latlng, elev, address = NAMED_LOCATIONS[path]
    elif requester_ip == '127.0.0.1':
        place, latlng, elev, address = _DEFAULT_LOCATION
    else:
        ip_geo = geocoder.ip(requester_ip, key=GOOGLE_API_KEY, session=session)
        latlng = ip_geo.latlng if ip_geo.latlng else _DEFAULT_LOCATION[1]
        place, elev, address = 'geocode', None, None

    if address is None:
        rev_geo = geocoder.google(latlng, method='reverse', key=GOOGLE_API_KEY, session=session)
        address = str(rev_geo.address)

    if elev is None:
        elev = geocoder.elevation(latlng, key=GOOGLE_API_KEY, session=session).meters

    tz = geocoder.timezone(latlng, key=GOOGLE_API_KEY, session=session)
    zone = tz.timeZoneId if tz and tz.timeZoneId else 'UTC'

    return place, latlng, elev, address, zone


application = Flask(__name__)


def _render_ephemeris(place, latlng, elev, address, zone, requester_ip):
    lat, lng = str(latlng[0]), str(latlng[1])
    tw = dict(lat=lat, lng=lng, elev=elev, zone=zone)
    return render_template(
        'print_times.html',
        place=place,
        address=address,
        latlng=latlng,
        elevation=elev,
        ip=requester_ip,
        sunset_string=twilight('sunset', **tw),
        sunrise_string=twilight('sunrise', **tw),
        civil_end_string=twilight('civil_end', **tw),
        civil_begin_string=twilight('civil_begin', **tw),
        nautical_end_string=twilight('nautical_end', **tw),
        nautical_begin_string=twilight('nautical_begin', **tw),
        amateur_end_string=twilight('amateur_end', **tw),
        amateur_begin_string=twilight('amateur_begin', **tw),
        astro_end_string=twilight('astronomical_end', **tw),
        astro_begin_string=twilight('astronomical_begin', **tw),
        moonrise_string=twilight('moonrise', **tw),
        moonset_string=twilight('moonset', **tw),
        moon_phase_string=twilight('moon_phase', **tw),
        moonset_ante_astro_noon_p=twilight('moonset_ante_astro_noon_p', **tw),
    )


@application.errorhandler(404)
def page_not_found(error):
    requester_ip = request.access_route[0]
    with requests.Session() as session:
        place, latlng, elev, address, zone = _resolve_location('', requester_ip, session)
    return render_template('404.html',
                           place=place,
                           address=address,
                           latlng=latlng,
                           elevation=elev,
                           ip=requester_ip), 404


@application.route('/')
@application.route('/nc')
@application.route('/erikshus')
@application.route('/gammelhus')
@application.route('/kopernik')
@application.route('/deetop')
@application.route('/stjohns')
@application.route('/greenwich')
def print_ephemeris():
    requester_ip = request.access_route[0]
    with requests.Session() as session:
        place, latlng, elev, address, zone = _resolve_location(str(request.path), requester_ip, session)
    return _render_ephemeris(place, latlng, elev, address, zone, requester_ip)


if __name__ == '__main__':
    application.run()
