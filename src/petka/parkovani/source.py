"""ChytřejšíParking, the app API of the town's parking operator (DPMP) at
pardubice.chytrejsiparking.cz: public, without a token, but undocumented and without a licence.

Two answers are read:

- `parking/occupancy`: every lot (the operator's group of spaces, deviceClass ParkingZone) with
  its name, position, price list, the number of its area (`configParking.zoneNumber`, the key of
  DPMP's SMS codes) and its free and total places now. No time of measurement.
- `parking/locations`: the operator's localities; a lot's locality code („A-1“, „L.2“) is the
  first part of the location's `zoneNumber` („A-1/20“, „L.2/A-1/2“), found by (areaID,
  locationID) – a locationID alone repeats across areas.

`lots_of` keeps a lot's facts as the source says them; petka.parkovani.build joins them with the
curated data (SMS codes, the regulation's prices).
"""

BASE = "https://pardubice.chytrejsiparking.cz/admin/api/app/parking"
OCCUPANCY = f"{BASE}/occupancy?placeTypes=&locale=cs"
LOCATIONS = f"{BASE}/locations?locale=cs"
# no personal data: a name and where to read what it is for
USER_AGENT = "OtevrenaPetka/1 (+https://otevrenapetka.cz/data#parkovani)"
TIMEOUT = 30


class SourceError(RuntimeError):
    pass


def fetch(client, url: str) -> list[dict]:
    """The `data` list of one answer; an HTTP error, an answer that is not JSON or one without a
    list raises SourceError."""
    try:
        r = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
    except Exception as e:      # httpx errors, a JSON decode error
        raise SourceError(f"{url}: {e}") from e
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise SourceError(f"{url}: no data list (status {body.get('status') if isinstance(body, dict) else '?'})")
    return data


def _num(v) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def occupancy_of(data: list[dict]) -> dict[str, tuple[int, int]]:
    """{lot id: (free, total)} of the occupancy answer; a lot with no places is left out."""
    out = {}
    for p in data:
        d = p.get("data") or {}
        total = _num(d.get("total"))
        if p.get("devID") and total:
            out[p["devID"]] = (min(_num(d.get("free")), total), total)
    return out


def localities_of(locations: list[dict]) -> dict[tuple, str]:
    """{(areaID, locationID): locality code} of the locations answer."""
    out = {}
    for loc in locations:
        c = loc.get("config") or {}
        code = str(c.get("zoneNumber") or "").split("/")[0].strip()
        if code:
            out[(c.get("areaID"), c.get("locationID"))] = code
    return out


def lots_of(occupancy: list[dict], locations: list[dict]) -> list[dict]:
    """The lots with places, sorted by id, as plain facts:

    id, name, area (the operator's name for the part of town), at [lon, lat], paid (a ticket
    can be bought), description, number (the area's number, the SMS codes' key), locality,
    kind (mixed | visitor | resident), capacity (total places), prices (the operator's price
    list: [{day, time, price}])."""
    locs = localities_of(locations)
    out = []
    for p in occupancy:
        if not p.get("devID") or not _num((p.get("data") or {}).get("total")):
            continue
        cp = p.get("configParking") or {}
        pos = p.get("position") or {}
        try:
            at = [round(float(pos["lng"]), 6), round(float(pos["lat"]), 6)]
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            "id": p["devID"], "name": (p.get("deviceName") or "").strip(), "area": p.get("appName") or "",
            "at": at, "paid": bool(p.get("ticketID")), "description": p.get("description") or "",
            "number": str(cp.get("zoneNumber") or ""), "locality": locs.get((cp.get("areaID"), cp.get("locationID"))),
            "kind": cp.get("specification") or None, "capacity": _num((p.get("data") or {}).get("total")),
            "prices": [{k: str(x.get(k) or "") for k in ("day", "time", "price")}
                       for x in ((p.get("config") or {}).get("priceList") or [])],
        })
    return sorted(out, key=lambda lot: lot["id"])
