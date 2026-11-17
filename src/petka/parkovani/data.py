"""The curated parking data, kept as files in data/parkovani (moved from the app Otevřené
Pardubice on 16. 11. 2026). Each file names its source, the date it was last checked against it
(`checked`) and, where the source says so, from when it is valid:

    sms-kody.json          DPMP's SMS codes by the operator's area number
    cenik.json             the regulation's price list by locality (nařízení 3/2026)
    automaty.json          the pay machines
    zony.json              the zones A, B, C (annex 1 of nařízení 2/2026)
    prilehla-oblast.json   the area adjacent to zone B (annex 6)
    lokality.json          the localities and visitor places (annexes 2–4)
    useky.json             the paid street sections as bands, paired with the operator's lots
    oblasti.json           areas as people name them (centre, U Mlýnů…): our own lists of lots

They change when the regulation or DPMP's table does; then they are edited by hand (see
docs/parkovani.md). The lots themselves come from the live source every day.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "data" / "parkovani"
FILES = {
    "smsCodes": "sms-kody.json", "tariffs": "cenik.json", "machines": "automaty.json", "zones": "zony.json",
    "adjacent": "prilehla-oblast.json", "localities": "lokality.json", "sections": "useky.json",
    "areas": "oblasti.json",
}
# what each file's payload is under
PAYLOAD = {"smsCodes": "codes", "tariffs": "tariffs", "machines": "machines", "zones": "zones",
           "adjacent": "area", "localities": ("localities", "visitor"), "sections": "sections",
           "areas": "areas"}
META = ("source", "url", "valid_from", "checked", "note")


@lru_cache
def raw(key: str) -> dict:
    return json.loads((ROOT / FILES[key]).read_text())


def payload(key: str):
    """What a file holds without its metadata (a list, a dict, or for localities a dict of both
    lists)."""
    d, p = raw(key), PAYLOAD[key]
    return {k: d[k] for k in p} if isinstance(p, tuple) else d[p]


def meta(key: str) -> dict:
    """A file's source, url, valid_from, checked and note (those it has)."""
    d = raw(key)
    return {k: d[k] for k in META if d.get(k)}


@lru_cache
def version() -> str:
    """A hash of every file: part of the export's ETag, so an edited file reaches the app at once."""
    h = hashlib.sha256()
    for name in sorted(FILES.values()):
        h.update((ROOT / name).read_bytes())
    return h.hexdigest()[:16]
