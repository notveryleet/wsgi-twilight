#!/usr/bin/env python
# -*- coding: utf-8 -*-

import ipaddress
import math
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import ephem
import requests
from flask import Flask, render_template, request
from geopy.exc import GeopyError
from geopy.geocoders import GoogleV3
from werkzeug.middleware.proxy_fix import ProxyFix
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()

# Ephemeris horizon angles
RISE_SET_ANGLE = '-0:34'
CIVIL_ANGLE = '-6'
NAUTICAL_ANGLE = '-12'
AMATEUR_ANGLE = '-15'
ASTRONOMICAL_ANGLE = '-18'

# Time spans
A_DAY = timedelta(days=1)
HALF_A_DAY = timedelta(hours=12)

GOOGLE_API_KEY: str = os.environ.get('GOOGLE_API_KEY', '')

# Number of proxies in front of the app (the ingress) whose X-Forwarded-For entries are trusted
TRUSTED_PROXY_HOPS = int(os.environ.get('TRUSTED_PROXY_HOPS', '1'))

IPINFO_URL = 'https://ipinfo.io/{0}json'
ELEVATION_URL = 'https://maps.googleapis.com/maps/api/elevation/json'
HTTP_TIMEOUT = 5

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


def start_of_astronomical_day(obs, dt):
    """Return the start of the astronomical day (the sun's last transit, i.e. local solar noon) before dt, in UTC."""
    obs.date = dt
    return ephem.Date(obs.previous_transit(ephem.Sun())).datetime().replace(tzinfo=UTC)


def object_ephemeris(body, obs, dt, zone, kind, elev_angle=RISE_SET_ANGLE, before=None):
    """Calculate the next rise or set time for a celestial body, or N/A if it isn't before `before`."""
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
        result = result.replace(tzinfo=UTC)
        if before is not None and result >= before:
            raise ephem.CircumpolarError
        result = result.astimezone(ZoneInfo(zone))
        return {'printable': result.strftime("%b %d %H:%M:%S %Z"), 'data': result}
    except ephem.CircumpolarError:
        return {'printable': 'N/A for this latitude', 'data': None}


def lunar_phase(dt):
    """Return a string description of the lunar phase at dt."""
    descriptions = [
        "New Moon", "Waxing Crescent Moon", "First Quarter Moon", "Waxing Gibbous Moon",
        "Full Moon", "Waning Gibbous Moon", "Last Quarter Moon", "Waning Crescent Moon",
    ]
    date = ephem.Date(dt)
    last_new, next_new = ephem.previous_new_moon(date), ephem.next_new_moon(date)
    index = math.floor((date - last_new) / (next_new - last_new) * 8 + 0.5)
    return descriptions[index & 7]


def twilight(which_one: str, lat: str, lng: str, elev: float, zone: str) -> str:
    """Calculate a single twilight/ephemeris value for the given location."""
    obs = ephem.Observer()
    obs.lat, obs.long, obs.elev = lat, lng, elev
    obs.pressure = 0  # the horizon angles already include refraction (USNO convention)
    dt = start_of_astronomical_day(obs, datetime.now(UTC))

    # The sun sets before solar midnight and rises before the next solar noon, or not at all this night
    sun = ephem.Sun(obs)
    obs.date = dt
    solar_midnight = ephem.Date(obs.next_antitransit(sun)).datetime().replace(tzinfo=UTC)
    next_noon = ephem.Date(obs.next_transit(sun)).datetime().replace(tzinfo=UTC)

    if which_one == 'sunset':
        return object_ephemeris(sun, obs, dt, zone, 'set', before=solar_midnight)['printable']

    if which_one == 'sunrise':
        return object_ephemeris(sun, obs, dt, zone, 'rise', before=next_noon)['printable']

    for angle, name in TWILIGHT_TYPES:
        if which_one == f'{name}_end':
            return object_ephemeris(sun, obs, dt, zone, 'set', angle, before=solar_midnight)['printable']
        if which_one == f'{name}_begin':
            return object_ephemeris(sun, obs, dt, zone, 'rise', angle, before=next_noon)['printable']

    moon = ephem.Moon(obs)

    if which_one == 'moonrise':
        return object_ephemeris(moon, obs, dt, zone, 'rise')['printable']

    if which_one == 'moonset':
        moonrise = object_ephemeris(moon, obs, dt, zone, 'rise')
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if moonset['data'] and moonrise['data']:
            if moonset['data'] - dt >= HALF_A_DAY and moonset['data'] < moonrise['data']:
                moonset = object_ephemeris(moon, obs, dt + A_DAY, zone, 'set')
        return moonset['printable']

    if which_one == 'moon_phase':
        return lunar_phase(dt)

    if which_one == 'moonset_ante_astro_noon_p':
        moonset = object_ephemeris(moon, obs, dt, zone, 'set')
        if moonset['data'] and moonset['data'] - dt < HALF_A_DAY:
            return 'True'
        return 'False'

    return ''


def _ip_latlng(ip, session):
    """Look up approximate [lat, lng] for an IP address via ipinfo.io (ours if ip is None), or None."""
    try:
        resp = session.get(IPINFO_URL.format(f'{ip}/' if ip else ''), timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        lat, lng = resp.json()['loc'].split(',')
        return [float(lat), float(lng)]
    except (requests.RequestException, ValueError, KeyError):
        return None


def _reverse_geocode(latlng) -> str:
    """Return a formatted address for the coordinates via Google, or the coordinates themselves."""
    try:
        location = GoogleV3(api_key=GOOGLE_API_KEY, timeout=HTTP_TIMEOUT).reverse(latlng, exactly_one=True)
        if location:
            return location.address
    except GeopyError:
        pass
    return f'{latlng[0]}, {latlng[1]}'


def _elevation(latlng, session) -> float:
    """Return elevation in meters for the coordinates via Google, or 0.0."""
    try:
        resp = session.get(ELEVATION_URL,
                           params={'locations': f'{latlng[0]},{latlng[1]}', 'key': GOOGLE_API_KEY},
                           timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return float(resp.json()['results'][0]['elevation'])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return 0.0


def _is_public_ip(ip: str) -> bool:
    """True if ip is a globally routable address that IP geolocation can place."""
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _resolve_location(path: str, requester_ip: str, session):
    """
    Resolve location data for a request.

    For named paths, uses hardcoded coordinates and only fetches timezone.
    Otherwise geolocates the requester's IP. A loopback/private IP can't be
    geolocated, so it uses the server's own public IP, which is right for
    visitors on the server's network.

    Returns (place, latlng, elev, address, zone).
    """
    if path in NAMED_LOCATIONS:
        place, latlng, elev, address = NAMED_LOCATIONS[path]
    else:
        ip = requester_ip if _is_public_ip(requester_ip) else None
        latlng = _ip_latlng(ip, session) or _DEFAULT_LOCATION[1]
        place, elev, address = 'geocode', None, None

    if address is None:
        address = _reverse_geocode(latlng)

    if elev is None:
        elev = _elevation(latlng, session)

    zone = _tf.timezone_at(lat=latlng[0], lng=latlng[1]) or 'UTC'

    return place, latlng, elev, address, zone


application = Flask(__name__)
application.wsgi_app = ProxyFix(application.wsgi_app, x_for=TRUSTED_PROXY_HOPS)


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
    requester_ip = request.remote_addr
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
    requester_ip = request.remote_addr
    with requests.Session() as session:
        place, latlng, elev, address, zone = _resolve_location(str(request.path), requester_ip, session)
    return _render_ephemeris(place, latlng, elev, address, zone, requester_ip)


if __name__ == '__main__':
    application.run()
