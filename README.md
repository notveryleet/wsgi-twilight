wsgi-twilight
=============

Python WSGI server to show sun and moon ephemerides for my house and for Kopernik Observatory in Vestal, NY. For giggles it also includes the ephemerides for Greenwich Observatory.

NOW! With more geocoding!

Currently returns info for the requester's location.

Future directions include allowing input for arbitrary locations.

Testing
-------

`tests/check_all_zones.py` checks the ephemeris for every timezone (each at a
point inside it), hourly through the year and around every DST change: event
order, sun altitude at each event, N/A only when the sun really doesn't cross,
times printed in the right zone, and the moon phase. It exits 1 on any failure.

    python tests/check_all_zones.py            # full run, ~5 min on 8 cores
    python tests/check_all_zones.py --quick    # every 30th day, ~1 min
    python tests/check_all_zones.py --zones Antarctica/ America/Inuvik

The named routes (e.g. `/nc`) use fixed coordinates and make no geolocation
calls, so use them for local testing; `/` geolocates the requester.
