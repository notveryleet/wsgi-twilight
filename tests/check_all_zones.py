#!/usr/bin/env python
"""
Check twilight() invariants for every timezone timezonefinder can return.

For each zone, picks a point inside it and evaluates every page value hourly
on every Nth day of the year, plus every hour for 3 days around each UTC
offset change (DST), checking that:

  - the astronomical day starts at local solar noon, at most a day before now
  - no value is missing or raises
  - printed times are in the location's zone
  - sun events fall within the night, in order (sunset, twilights, sunrise)
  - every N/A sun value really has no crossing of that altitude that night
  - moon events follow the day start, and the layout flag matches them
  - the moon phase name matches ephem's new moons

Usage:
  python tests/check_all_zones.py                 # full run, ~5 min on 8 cores
  python tests/check_all_zones.py --quick         # every 30th day, ~1 min
  python tests/check_all_zones.py --zones Antarctica/ America/Inuvik

Exits 1 if any invariant is violated.
"""
import argparse
import math
import multiprocessing as mp
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from importlib import resources
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ephem  # noqa: E402
import wsgi  # noqa: E402
from timezonefinder import TimezoneFinder  # noqa: E402

AN_HOUR = timedelta(hours=1)
EVENING = ['sunset', 'civil_end', 'nautical_end', 'amateur_end', 'astronomical_end']
MORNING = ['astronomical_begin', 'amateur_begin', 'nautical_begin', 'civil_begin', 'sunrise']
MOON = ['moonrise', 'moonset', 'moon_phase', 'moonset_ante_astro_noon_p']
PHASES = ["New Moon", "Waxing Crescent Moon", "First Quarter Moon", "Waxing Gibbous Moon",
          "Full Moon", "Waning Gibbous Moon", "Last Quarter Moon", "Waning Crescent Moon"]

# Altitude each sun event crosses: upper limb for sunrise/sunset, center for twilights (geometric)
ALTITUDES = {'sunset': -34 / 60, 'sunrise': -34 / 60}
for _angle, _name in wsgi.TWILIGHT_TYPES:
    ALTITUDES[f'{_name}_end'] = ALTITUDES[f'{_name}_begin'] = float(_angle)


def zone_tab_coords():
    """Representative coordinates per zone from tzdata's zone.tab and zone1970.tab."""
    def iso6709(s, deg_digits):
        sign = -1 if s[0] == '-' else 1
        d, m, sec = int(s[1:deg_digits + 1]), int(s[deg_digits + 1:deg_digits + 3]), int(s[deg_digits + 3:] or 0)
        return sign * (d + m / 60 + sec / 3600)

    coords = {}
    for name in ('zone.tab', 'zone1970.tab'):
        for line in resources.files('tzdata').joinpath('zoneinfo', name).read_text().splitlines():
            if line.startswith('#') or not line.strip():
                continue
            _, coord, zone = line.split('\t')[:3]
            i = max(coord.rfind('+'), coord.rfind('-'))
            coords[zone] = (iso6709(coord[:i], 2), iso6709(coord[i:], 3))
    return coords


def point_in_zone(tf, zone, tab):
    """Find a (lat, lng) that timezonefinder maps to zone, or None."""
    if zone in tab and tf.timezone_at(lat=tab[zone][0], lng=tab[zone][1]) == zone:
        return tab[zone]
    if zone.startswith('Etc/GMT'):
        lng = -15.0 * int(zone[7:] or 0)
        for lat in (0, 5, -5, 20, -20, 40, -40):
            if tf.timezone_at(lat=lat, lng=lng) == zone:
                return lat, lng
    rnd = random.Random(zone)
    for poly in sorted(tf.get_geometry(tz_name=zone, coords_as_pairs=True), key=lambda p: -len(p[0])):
        lngs, lats = [p[0] for p in poly[0]], [p[1] for p in poly[0]]
        candidates = [(sum(lats) / len(lats), sum(lngs) / len(lngs))]
        candidates += [(rnd.uniform(min(lats), max(lats)), rnd.uniform(min(lngs), max(lngs))) for _ in range(4000)]
        for lat, lng in candidates:
            if tf.timezone_at(lat=lat, lng=lng) == zone:
                return lat, lng
    return None


def instants(zone, year, day_stride):
    """Every hour on every day_stride-th day of the year, plus every hour for 3 days around each offset change."""
    tz = ZoneInfo(zone)
    start = datetime(year, 1, 1, tzinfo=UTC)
    out = set()
    t, prev = start, start.astimezone(tz).utcoffset()
    while t.year == year:
        offset = t.astimezone(tz).utcoffset()
        if offset != prev:
            out.update(t + k * AN_HOUR for k in range(-36, 37))
        prev = offset
        t += AN_HOUR
    day = start
    while day.year == year:
        out.update(day + h * AN_HOUR for h in range(24))
        day += timedelta(days=day_stride)
    return sorted(out)


def observer(lat, lng):
    obs = ephem.Observer()
    obs.lat, obs.long, obs.elev = lat, lng, 0.0
    obs.pressure = 0
    return obs


def utc(ephem_date):
    return ephem.Date(ephem_date).datetime().replace(tzinfo=UTC)


def true_phase(dt):
    date = ephem.Date(dt)
    last_new, next_new = ephem.previous_new_moon(date), ephem.next_new_moon(date)
    return PHASES[math.floor((date - last_new) / (next_new - last_new) * 8 + 0.5) & 7]


def sun_crosses(obs, altitude, limb, lo, hi):
    """Whether the sun's altitude (upper limb or center) crosses altitude between lo and hi, sampled every 5 min."""
    sun, alts, t = ephem.Sun(), [], lo
    while t <= hi:
        obs.date = t
        sun.compute(obs)
        alts.append(math.degrees(sun.alt + (sun.radius if limb else 0)))
        t += timedelta(minutes=5)
    return max(alts) > altitude + 0.05 and min(alts) < altitude - 0.05, min(alts), max(alts)


def check_zone(job):
    zone, lat, lng, year, day_stride = job
    tz = ZoneInfo(zone)
    slat, slng = str(lat), str(lng)
    issues = defaultdict(list)
    counts = Counter()
    captured = []
    real_object_ephemeris = wsgi.object_ephemeris

    def spy(*args, **kwargs):
        result = real_object_ephemeris(*args, **kwargs)
        captured.append(result)
        return result

    for now in instants(zone, year, day_stride):
        counts['instants'] += 1
        at = f'now={now:%Y-%m-%dT%H:%MZ}'

        # Day start: local solar noon, within the equation of time (< 17 min) of mean solar noon
        try:
            dt = wsgi.start_of_astronomical_day(observer(slat, slng), now)
        except Exception as e:
            issues['day-start:exception'].append(f'{at} {type(e).__name__}: {e}')
            continue
        mean_noon_h = (12 - lng / 15) % 24
        dt_h = dt.hour + dt.minute / 60 + dt.second / 3600
        if min(abs(dt_h - mean_noon_h), 24 - abs(dt_h - mean_noon_h)) * 60 > 17:
            issues['day-start:not-solar-noon'].append(f'{at} dt={dt.isoformat()}')
        if not dt <= now < dt + timedelta(hours=24, minutes=5):
            issues['day-start:not-within-a-day'].append(f'{at} dt={dt.isoformat()}')

        # Every page value, as the app computes it
        frozen = now

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

        vals, data = {}, {}
        with mock.patch('wsgi.datetime', FakeDatetime), mock.patch('wsgi.object_ephemeris', spy):
            for key in EVENING + MORNING + MOON:
                captured.clear()
                try:
                    vals[key] = wsgi.twilight(key, slat, slng, 0.0, zone)
                except Exception as e:
                    issues[f'{key}:exception'].append(f'{at} {type(e).__name__}: {e}')
                    vals[key] = None
                data[key] = captured[-1]['data'] if captured else None
        empty = [k for k, v in vals.items() if v in (None, '', 'None')]
        if empty:
            issues['value:empty'].append(f'{at} {", ".join(empty)}')

        for key, d in data.items():
            if d is not None and key in EVENING + MORNING + ['moonrise', 'moonset']:
                if d.utcoffset() != d.astimezone(tz).utcoffset() or vals[key] != d.strftime("%b %d %H:%M:%S %Z"):
                    issues['print:wrong-zone'].append(f'{at} {key}={vals[key]}')

        # Sun: within the day, in order; N/A only when the altitude is really never crossed
        sun = {k: data[k] for k in EVENING + MORNING if data[k] is not None}
        obs = observer(slat, slng)
        for k, d in sun.items():
            if not dt < d < dt + timedelta(hours=25):
                issues['sun:outside-day'].append(f'{at} {k}={vals[k]}')
            obs.date = d
            body = ephem.Sun(obs)
            alt = math.degrees(body.alt + (body.radius if k in ('sunset', 'sunrise') else 0))
            if abs(alt - ALTITUDES[k]) > 0.02:
                issues['sun:wrong-altitude'].append(f'{at} {k}={vals[k]} sun at {alt:.3f} deg, expected {ALTITUDES[k]:.3f}')
        seq = [k for k in EVENING + MORNING if k in sun]
        for a, b in zip(seq, seq[1:]):
            if not sun[a] < sun[b]:
                issues['sun:out-of-order'].append(f'{at} {a}={vals[a]} !< {b}={vals[b]}')
                break
        not_available = [k for k in EVENING + MORNING if vals[k] and vals[k].startswith('N/A')]
        if not_available:
            obs = observer(slat, slng)
            obs.date = dt
            solar_midnight = utc(obs.next_antitransit(ephem.Sun()))
            obs.date = dt
            next_noon = utc(obs.next_transit(ephem.Sun()))
            for k in not_available:
                lo, hi = (dt, solar_midnight) if k in EVENING else (solar_midnight, next_noon)
                crosses, lo_alt, hi_alt = sun_crosses(obs, ALTITUDES[k], k in ('sunset', 'sunrise'), lo, hi)
                if crosses:
                    issues['sun:false-NA'].append(f'{at} {k} N/A but altitude spans {lo_alt:.2f}..{hi_alt:.2f}')
                counts['na_checked'] += 1

        # Moon: events after the day start, layout flag consistent, phase matches ephem
        for k in ('moonrise', 'moonset'):
            if data[k] is not None and not dt < data[k] < dt + timedelta(hours=50):
                issues['moon:outside-window'].append(f'{at} {k}={vals[k]}')
        moonset = real_object_ephemeris(ephem.Moon(), observer(slat, slng), dt, zone, 'set')['data']
        expected_flag = 'True' if moonset and moonset - dt < wsgi.HALF_A_DAY else 'False'
        if vals['moonset_ante_astro_noon_p'] != expected_flag:
            issues['moon:flag-mismatch'].append(at)
        if vals['moon_phase'] != true_phase(dt):
            issues['moon:wrong-phase'].append(f'{at} {vals["moon_phase"]} != {true_phase(dt)}')

    return zone, lat, lng, dict(counts), {k: (len(v), v[:3]) for k, v in issues.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--year', type=int, default=datetime.now(UTC).year)
    parser.add_argument('--day-stride', type=int, default=5, help='check every Nth day (default 5)')
    parser.add_argument('--quick', action='store_true', help='same as --day-stride 30')
    parser.add_argument('--zones', nargs='*', help='only zones starting with any of these prefixes')
    args = parser.parse_args()
    day_stride = 30 if args.quick else args.day_stride

    tf = TimezoneFinder()
    tab = zone_tab_coords()
    zones = sorted(z for z in tf.timezone_names if not args.zones or any(z.startswith(p) for p in args.zones))
    jobs, unplaced = [], []
    for zone in zones:
        point = point_in_zone(tf, zone, tab)
        if point is None:
            unplaced.append(zone)
        else:
            jobs.append((zone, point[0], point[1], args.year, day_stride))
    print(f'{len(jobs)} zones, {args.year}, every {day_stride} days plus DST changes', flush=True)

    with mp.Pool() as pool:
        results = sorted(pool.imap_unordered(check_zone, jobs))

    totals = Counter()
    by_issue = defaultdict(list)
    for zone, lat, lng, counts, issues in results:
        totals.update(counts)
        for k, (n, examples) in issues.items():
            by_issue[k].append((zone, lat, lng, n, examples))
    print(f"instants checked: {totals['instants']:,}")
    print(f"N/A sun values verified: {totals['na_checked']:,}")
    if unplaced:
        print(f'zones with no point found (not checked): {", ".join(unplaced)}')
    for k in sorted(by_issue):
        zs = by_issue[k]
        print(f"\nFAIL {k}: {sum(z[3] for z in zs):,} cases in {len(zs)} zones")
        for zone, lat, lng, n, examples in sorted(zs, key=lambda z: -z[3])[:8]:
            print(f"   {zone} ({lat:.2f}, {lng:.2f}) x{n}: {examples[0]}")
    if by_issue or unplaced:
        sys.exit(1)
    print('OK: no invariant violations')


if __name__ == '__main__':
    main()
