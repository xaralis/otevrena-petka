"""The kind `misto`: every other named place of the town a person may look for by its name – a
firm, an office, a doctor, a school, a shop that sells no food, a sports ground, a named
building or works – so that the app's search finds it, not only the places of „Co je v okolí“.

The app does not draw these on its map; they are only searched. Each says what it is in Czech
(`what`), from the first tag of PRIORITY that has a value in WHAT, else the key's general word
(KEY_WORD). Pure functions; petka.mista.osm asks for them in its one Overpass query.
"""

import math
import re
import unicodedata

# The keys that make a named object a place, in the order their value says best what it is: a
# shop inside a named building is a shop, a doctor's office an ordinace, not an office.
PRIORITY = ("healthcare", "amenity", "shop", "craft", "office", "tourism", "leisure", "club",
            "emergency", "government", "company", "man_made", "landuse", "natural", "building", "place")

# Values that are no place to go to, even with a name: street furniture, parts of something,
# private garages. An object whose only place-tag is one of these is left out.
NOT_A_PLACE = {
    "amenity": {"bench", "waste_basket", "waste_disposal", "parking_space", "parking_entrance", "grit_bin",
                "hunting_stand", "vending_machine", "telephone", "clock", "drinking_water", "shelter",
                "bicycle_parking", "recycling", "toilets", "atm", "post_box", "loading_dock", "letter_box",
                "photo_booth", "bbq", "lounger", "table", "watering_place", "water_point", "fountain",
                "motorcycle_parking", "smoking_area", "dog_toilet", "give_box", "public_bookcase"},
    "leisure": {"picnic_table", "firepit", "bleachers", "slipway", "swimming_area", "outdoor_seating",
                "track", "bandstand"},
    "man_made": {"pipeline", "mast", "tower", "chimney", "antenna", "survey_point", "cross", "flagpole",
                 "street_cabinet", "manhole", "pole", "embankment", "cutline", "bridge", "pier", "dyke",
                 "water_tap", "monitoring_station", "surveillance", "utility_pole", "power_pole"},
    "building": {"garage", "garages", "shed", "roof", "carport", "hut", "cabin", "barn", "greenhouse",
                 "construction", "ruins", "transformer_tower", "bunker", "service", "toilets", "kiosk",
                 "house", "detached", "semidetached_house", "bungalow", "terrace", "farm_auxiliary"},
    "landuse": None,      # only those in LANDUSE_PLACES
    "tourism": {"information", "picnic_site", "camp_pitch", "yes"},
}
# Parts of the town a person names as a place to go: „Polabiny“, „Dukla“, „Na Spravedlnosti“.
PLACE_PLACES = {"borough", "suburb", "quarter", "neighbourhood", "locality", "village", "hamlet", "isolated_dwelling", "square", "farm"}
NATURAL_PLACES = {"wood", "water", "beach", "peak", "spring", "tree", "wetland", "heath", "grassland"}
LANDUSE_PLACES = {"forest", "recreation_ground", "meadow", "industrial", "commercial", "retail", "military", "railway", "cemetery", "allotments",
                  "religious", "education", "institutional", "depot", "garages", "quarry"}

# What a place is, in Czech, by key and value. A value not here takes KEY_WORD of its key.
WHAT = {
    "healthcare": {
        "doctor": "Lékař", "dentist": "Zubař", "hospital": "Nemocnice", "clinic": "Poliklinika",
        "pharmacy": "Lékárna", "physiotherapist": "Fyzioterapie", "optometrist": "Optometrista",
        "laboratory": "Laboratoř", "psychotherapist": "Psychoterapie", "rehabilitation": "Rehabilitace",
        "centre": "Zdravotní středisko", "podiatrist": "Podolog", "speech_therapist": "Logoped",
        "nurse": "Zdravotní sestra", "alternative": "Alternativní medicína", "blood_donation": "Odběr krve",
        "audiologist": "Audiolog", "counselling": "Poradna", "sample_collection": "Odběrové místo",
        "dialysis": "Dialýza", "birthing_centre": "Porodnice", "hospice": "Hospic",
    },
    "amenity": {
        "doctors": "Ordinace", "dentist": "Zubař", "hospital": "Nemocnice", "clinic": "Poliklinika",
        "veterinary": "Veterinář", "nursing_home": "Domov seniorů", "social_facility": "Sociální služby",
        "school": "Škola", "kindergarten": "Mateřská škola", "college": "Vyšší odborná škola",
        "university": "Vysoká škola", "library": "Knihovna", "language_school": "Jazyková škola",
        "music_school": "Hudební škola", "driving_school": "Autoškola", "dancing_school": "Taneční škola",
        "childcare": "Péče o děti", "prep_school": "Doučování", "training": "Vzdělávání",
        "townhall": "Úřad", "courthouse": "Soud", "police": "Policie", "fire_station": "Hasiči",
        "post_depot": "Depo pošty", "prison": "Věznice", "embassy": "Konzulát",
        "bank": "Banka", "bureau_de_change": "Směnárna", "money_transfer": "Převod peněz",
        "fuel": "Čerpací stanice", "charging_station": "Nabíjecí stanice", "car_wash": "Myčka",
        "car_rental": "Půjčovna aut", "car_sharing": "Sdílená auta", "bicycle_rental": "Půjčovna kol",
        "parking": "Parkoviště", "taxi": "Taxi", "bus_station": "Autobusové nádraží", "ferry_terminal": "Přívoz",
        "vehicle_inspection": "Stanice technické kontroly",
        "theatre": "Divadlo", "cinema": "Kino", "arts_centre": "Kulturní centrum", "community_centre": "Komunitní centrum",
        "social_centre": "Klubovna", "events_venue": "Sál", "conference_centre": "Konferenční centrum",
        "nightclub": "Klub", "casino": "Kasino", "gambling": "Herna", "studio": "Studio",
        "exhibition_centre": "Výstaviště", "planetarium": "Hvězdárna", "music_venue": "Hudební klub",
        "place_of_worship": "Kostel", "monastery": "Klášter", "grave_yard": "Hřbitov", "funeral_hall": "Smuteční síň",
        "crematorium": "Krematorium", "marketplace": "Tržnice", "internet_cafe": "Internetová kavárna",
        "coworking_space": "Coworking", "animal_shelter": "Útulek", "animal_boarding": "Hotel pro zvířata",
        "restaurant": "Restaurace", "cafe": "Kavárna", "fast_food": "Rychlé občerstvení", "pub": "Hospoda",
        "bar": "Bar", "ice_cream": "Zmrzlina", "food_court": "Občerstvení", "canteen": "Jídelna",
        "pharmacy": "Lékárna", "post_office": "Pošta", "public_bath": "Lázně", "sauna": "Sauna",
        "shower": "Sprchy", "boat_rental": "Půjčovna lodí", "kick-scooter_rental": "Půjčovna koloběžek",
        "dojo": "Dojo", "ranger_station": "Stanice", "lavoir": "Prádelna",
        "parcel_locker": "Výdejní box", "bicycle_repair_station": "Servisní stojan na kola", "hospice": "Hospic",
        "baby_hatch": "Babybox", "refugee_site": "Ubytovna", "nursery": "Jesle",
    },
    "shop": {
        "clothes": "Oblečení", "shoes": "Obuv", "hairdresser": "Kadeřnictví", "beauty": "Kosmetika",
        "cosmetics": "Drogerie a kosmetika", "chemist": "Drogerie", "car": "Autosalon", "car_repair": "Autoservis",
        "car_parts": "Autodíly", "tyres": "Pneuservis", "motorcycle": "Motocykly", "bicycle": "Cykloprodejna",
        "hardware": "Železářství", "doityourself": "Hobbymarket", "electronics": "Elektro", "mobile_phone": "Mobilní telefony",
        "computer": "Počítače", "furniture": "Nábytek", "florist": "Květinářství", "garden_centre": "Zahradnictví",
        "books": "Knihkupectví", "stationery": "Papírnictví", "gift": "Dárky", "jewelry": "Klenotnictví",
        "optician": "Optika", "pet": "Chovatelské potřeby", "sports": "Sportovní potřeby", "toys": "Hračky",
        "alcohol": "Alkohol", "beverages": "Nápoje", "wine": "Vinotéka", "tobacco": "Trafika", "kiosk": "Trafika",
        "newsagent": "Trafika", "department_store": "Obchodní dům", "mall": "Obchodní centrum", "variety_store": "Levné zboží",
        "second_hand": "Second hand", "charity": "Charitativní obchod", "travel_agency": "Cestovní kancelář",
        "funeral_directors": "Pohřební služba", "laundry": "Prádelna", "dry_cleaning": "Čistírna", "tailor": "Krejčovství",
        "massage": "Masáže", "tattoo": "Tetování", "nails": "Nehtové studio", "copyshop": "Kopírovací centrum",
        "photo": "Fotografie", "locksmith": "Zámečnictví", "kitchen": "Kuchyně", "bathroom_furnishing": "Koupelny",
        "interior_decoration": "Bytové doplňky", "houseware": "Domácí potřeby", "appliance": "Spotřebiče",
        "paint": "Barvy a laky", "building_materials": "Stavebniny", "trade": "Velkoobchod", "wholesale": "Velkoobchod",
        "fabric": "Látky", "craft": "Hobby potřeby", "music": "Hudebniny", "musical_instrument": "Hudební nástroje",
        "pawnbroker": "Zastavárna", "money_lender": "Půjčky", "lottery": "Loterie", "bookmaker": "Sázková kancelář",
        "medical_supply": "Zdravotnické potřeby", "hearing_aids": "Naslouchadla", "outdoor": "Outdoor",
        "fishing": "Rybářské potřeby", "hunting": "Myslivecké potřeby", "weapons": "Zbraně", "baby_goods": "Kojenecké potřeby",
        "bag": "Kabelky", "boutique": "Butik", "fashion_accessories": "Módní doplňky", "watches": "Hodinářství",
        "perfumery": "Parfumerie", "herbalist": "Bylinky", "e-cigarette": "Elektronické cigarety", "erotic": "Erotické zboží",
        "electrical": "Elektroinstalace", "lighting": "Svítidla", "energy": "Energie", "security": "Zabezpečení",
        "agrarian": "Zemědělské potřeby", "swimming_pool": "Bazény", "frame": "Rámování", "video_games": "Videohry",
        "ticket": "Předprodej", "storage_rental": "Pronájem skladů", "rental": "Půjčovna", "repair": "Opravna",
        "shoe_repair": "Opravna obuvi", "pastry": "Cukrárna", "confectionery": "Cukrovinky", "coffee": "Káva",
        "tea": "Čaj", "seafood": "Ryby", "cheese": "Sýry", "chocolate": "Čokoláda", "spices": "Koření",
        "dairy": "Mléčné výrobky", "water": "Voda", "gas": "Plyn", "fuel": "Pohonné hmoty", "vacant": None,
        "supermarket": "Supermarket", "convenience": "Večerka", "bakery": "Pekařství", "butcher": "Řeznictví",
    },
    "craft": {
        "electrician": "Elektrikář", "plumber": "Instalatér", "carpenter": "Truhlářství", "joiner": "Truhlářství",
        "metal_construction": "Zámečnictví", "locksmith": "Zámečnictví", "brewery": "Pivovar", "winery": "Vinařství",
        "printer": "Tiskárna", "photographer": "Fotograf", "tailor": "Krejčovství", "shoemaker": "Obuvník",
        "glaziery": "Sklenářství", "painter": "Malíř", "roofer": "Pokrývač", "stonemason": "Kamenictví",
        "upholsterer": "Čalounictví", "watchmaker": "Hodinář", "jeweller": "Zlatnictví", "beekeeper": "Včelař",
        "confectionery": "Cukrárna", "caterer": "Catering", "hvac": "Vzduchotechnika", "key_cutter": "Klíče",
        "builder": "Stavební firma", "gardener": "Zahradník", "blacksmith": "Kovářství", "sawmill": "Pila",
        "tiler": "Obkladač", "floorer": "Podlahářství", "window_construction": "Okna", "signmaker": "Reklama",
        "dressmaker": "Krejčovství", "electronics_repair": "Opravna elektroniky", "distillery": "Lihovar",
        "bakery": "Pekárna", "optician": "Optika", "dental_technician": "Zubní laboratoř",
    },
    "office": {
        "company": "Firma", "government": "Úřad", "administrative": "Úřad", "lawyer": "Advokát",
        "notary": "Notář", "accountant": "Účetnictví", "tax_advisor": "Daňový poradce", "insurance": "Pojišťovna",
        "estate_agent": "Realitní kancelář", "it": "IT firma", "architect": "Architekt", "engineer": "Projekce",
        "financial": "Finanční služby", "financial_advisor": "Finanční poradce", "employment_agency": "Pracovní agentura",
        "ngo": "Nezisková organizace", "association": "Spolek", "foundation": "Nadace", "charity": "Charita",
        "educational_institution": "Vzdělávací instituce", "research": "Výzkum", "telecommunication": "Telekomunikace",
        "energy_supplier": "Dodavatel energie", "water_utility": "Vodárna", "political_party": "Politická strana",
        "religion": "Církev", "travel_agent": "Cestovní kancelář", "advertising_agency": "Reklamní agentura",
        "logistics": "Logistika", "newspaper": "Redakce", "publisher": "Vydavatelství", "consulting": "Poradenství",
        "construction_company": "Stavební firma", "property_management": "Správa nemovitostí",
        "union": "Odbory", "coworking": "Coworking", "diplomatic": "Konzulát", "quango": "Úřad", "courier": "Kurýr",
        "security": "Bezpečnostní agentura", "moving_company": "Stěhování", "therapist": "Terapie",
        "healthcare": "Zdravotnictví", "graphic_design": "Grafické studio", "surveyor": "Geodet", "yes": "Kancelář",
    },
    "tourism": {
        "hotel": "Hotel", "guest_house": "Penzion", "hostel": "Hostel", "motel": "Motel", "apartment": "Apartmány",
        "camp_site": "Kemp", "caravan_site": "Autokemp", "chalet": "Chata", "museum": "Muzeum", "gallery": "Galerie",
        "attraction": "Zajímavé místo", "artwork": "Umělecké dílo", "viewpoint": "Vyhlídka", "zoo": "Zoo", "theme_park": "Zábavní park", "aquarium": "Akvárium",
    },
    "leisure": {
        "sports_centre": "Sportovní centrum", "stadium": "Stadion", "pitch": "Hřiště", "playground": "Dětské hřiště",
        "park": "Park", "garden": "Zahrada", "swimming_pool": "Bazén", "water_park": "Aquapark", "fitness_centre": "Fitness",
        "fitness_station": "Venkovní posilovna", "ice_rink": "Zimní stadion", "golf_course": "Golf", "miniature_golf": "Minigolf",
        "horse_riding": "Jezdecký areál", "marina": "Přístaviště", "dog_park": "Psí louka", "nature_reserve": "Přírodní rezervace",
        "sports_hall": "Sportovní hala", "dance": "Taneční sál", "bowling_alley": "Bowling", "escape_game": "Úniková hra",
        "amusement_arcade": "Herna", "sauna": "Sauna", "fishing": "Rybník", "common": "Louka", "recreation_ground": "Rekreační areál",
        "shooting_ground": "Střelnice", "trampoline_park": "Trampolíny", "hackerspace": "Hackerspace", "summer_camp": "Tábor",
        "adult_gaming_centre": "Herna", "resort": "Rekreační středisko", "beach_resort": "Koupaliště", "bathing_place": "Koupaliště",
    },
    "natural": {"wood": "Les", "water": "Vodní plocha", "beach": "Pláž", "peak": "Vrch", "spring": "Pramen",
                "tree": "Památný strom", "wetland": "Mokřad", "heath": "Vřesoviště", "grassland": "Louka"},
    "place": {"borough": "Městský obvod", "suburb": "Část města", "quarter": "Čtvrť", "neighbourhood": "Čtvrť", "locality": "Místní název",
              "village": "Obec", "hamlet": "Osada", "isolated_dwelling": "Samota", "square": "Náměstí", "farm": "Statek"},
    "emergency": {"ambulance_station": "Záchranná služba", "mountain_rescue": "Záchranná služba", "water_rescue": "Vodní záchranná služba"},
    "man_made": {"works": "Závod", "wastewater_plant": "Čistírna odpadních vod", "water_works": "Úpravna vody",
                 "observatory": "Hvězdárna", "lighthouse": "Maják", "windmill": "Větrný mlýn", "watermill": "Vodní mlýn",
                 "silo": "Sila", "storage_tank": "Nádrž", "water_tower": "Vodárna", "gasometer": "Plynojem"},
    "landuse": {"industrial": "Průmyslový areál", "commercial": "Areál", "retail": "Obchodní zóna", "military": "Vojenský areál",
                "railway": "Železniční areál", "cemetery": "Hřbitov", "allotments": "Zahrádkářská osada",
                "religious": "Církevní areál", "education": "Školní areál", "institutional": "Areál", "depot": "Depo",
                "garages": "Garáže", "quarry": "Lom", "forest": "Les", "recreation_ground": "Rekreační areál", "meadow": "Louka"},
    "building": {"industrial": "Průmyslová budova", "warehouse": "Sklad", "commercial": "Komerční budova", "office": "Kancelářská budova",
                 "retail": "Obchod", "school": "Škola", "kindergarten": "Mateřská škola", "university": "Vysoká škola",
                 "college": "Škola", "hospital": "Nemocnice", "church": "Kostel", "chapel": "Kaple", "civic": "Veřejná budova",
                 "public": "Veřejná budova", "government": "Úřad", "train_station": "Nádraží", "transportation": "Dopravní budova",
                 "hotel": "Hotel", "sports_hall": "Sportovní hala", "stadium": "Stadion", "dormitory": "Kolej",
                 "apartments": "Bytový dům", "residential": "Obytná budova", "fire_station": "Hasiči", "museum": "Muzeum",
                 "factory": "Továrna", "manufacture": "Výroba", "supermarket": "Supermarket", "yes": "Budova"},
}
KEY_WORD = {"healthcare": "Zdravotnictví", "amenity": "Místo", "shop": "Obchod", "craft": "Řemeslo", "office": "Firma",
            "tourism": "Turistické místo", "leisure": "Sport a volný čas", "club": "Klub",
            "emergency": "Záchranná služba", "government": "Úřad", "company": "Firma", "man_made": "Areál",
            "landuse": "Areál", "natural": "Příroda", "building": "Budova", "place": "Místo"}

def _counts(key: str, value: str | None) -> bool:
    """Whether `key=value` makes a named object a place."""
    if not value or value == "no":
        return False
    if key == "landuse":
        return value in LANDUSE_PLACES
    if key == "place":
        return value in PLACE_PLACES
    if key == "natural":
        return value in NATURAL_PLACES
    skip = NOT_A_PLACE.get(key)
    return not (skip and value in skip)


def classify(t: dict) -> str | None:
    """What a named object other than the places of „Co je v okolí“ is, in Czech, or None when it
    is no place a person looks for (street furniture, a private garage, a house)."""
    if not (t.get("name") or t.get("brand")):
        return None
    for key in PRIORITY:
        value = t.get(key)
        if not _counts(key, value):
            continue
        what = WHAT.get(key, {}).get(value, KEY_WORD[key])
        if what is None:        # e.g. shop=vacant: nothing there now
            return None
        return what
    return None


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


SAME_PLACE_M = 150   # m: a named object this near another place of the same name is that place


def _m(a: list, b: list) -> float:
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(math.radians(b[1])), (a[1] - b[1]) * 110540)


def once(places: list[dict]) -> list[dict]:
    """The places with each `misto` left out that names the same thing as another `misto` within
    SAME_PLACE_M m: OSM often maps a firm as its building and as a point inside it. Of the two,
    the one with the more telling `what` (not a bare building or area) and then the lower id
    stays. A `misto` of the same name as a place of „Co je v okolí“ stays: a firm's building
    holding its own pharmacy is two things a person looks for."""
    generic = {"Budova", "Areál", "Průmyslový areál", "Komerční budova", "Obytná budova", "Bytový dům"}
    order = sorted(places, key=lambda p: (p["kind"] != "misto", p["what"] in generic, p["id"]))
    by_name: dict[str, list[list]] = {}
    out = []
    for p in order:
        key = _fold(p["name"] or "") if p["kind"] == "misto" else ""
        if key and any(_m(p["at"], at) <= SAME_PLACE_M for at in by_name.get(key, [])):
            continue
        if key:
            by_name.setdefault(key, []).append(p["at"])
        out.append(p)
    return sorted(out, key=lambda p: (p["kind"], p["id"]))
