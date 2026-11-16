"""Browser notifications (Web Push) of Můj přehled: the events of petka.ulice.feed for the streets
and kinds a browser chose, each sent once.

A subscription is the browser's address at its push service and the choice; nothing else. When
it is saved (new, or the choice changed) every event it could be sent now is marked as sent, so
it hears only of what comes after. `deliver` (the `muj-prehled-push` job) sends what is new: one
message per event, or one that sums them up when there are more than BURST. A subscription the
push service answers 404/410 for is gone (the person blocked notifications or left) and deleted.

The keys (VAPID) are in the environment: VAPID_PUBLIC_KEY (the page passes it to the browser),
VAPID_PRIVATE_KEY, VAPID_SUBJECT (who the push services can write to; the portal's URL).
"""

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

from ..cisteni import words as cw
from . import feed

log = logging.getLogger(__name__)
BURST = 3               # more new events than this at once: one message that sums them up
TTL = 24 * 3600         # a push service keeps an undelivered message this long (seconds)


@dataclass(frozen=True)
class Keys:
    public: str
    private: str
    subject: str


def keys() -> Keys | None:
    pub, priv = os.environ.get("VAPID_PUBLIC_KEY"), os.environ.get("VAPID_PRIVATE_KEY")
    if not pub or not priv:
        return None
    return Keys(pub, priv, os.environ.get("VAPID_SUBJECT") or os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz"))


def save(conn, sub: dict, obvod: str, streets: list[tuple[str, str]], kinds: list[str], src: feed.Sources,
         now: dt.datetime) -> None:
    """Store a subscription with its choice (a new one, or the same browser's new choice) and mark
    what it could be sent now as sent."""
    conn.execute("""INSERT INTO push_subscriptions (endpoint, p256dh, auth, obvod, streets, kinds)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (endpoint) DO UPDATE SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth,
                      obvod = EXCLUDED.obvod, streets = EXCLUDED.streets, kinds = EXCLUDED.kinds, updated_at = now()""",
                 (sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], obvod, [s for _, s in streets], kinds))
    _mark(conn, sub["endpoint"], [e.key for e in feed.events(streets, src, now, set(kinds))])


def renew(conn, old: str, sub: dict) -> bool:
    """The browser renewed its subscription (pushsubscriptionchange): the same choice, a new address."""
    return conn.execute("""UPDATE push_subscriptions SET endpoint = %s, p256dh = %s, auth = %s, updated_at = now()
                           WHERE endpoint = %s""", (sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], old)).rowcount > 0


def drop(conn, endpoint: str) -> bool:
    return conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,)).rowcount > 0


def _mark(conn, endpoint: str, keys_: list[str]) -> None:
    if keys_:
        conn.execute("""INSERT INTO push_sent (endpoint, key) SELECT %s, unnest(%s::text[])
                        ON CONFLICT DO NOTHING""", (endpoint, keys_))


def messages(new: list[feed.Event], names: list[str], base: str, page: str) -> list[dict]:
    """What to send for the new events (newest first): each on its own, or one for all of them."""
    if len(new) > BURST:
        n = len(new)
        return [{"title": f"{n} {cw.plural(n, 'novinka', 'novinky', 'novinek')} "
                          + (f"v ulici {names[0]}" if len(names) == 1 else "ve vašich ulicích"),
                 "body": "; ".join(e.title for e in new[:3]) + ("…" if len(new) > 3 else ""),
                 "url": base + page, "tag": "petka-souhrn"}]
    return [{"title": e.title, "body": e.text if len(e.text) <= 180 else e.text[:179].rsplit(" ", 1)[0] + "…",
             "url": e.path if e.path.startswith("http") else base + e.path, "tag": e.key} for e in reversed(new)]


class Gone(Exception):
    """The push service no longer knows the subscription."""


def webpush_sender(k: Keys) -> Callable[[dict, dict], None]:
    """send(subscription_info, message) through pywebpush; raises Gone on 404/410."""
    from pywebpush import WebPushException, webpush

    def send(info: dict, msg: dict) -> None:
        try:
            webpush(info, json.dumps(msg, ensure_ascii=False), vapid_private_key=k.private,
                    vapid_claims={"sub": k.subject}, ttl=TTL, timeout=10)
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                raise Gone from e
            raise
    return send


def deliver(conn, send: Callable[[dict, dict], None], sources: Callable[[str], feed.Sources],
            names: Callable[[str], dict[str, str]], base: str, now: dt.datetime) -> dict:
    """Send every subscription what is new for it; returns counts for the job's report."""
    out = {"subscriptions": 0, "messages": 0, "gone": 0, "failed": 0}
    src, known = {}, {}
    for s in conn.execute("SELECT * FROM push_subscriptions ORDER BY created_at").fetchall():
        out["subscriptions"] += 1
        o = s["obvod"]
        if o not in src:
            src[o], known[o] = sources(o), names(o)
        streets = [(known[o][slug], slug) for slug in s["streets"] if slug in known[o]]
        evs = feed.events(streets, src[o], now, set(s["kinds"]))
        sent = {r["key"] for r in conn.execute("SELECT key FROM push_sent WHERE endpoint = %s", (s["endpoint"],))}
        new = [e for e in evs if e.key not in sent]
        if not new:
            continue
        page = "/muj-prehled?ulice=" + ",".join(s["streets"])
        info = {"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
        try:
            for m in messages(new, [n for n, _ in streets], base, page):
                send(info, m)
                out["messages"] += 1
        except Gone:
            drop(conn, s["endpoint"])
            out["gone"] += 1
            continue
        except Exception as e:      # one browser's push service failing is not the others' business
            log.warning("push to %s failed: %s", s["endpoint"][:60], e)
            out["failed"] += 1
            continue
        _mark(conn, s["endpoint"], [e.key for e in new])
        conn.execute("UPDATE push_subscriptions SET sent_at = now() WHERE endpoint = %s", (s["endpoint"],))
    conn.execute("DELETE FROM push_sent WHERE at < %s", (now - dt.timedelta(days=feed.WINDOW + 7),))
    return out
