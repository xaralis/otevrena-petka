"""The NDIC snapshot "DATEX II – Běžné dopravní informace (snímek)" (x-source:cz-ndic_d2-common-pull,
format cz-ndic_d2-common-v1.1, DATEX II v2.3): every traffic information valid now or later in
the country – closures, road works, accidents, broken-down vehicles – fetched with HTTP PULL
(Basic authentication, gzip) from the address ŘSD assigned to our subscription.

`parse` turns one snapshot into plain records. A record's place is the S-JTSK points of its
Global Network stretch (start, end), converted to WGS84; the TMC (ALERT-C) locations are not
read: their content may not be published (licence of the TMC location table).

Settings, from the environment: NDIC_URL, NDIC_USER, NDIC_PASSWORD.
"""

import datetime as dt
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

D2 = "{http://datex2.eu/schema/2/2_0}"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
TIMEOUT = 120


@dataclass
class Record:
    id: str
    situation: str
    version: int
    kind: str                       # RoadOrCarriagewayOrLaneManagement, Accident, …
    details: list[str]              # roadClosed, laneClosures, accidentInvolvingHeavyLorries, …
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None
    comment: str
    source: str
    road: str | None
    points: list[tuple[float, float]] = field(default_factory=list)   # (lon, lat), WGS84
    version_at: dt.datetime | None = None


def settings() -> tuple[str, str, str] | None:
    """(url, user, password) of our subscription, or None until ŘSD has assigned them."""
    url, user, pw = (os.environ.get(k, "") for k in ("NDIC_URL", "NDIC_USER", "NDIC_PASSWORD"))
    return (url, user, pw) if url and user and pw else None


def fetch(client, url: str, user: str, password: str) -> bytes:
    """The snapshot as XML bytes (the server compresses it; httpx unpacks)."""
    r = client.get(url, auth=(user, password), headers={"Accept-Encoding": "gzip"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el) -> str:
    return " ".join((el.text or "").split()) if el is not None else ""


def _time(el) -> dt.datetime | None:
    t = _text(el)
    return dt.datetime.fromisoformat(t) if t else None


def _czech(el) -> str:
    """The Czech value of a multilingual string (values/value[@lang]), whitespace normalised."""
    if el is None:
        return ""
    vals = el.findall(f"{D2}values/{D2}value")
    pick = next((v for v in vals if (v.get("lang") or "").startswith("cs")), vals[0] if vals else None)
    return _text(pick)


_transformer = None


def to_wgs(x: float, y: float) -> tuple[float, float]:
    """S-JTSK (EPSG:5514, the negative east/north NDIC uses) -> (lon, lat) WGS84."""
    global _transformer
    if _transformer is None:
        from pyproj import Transformer
        _transformer = Transformer.from_crs(5514, 4326, always_xy=True)
    lon, lat = _transformer.transform(x, y)
    return round(lon, 6), round(lat, 6)


def _points(rec) -> list[tuple[float, float]]:
    """The record's place: its S-JTSK points in document order (start, end of each stretch),
    or WGS84 point coordinates where a Point location gives them; repeats dropped."""
    out: list[tuple[float, float]] = []
    for g in rec.iter(f"{D2}groupOfLocations"):
        for el in g.iter():
            name = _local(el.tag)
            if name == "sjtskPointCoordinates":
                x, y = el.find(f"{D2}sjtskX"), el.find(f"{D2}sjtskY")
                if x is not None and y is not None:
                    p = to_wgs(float(_text(x)), float(_text(y)))
                    if not out or out[-1] != p:
                        out.append(p)
            elif name == "pointCoordinates":
                la, lo = el.find(f"{D2}latitude"), el.find(f"{D2}longitude")
                if la is not None and lo is not None:
                    p = (round(float(_text(lo)), 6), round(float(_text(la)), 6))
                    if not out or out[-1] != p:
                        out.append(p)
    return out


def parse(xml: bytes) -> tuple[dt.datetime | None, list[Record]]:
    """(publicationTime, records) of one snapshot. A DOCTYPE is refused: DATEX never has one,
    and without it the parser expands no entities (XXE, billion laughs)."""
    if b"<!DOCTYPE" in xml[:4096].upper():
        raise ValueError("DATEX snapshot with a DOCTYPE")
    root = ET.fromstring(xml)
    pub = root.find(f"{D2}payloadPublication")
    if pub is None:
        return None, []
    out = []
    for sit in pub.iter(f"{D2}situation"):
        for rec in sit.findall(f"{D2}situationRecord"):
            spec = rec.find(f"{D2}validity/{D2}validityTimeSpecification")
            comments = [c for c in (_czech(gc.find(f"{D2}comment")) for gc in rec.findall(f"{D2}generalPublicComment")) if c]
            details = [_text(el) for el in rec.iter() if _local(el.tag).endswith("Type") and el.tag != rec.tag
                       and _local(el.tag) not in ("linearGeometryType", "vehicleType") and _text(el)]
            road = rec.find(f".//{D2}roadNumber")
            out.append(Record(
                id=rec.get("id") or "", situation=sit.get("id") or "", version=int(rec.get("version") or 0),
                kind=rec.get(XSI_TYPE, "").split(":")[-1],
                details=list(dict.fromkeys(details)),
                starts_at=_time(spec.find(f"{D2}overallStartTime")) if spec is not None else None,
                ends_at=_time(spec.find(f"{D2}overallEndTime")) if spec is not None else None,
                comment=re.sub(r"\s+", " ", "; ".join(comments)).strip(),
                source=_czech(rec.find(f"{D2}source/{D2}sourceName")),
                road=_text(road) or None,
                points=_points(rec),
                version_at=_time(rec.find(f"{D2}situationRecordVersionTime")),
            ))
    return _time(pub.find(f"{D2}publicationTime")), out
