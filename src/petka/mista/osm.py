"""The places of the town from OpenStreetMap: one Overpass query for the whole statutory city and
how its answer becomes places (docs/mista.md is the format).

Kinds: the places of „Co je v okolí“ of the app Pardubice do kapsy (potraviny, bankomat,
lekarna, jidlo, pamatky, wc, posta; selection and Czech wording carried over unchanged from the
app's data-tools/build_places.mjs), bike racks (stojan), sorted-waste containers (kontejner)
and recycling centres (dvur), and every other named place a person may search for by its name
(misto, petka.mista.other: firms, offices, doctors, schools, shops, sports grounds, named
buildings and works). Pure functions over Overpass elements; `fetch` is the only one
that goes to the network.

Overpass etiquette: a descriptive User-Agent without personal data, one query a day, a
timeout, one retry after a pause on 429/502/504. OVERPASS_URL overrides the server.
"""

import os
import re
import time

from . import other

KINDS = ("potraviny", "bankomat", "lekarna", "jidlo", "pamatky", "wc", "posta", "stojan", "kontejner", "dvur", "vykupna", "misto")
WASTE = ("papir", "plast", "sklo", "kov", "textil", "elektro", "baterie", "olej", "bio")

OVERPASS = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = "OtevrenaPetka/1 (+https://otevrenapetka.cz/data#mista)"
TIMEOUT = 240       # s, longer than the query's own [timeout:180]
RETRY_ON = {429, 502, 504}
RETRY_AFTER = 60    # s before the one retry

# The statutory city by its boundary, all eight obvody.
AREA = 'area["name"="Pardubice"]["admin_level"="8"]["boundary"="administrative"]->.city;'

QUERY = f"""[out:json][timeout:180];
{AREA}
(
  nwr["shop"~"^(supermarket|convenience|greengrocer|bakery|butcher|deli|grocery|general|health_food|farm|frozen_food)$"](area.city);
  nwr["amenity"="atm"](area.city);
  nwr["amenity"="bank"]["atm"="yes"](area.city);
  nwr["amenity"="pharmacy"](area.city);
  nwr["amenity"~"^(restaurant|cafe|fast_food|pub|bar|ice_cream|biergarten)$"](area.city);
  nwr["historic"]["name"](area.city);
  nwr["tourism"~"^(museum|attraction)$"]["name"](area.city);
  nwr["amenity"="place_of_worship"]["name"](area.city);
  nwr["amenity"="toilets"](area.city);
  nwr["amenity"="post_office"](area.city);
  nwr["amenity"="bicycle_parking"](area.city);
  nwr["amenity"="recycling"](area.city);
  // misto: every other named place (petka.mista.other)
  nwr["name"]["shop"](area.city);
  nwr["brand"]["shop"](area.city);
  nwr["name"]["amenity"](area.city);
  nwr["brand"]["amenity"](area.city);
  nwr["name"]["office"](area.city);
  nwr["name"]["craft"](area.city);
  nwr["name"]["healthcare"](area.city);
  nwr["name"]["tourism"](area.city);
  nwr["name"]["leisure"](area.city);
  nwr["name"]["club"](area.city);
  nwr["name"]["emergency"](area.city);
  nwr["name"]["government"](area.city);
  nwr["name"]["company"](area.city);
  nwr["name"]["man_made"~"^(works|wastewater_plant|water_works|observatory|windmill|watermill|silo|water_tower|gasometer)$"](area.city);
  wr["name"]["landuse"~"^({"|".join(sorted(other.LANDUSE_PLACES))})$"](area.city);
  wr["name"]["building"](area.city);
  nwr["name"]["natural"~"^({"|".join(sorted(other.NATURAL_PLACES))})$"](area.city);
  nwr["name"]["place"~"^({"|".join(sorted(other.PLACE_PLACES))})$"](area.city);
);
out center tags;"""

# --- „Co je v okolí“: as the app's build_places.mjs -----------------------------------------

SHOP = {
    "supermarket": "Supermarket", "convenience": "Večerka", "greengrocer": "Ovoce a zelenina", "bakery": "Pekařství",
    "butcher": "Řeznictví", "deli": "Lahůdky", "grocery": "Potraviny", "general": "Smíšené zboží",
    "health_food": "Zdravá výživa", "farm": "Farmářská prodejna", "frozen_food": "Mražené potraviny",
}
FOOD = {
    "restaurant": "Restaurace", "cafe": "Kavárna", "fast_food": "Rychlé občerstvení", "pub": "Hospoda", "bar": "Bar",
    "ice_cream": "Zmrzlina", "biergarten": "Pivní zahrádka",
}
# historic=* not named here is a „Památka“
SIGHT = {
    "castle": "Zámek", "city_gate": "Městská brána", "tower": "Věž", "church": "Kostel", "monument": "Pomník",
    "memorial": "Památník", "ruins": "Zřícenina", "archaeological_site": "Archeologické naleziště",
    "building": "Historická budova", "manor": "Zámeček", "tomb": "Hrobka", "wayside_shrine": "Boží muka",
    "wayside_cross": "Kříž", "fort": "Pevnost", "museum": "Muzeum",
}
SMALL_MEMORIAL = {"plaque", "stolperstein", "blue_plaque"}   # too small to walk to as a sight
NOT_PUBLIC = {"private", "no", "customers", "permit"}         # toilets nobody passing may use
CRYPTO = re.compile(r"bitcoin|crypto|kvakomat", re.I)          # a machine for crypto is no ATM

# --- the kinds Pětka adds -------------------------------------------------------------------

# OSM recycling:<x>=yes -> waste kind, as the app's design/build_data.py RECYCLING_KINDS
RECYCLING = {
    "papir": ("paper", "cardboard", "newspaper", "magazines", "paper_packaging"),
    "plast": ("plastic", "plastic_packaging", "plastic_bottles", "pet_drink_bottles"),
    "sklo": ("glass", "glass_bottles"),
    "kov": ("cans", "metal_packaging", "scrap_metal"),
    "textil": ("clothes", "textiles", "shoes"),
    "elektro": ("electrical_appliances", "electrical_items", "small_appliances", "small_electrical_appliances"),
    "baterie": ("batteries",),
    "olej": ("cooking_oil",),
    "bio": ("green_waste", "organic", "food_waste"),
}
COVERED_RACK = {"shed", "building", "shelter"}
NO_ENTRY = {"private", "no"}        # a rack nobody passing may use


def waste(t: dict) -> list[str]:
    """What a recycling point takes (WASTE order), from its recycling:*=yes tags."""
    return [k for k, keys in RECYCLING.items() if any(t.get(f"recycling:{x}") == "yes" for x in keys)]


def classify(t: dict) -> tuple[str, str] | None:
    """(kind, what in Czech) of an element's tags, or None when it is none of the kinds."""
    shop, amenity = t.get("shop"), t.get("amenity")
    if shop in SHOP:
        return "potraviny", SHOP[shop]
    if amenity == "atm" or (amenity == "bank" and t.get("atm") == "yes"):
        if CRYPTO.search(f"{t.get('name', '')} {t.get('brand', '')} {t.get('operator', '')}"):
            return None
        return "bankomat", "Bankomat u pobočky" if amenity == "bank" else "Bankomat"
    if amenity == "pharmacy":
        return "lekarna", "Lékárna"
    if amenity in FOOD:
        return "jidlo", FOOD[amenity]
    if amenity == "toilets":
        if t.get("access") in NOT_PUBLIC:
            return None
        fee = t.get("fee")
        return "wc", "Toaleta, placená" if fee == "yes" else "Toaleta, zdarma" if fee == "no" else "Toaleta"
    if amenity == "post_office":
        if re.search("balíkovna", f"{t.get('name', '')} {t.get('brand', '')}", re.I):
            return "posta", "Balíkovna"
        who = t.get("operator") or t.get("brand") or ""
        return "posta", "Pobočka České pošty" if re.search("česká pošta", who, re.I) else "Pošta"
    if amenity == "bicycle_parking":
        if t.get("access") in NO_ENTRY:
            return None
        if t.get("bicycle_parking") == "lockers":
            return "stojan", "Boxy na kola"
        if t.get("covered") == "yes" or t.get("bicycle_parking") in COVERED_RACK:
            return "stojan", "Kryté stání pro kola"
        return "stojan", "Stojan na kola"
    if amenity == "recycling":
        if t.get("recycling_type") == "centre":
            return "dvur", "Sběrný dvůr"
        return "kontejner", "Kontejnery na tříděný odpad"
    if not t.get("name"):
        return None
    historic = t.get("historic")
    if historic and not (historic == "memorial" and t.get("memorial") in SMALL_MEMORIAL):
        return "pamatky", SIGHT.get(historic, "Památka")
    if t.get("tourism") == "museum":
        return "pamatky", "Muzeum"
    if t.get("tourism") == "attraction":
        return "pamatky", "Zajímavé místo"
    if amenity == "place_of_worship":
        return "pamatky", "Kaple" if t.get("building") == "chapel" else "Kostel"
    return None


# --- Průvodce městem: places worth a visit, by the guide's five kinds ---------------------------

GUIDE = ("pamatky", "kultura", "priroda", "jidlo", "ubytovani")
GUIDE_SIGHTS = {"viewpoint", "artwork"}   # tourism=*: a sight besides museums and attractions
GUIDE_CULTURE = {"amenity": {"theatre", "cinema", "arts_centre", "music_venue", "planetarium", "library",
                             "exhibition_centre", "concert_hall"},
                 "tourism": {"gallery"}}
GUIDE_NATURE = {"leisure": {"park", "garden", "nature_reserve", "sports_centre", "stadium", "swimming_pool",
                            "water_park", "ice_rink", "golf_course", "horse_riding", "miniature_golf", "fitness_centre",
                            "climbing", "beach_resort"},
                "tourism": {"zoo", "picnic_site"}}
GUIDE_FOOD = {"restaurant", "cafe", "pub", "bar", "biergarten", "ice_cream"}   # no fast food: no outing
GUIDE_STAY = {"hotel", "guest_house", "hostel", "motel", "apartment", "chalet", "camp_site"}


def guide_of(t: dict, kind: str) -> str | None:
    """The kind of Průvodce městem a named place is (GUIDE), or None when it is no place to visit:
    sights as „Co je v okolí“ has them, plus viewpoints and artworks; culture; parks, gardens and
    sports grounds open to the public; restaurants, cafés and pubs, not fast food; where to stay."""
    if not t.get("name") or t.get("access") in NOT_PUBLIC:
        return None
    amenity, tourism, leisure = t.get("amenity"), t.get("tourism"), t.get("leisure")
    if tourism in GUIDE_STAY:
        return "ubytovani"
    if kind == "pamatky" or tourism in GUIDE_SIGHTS:
        return "pamatky"
    if amenity in GUIDE_CULTURE["amenity"] or tourism in GUIDE_CULTURE["tourism"]:
        return "kultura"
    if leisure in GUIDE_NATURE["leisure"] or tourism in GUIDE_NATURE["tourism"]:
        return "priroda"
    if kind == "jidlo" and amenity in GUIDE_FOOD:
        return "jidlo"
    return None


def name_of(t: dict, kind: str, what: str) -> str | None:
    """The name a person sees. „Co je v okolí“: its own, else brand (an ATM also its operator),
    else what it is („Veřejné WC“). A rack, container or dvůr: its own name or None."""
    if kind == "misto":
        return (t.get("name") or t.get("brand") or "").strip() or None
    if kind in ("stojan", "kontejner", "dvur", "vykupna"):
        return (t.get("name") or "").strip() or None
    own = t.get("name") or t.get("brand") or (t.get("operator") if kind == "bankomat" else None)
    if own:
        return own.strip()
    return "Veřejné WC" if kind == "wc" else what


def address_of(t: dict) -> str | None:
    """Street (or place) and house number as OSM writes them, or None without a street."""
    street = t.get("addr:street") or t.get("addr:place")
    number = t.get("addr:housenumber") or t.get("addr:conscriptionnumber") or t.get("addr:streetnumber")
    if not street:
        return None
    return f"{street} {number}" if number else street


PHONE_KEYS = ("phone", "contact:phone", "contact:mobile", "mobile")
WEB_KEYS = ("website", "contact:website", "url")
SOCIAL_KEYS = ("contact:facebook", "facebook", "contact:instagram")
EMAIL_KEYS = ("email", "contact:email")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _first(t: dict, keys: tuple[str, ...]) -> str | None:
    """The first of a value's alternatives (OSM separates them by „;“) under the first key that has one."""
    for k in keys:
        for v in (t.get(k) or "").split(";"):
            if v.strip():
                return v.strip()
    return None


def phone_of(t: dict) -> str | None:
    """The first phone number as „+420 466 123 456“ (a Czech one of nine digits gets +420), any
    other international number as OSM has it, None when there is none or it is no number."""
    raw = _first(t, PHONE_KEYS)
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.split(",")[0])
    if raw.lstrip().startswith("00"):
        digits = digits[2:]
    elif not raw.lstrip().startswith("+") and len(digits) == 9:
        digits = "420" + digits
    if digits.startswith("420") and len(digits) == 12:
        return f"+420 {digits[3:6]} {digits[6:9]} {digits[9:]}"
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def web_of(t: dict) -> str | None:
    """The place's own web, else its Facebook or Instagram page, as a link with a scheme."""
    raw = _first(t, WEB_KEYS)
    if not raw:
        social = next(((k, v) for k in SOCIAL_KEYS if (v := _first(t, (k,)))), None)
        if not social:
            return None
        k, raw = social
        if not re.match(r"(?i)^(https?://|www\.|[a-z0-9-]+\.[a-z]{2,}/)", raw):
            raw = ("https://www.instagram.com/" if "instagram" in k else "https://www.facebook.com/") + raw.lstrip("@")
    if " " in raw or "." not in raw:
        return None
    return raw if re.match(r"(?i)^https?://", raw) else "https://" + raw.removeprefix("//")


def email_of(t: dict) -> str | None:
    e = _first(t, EMAIL_KEYS)
    return e.removeprefix("mailto:") if e and EMAIL.match(e.removeprefix("mailto:")) else None


def contact_of(t: dict) -> dict:
    """{phone, web, email} of the ones OSM has (docs/mista.md: a missing one is no field)."""
    c = {"phone": phone_of(t), "web": web_of(t), "email": email_of(t)}
    return {k: v for k, v in c.items() if v}


def capacity_of(t: dict) -> int | None:
    """OSM capacity as a whole number, None when absent or not a plain number („cca 10“)."""
    c = (t.get("capacity") or "").strip()
    return int(c) if c.isdigit() else None


def places_of(elements: list[dict]) -> list[dict]:
    """The places of an Overpass answer, one per OSM object, sorted by kind and id so that a
    day's file diffs. Fields as the export's, without `obvody` (petka.mista.where adds them).
    A container that takes none of the waste kinds is left out; a dvůr is kept. A `misto` that
    is another place of the same name nearby is left out (`other.once`)."""
    out = []
    for e in elements:
        t = e.get("tags") or {}
        c = classify(t)
        if not c and (what := other.classify(t)):
            c = ("misto", what)
        lat = e.get("lat", (e.get("center") or {}).get("lat"))
        lon = e.get("lon", (e.get("center") or {}).get("lon"))
        if not c or lat is None or lon is None:
            continue
        kind, what = c
        p = {"id": f"{e['type'][0]}{e['id']}", "kind": kind, "name": name_of(t, kind, what), "what": what,
             "address": address_of(t), "at": [round(lon, 5), round(lat, 5)],
             "hours": (t.get("opening_hours") or "").strip() or None, **contact_of(t)}
        if kind in ("kontejner", "dvur"):
            p["odpad"] = waste(t)
            if kind == "kontejner" and not p["odpad"]:
                continue
        if kind == "stojan":
            p["capacity"] = capacity_of(t)
        if kind == "misto" and not p["name"]:
            continue
        if guide := guide_of(t, kind):
            p["pruvodce"] = guide
        out.append(p)
    return other.once(out)


NEAR_YARD = 200     # m: an OSM recycling centre this close to a city yard is that yard
OSM_DAYS = {"po": "Mo", "út": "Tu", "st": "We", "čt": "Th", "pá": "Fr", "so": "Sa", "ne": "Su"}


def _m(a: list, b: list) -> float:
    from math import cos, hypot, radians
    return hypot((a[0] - b[0]) * 111320 * cos(radians(b[1])), (a[1] - b[1]) * 110540)


def opening_hours(hours: list[dict]) -> str:
    """SmP's hours ([{days, from, to}]) in OSM's opening_hours syntax: „Mo,Tu 06:30-15:00; We …“."""
    t = lambda s: s.zfill(5)
    return "; ".join(f"{','.join(OSM_DAYS[d] for d in h['days'])} {t(h['from'])}-{t(h['to'])}" for h in hours)


def split_yards(places: list[dict], city: list[dict]) -> list[dict]:
    """OSM tags every recycling centre alike, the town's separační dvory and private buyers of
    scrap (Kovošrot, JARÝ) too. A centre within NEAR_YARD m of a city yard (SmP's list,
    petka.odpady: {key, name, address, point, hours}) stays `dvur`, named and timed as SmP has
    it; any other becomes `vykupna`. A city yard OSM lacks (Dražkovice is mapped as a transfer
    station) is added from SmP's list, so `dvur` is always the town's yards."""
    used, out = set(), []
    for p in places:
        if p["kind"] != "dvur":
            out.append(p)
            continue
        near = [c for c in city if c.get("point") and c["key"] not in used and _m(p["at"], c["point"]) <= NEAR_YARD]
        if near:
            c = min(near, key=lambda c: _m(p["at"], c["point"]))
            used.add(c["key"])
            out.append({**p, "name": f"Sběrný dvůr {c['name']}", "what": "Sběrný dvůr",
                        "address": p["address"] or c["address"] or None, "hours": opening_hours(c["hours"])})
        else:
            out.append({**p, "kind": "vykupna", "what": "Výkupna, recyklační centrum"})
    for c in city:
        if c["key"] not in used and c.get("point"):
            out.append({"id": c["key"], "kind": "dvur", "name": f"Sběrný dvůr {c['name']}", "what": "Sběrný dvůr",
                        "address": c["address"] or None, "at": [round(c["point"][0], 5), round(c["point"][1], 5)],
                        "hours": opening_hours(c["hours"]), "odpad": []})
    return sorted(out, key=lambda p: (p["kind"], p["id"]))


def counts(places: list[dict]) -> dict[str, int]:
    """{kind: places} for every kind (0 for a missing one)."""
    out = dict.fromkeys(KINDS, 0)
    for p in places:
        out[p["kind"]] = out.get(p["kind"], 0) + 1
    return out


class OverpassError(RuntimeError):
    pass


def fetch(client, url: str = OVERPASS, sleep=time.sleep) -> dict:
    """The Overpass answer to QUERY as JSON; one retry after RETRY_AFTER s on 429/502/504. An
    answer with a runtime error in its `remark` (a partial answer) raises OverpassError."""
    for attempt in (1, 2):
        r = client.post(url, data={"data": QUERY}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        if r.status_code in RETRY_ON and attempt == 1:
            sleep(RETRY_AFTER)
            continue
        if r.status_code != 200:
            raise OverpassError(f"Overpass: HTTP {r.status_code}")
        data = r.json()
        if "error" in (data.get("remark") or "").lower():
            raise OverpassError(f"Overpass: {data['remark'][:200]}")
        return data
    raise AssertionError("unreachable")
