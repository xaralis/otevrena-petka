"""Photos of the reports, served by the portal itself: a phone or a browser loads them from
otevrenapetka.cz, never from dejtip.eu, so Dej Tip doesn't learn who looks at which report.

Only a photo the reporter made public is ever downloaded (`citizen_reports.photo_url` is set only
then, source.photo). The job downloads each one once, shrinks it (longer side MAX_SIDE px, WebP,
the EXIF orientation applied and every metadata block but the colour profile dropped: no GPS,
no camera, no time) and keeps it in `citizen_report_photos`. A photo whose report lost its public
photo, got another one or was deleted goes with it (`prune`, the foreign key's cascade).

The town has ~1 700 public photos; a run downloads at most PER_RUN of them, newest reports first, a
few at a time (WORKERS), so the first fill is spread over a few runs and every run is resumable.
A photo Dej Tip answers with 4xx or that isn't an image is noted as failed and tried again after
RETRY; a network error or 5xx is tried on the next run, and a batch with nothing but such errors
ends the run (Dej Tip is down, don't wait out every timeout).

The URL carries the image's version (a hash of its bytes), so it can be cached forever.
"""

import datetime as dt
import hashlib
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterator

import httpx
from PIL import Image, ImageOps

from ..jobs import Unit

log = logging.getLogger(__name__)

MAX_SIDE = 800              # px, the longer side; a map card and a street page show ~300 px
QUALITY = 75                # WebP; ~25–140 kB a photo, 75–95 kB on average
PER_RUN = 300               # downloads per run (the job runs six times a day)
BATCH = 25                  # downloads committed together
WORKERS = 4                 # downloads at a time
MAX_BYTES = 20_000_000      # a phone's photo is a few MB; anything larger isn't one
RETRY = dt.timedelta(days=7)   # a failed photo (404, not an image) is tried again after this
TIMEOUT = httpx.Timeout(30, connect=10)
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/")
VERSION_SQL = """(SELECT p.version FROM citizen_report_photos p
                  WHERE p.id = citizen_reports.id AND p.image IS NOT NULL) AS photo_version"""


# --- the image --------------------------------------------------------------------------------

def shrink(data: bytes) -> bytes:
    """A downloaded photo as WebP, longer side at most MAX_SIDE px (never enlarged), turned the way
    its EXIF says and without any metadata except the colour profile. Raises OSError (Pillow's
    UnidentifiedImageError) or Image.DecompressionBombError for what isn't a sane image."""
    with Image.open(io.BytesIO(data)) as im:
        im.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))      # JPEG: decode at a fraction of the size
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if _alpha(im) else "RGB")
        im.info = {}            # what a save could carry over (EXIF with GPS, XMP, comments)
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=QUALITY, method=6, **({"icc_profile": icc} if icc else {}))
        return out.getvalue()


def _alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA") or "transparency" in im.info


def version(image: bytes) -> str:
    """The image's version in its URL and ETag: the start of its SHA-256."""
    return hashlib.sha256(image).hexdigest()[:16]


def href(report_id: int, ver: str | None, base: str = "") -> str | None:
    """Where the portal serves a report's photo; None while it has none (not public, or not
    downloaded yet). `base` is PUBLIC_URL for the API, empty for the portal's own pages."""
    return f"{base}/api/v1/podnety/{report_id}/foto/{ver}.webp" if ver else None


# --- the database ------------------------------------------------------------------------------

def prune(conn) -> int:
    """Drop the photos whose report no longer has that public photo (made private, replaced).
    Deleted reports take their photo along (ON DELETE CASCADE)."""
    return conn.execute("""DELETE FROM citizen_report_photos p USING citizen_reports r
                           WHERE p.id = r.id AND r.photo_url IS DISTINCT FROM p.source_url""").rowcount


def todo(conn, limit: int = PER_RUN) -> list[tuple[int, str]]:
    """(id, Dej Tip URL) of the public photos to download: never tried, or failed more than RETRY
    ago; the newest reports first (they are looked at most)."""
    rows = conn.execute("""SELECT r.id, r.photo_url FROM citizen_reports r
                           LEFT JOIN citizen_report_photos p ON p.id = r.id
                           WHERE r.photo_url IS NOT NULL
                             AND (p.id IS NULL OR (p.image IS NULL AND p.fetched_at < now() - %s))
                           ORDER BY r.reported_at DESC, r.id DESC LIMIT %s""", (RETRY, limit)).fetchall()
    return [(r["id"], r["photo_url"]) for r in rows]


def save(conn, report_id: int, source_url: str, image: bytes | None, error: str | None = None) -> None:
    """Keep a shrunk photo, or note that it failed (image None) so it waits RETRY."""
    conn.execute("""INSERT INTO citizen_report_photos (id, source_url, image, version, error)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET source_url = EXCLUDED.source_url, image = EXCLUDED.image,
                      version = EXCLUDED.version, error = EXCLUDED.error, fetched_at = now()""",
                 (report_id, source_url, image, version(image) if image else None, error))


def get(report_id: int) -> dict | None:
    """The stored photo of a report ({version, image}), None when there is none."""
    from .. import db
    with db.pool().connection() as conn:
        return conn.execute("""SELECT version, image FROM citizen_report_photos
                               WHERE id = %s AND image IS NOT NULL""", (report_id,)).fetchone()


# --- the download ------------------------------------------------------------------------------

class Later(Exception):
    """A download to try again on the next run (network error, Dej Tip's 5xx)."""


def download(client: httpx.Client, url: str) -> bytes:
    """The photo's bytes. Raises Later for what may pass, ValueError for what won't (4xx, not
    an image, too large)."""
    try:
        with client.stream("GET", url, timeout=TIMEOUT) as r:
            if r.status_code >= 500:
                raise Later(f"HTTP {r.status_code}")
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            if not r.headers.get("content-type", "image/").startswith("image/"):
                raise ValueError(f"not an image: {r.headers['content-type']}")
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError("larger than MAX_BYTES")
            return bytes(data)
    except httpx.HTTPError as e:
        raise Later(f"{type(e).__name__}: {e}") from e


def _one(client: httpx.Client, url: str) -> tuple[bytes | None, str | None, bool]:
    """(image, error, later) for one photo."""
    try:
        return shrink(download(client, url)), None, False
    except Later as e:
        return None, str(e), True
    except (ValueError, OSError, Image.DecompressionBombError) as e:
        return None, f"{type(e).__name__}: {e}", False


def fetch(conn, client: httpx.Client, batch: list[tuple[int, str]]) -> dict:
    """Download and store one batch, WORKERS at a time; the caller commits."""
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda t: _one(client, t[1]), batch))
    stored = failed = later = 0
    for (rid, url), (image, error, again) in zip(batch, results):
        if again:
            later += 1
            log.info("podnety photo %s: later (%s)", rid, error)
            continue
        save(conn, rid, url, image, error)
        stored += image is not None
        failed += image is None
    return {"stored": stored, "failed": failed, "later": later,
            "kb": sum(len(r[0]) for r in results if r[0]) // 1000}


@dataclass
class _State:
    stop: bool = False


def units(conn, client, limit: int = PER_RUN) -> Iterator[Unit]:
    """The job's photo work: prune first, then up to `limit` downloads in batches of BATCH, each
    committed on its own (a run cut short keeps what it got). A batch of nothing but network
    errors ends the run."""
    yield Unit(("fotky", "smazane"), "fotky: smazané", lambda conn, client: {"removed": prune(conn)})
    wanted = todo(conn, limit)
    state = _State()
    for i in range(0, len(wanted), BATCH):
        if state.stop:
            log.warning("podnety photos: Dej Tip doesn't answer, %d left for the next run", len(wanted) - i)
            break
        batch = wanted[i:i + BATCH]

        def run(conn, client, batch=batch):
            summary = fetch(conn, client, batch)
            state.stop = summary["later"] == len(batch)
            return summary
        yield Unit(("fotky", i // BATCH + 1), f"fotky {i + 1}–{i + len(batch)} z {len(wanted)}", run)
