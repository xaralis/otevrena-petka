"""Commands of the street pages (`petka ulice-…`)."""

import json

from ..section import Command


def update(a) -> int:
    """Fetch every street of the town from RÚIAN into ruian_cache (only those missing), and the
    obvody's polygons, so each obvod knows all its streets (petka.ulice.streets)."""
    import psycopg
    from psycopg.rows import dict_row

    from .. import db, obvody
    from ..cisteni.ruian import Ruian
    from . import streets
    with psycopg.connect(db.URL, autocommit=True, row_factory=dict_row) as conn:
        r = Ruian(conn)
        r.prefetch(kod for kod, _ in r.streets())
        r.obvody()
        fetched = r.cache.fetched
    streets._cache.clear()
    print(json.dumps({"fetched": fetched, "streets": {o: len(streets.streets(o)) for o in obvody.BY_ID}},
                     ensure_ascii=False))
    return 0


def push(a) -> int:
    """Send the browser notifications of Můj přehled (petka.ulice.push): what is new since the last run."""
    import datetime as dt

    from .. import jobs as runner
    from . import feed, push as p, streets
    from .web import _origin
    k = p.keys()
    if k is None:
        print(json.dumps({"skipped": "VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY not set", "failures": []}))
        return 0
    send = p.webpush_sender(k)
    names = lambda obvod: {s.slug: s.name for s in streets.streets(obvod).values()}
    run = lambda conn, client: p.deliver(conn, send, feed.sources, names, _origin(), dt.datetime.now(feed.TZ))
    report = runner.run("muj-prehled-push", "push", lambda conn, client: [runner.Unit(("push",), "push", run)])
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 1 if report["failures"] else 0


def vapid(a) -> int:
    """New VAPID keys for the secret (once; a new pair invalidates every subscription)."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    priv = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    pub = b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
    return 0


COMMANDS = [
    Command("muj-prehled-push", "send the browser notifications of Můj přehled: what is new in the chosen streets "
            "since the last run (idempotent; hourly in the day)", push),
    Command("muj-prehled-vapid", "print a new pair of VAPID keys for the push secret", vapid),
    Command("ulice-update", "fetch the town's streets from RÚIAN (ČÚZK) for the street pages, only what "
            "is missing (idempotent)", update),
]
