"""Czech words for the podněty page: plurals, months, durations and how to name a category in
a sentence. Pure."""

import datetime as dt

MONTH = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen",
         "listopad", "prosinec"]
MONTH_GEN = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října",
             "listopadu", "prosince"]
MONTH_IN = ["v lednu", "v únoru", "v březnu", "v dubnu", "v květnu", "v červnu", "v červenci", "v srpnu",
            "v září", "v říjnu", "v listopadu", "v prosinci"]
MONTH_ABBR = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"]

# How a sentence names the reports of a known category: (after "podněty", the full phrase after
# "Z 38 podnětů", the phone title after "Nejdéle čekají"). Others get a generic phrasing.
PHRASES = {
    "Pískoviště, hřiště, sportoviště": ("k hřištím", "k pískovištím, hřištím a sportovištím", "hřiště"),
    "Veřejná zeleň": ("k zeleni", "k veřejné zeleni", "podněty k zeleni"),
    "Odpadky, černá skládka": ("k odpadkům a skládkám", "k odpadkům a černým skládkám", "odpadky a skládky"),
    "Autovrak": ("k autovrakům", "k autovrakům", "autovraky"),
    "Chodník": ("k chodníkům", "k chodníkům", "chodníky"),
    "Silnice, cyklostezky": ("k silnicím", "k silnicím a cyklostezkám", "silnice"),
    "Lavičky, zábradlí": ("k lavičkám", "k lavičkám a zábradlí", "lavičky"),
    "Veřejné osvětlení": ("k osvětlení", "k veřejnému osvětlení", "lampy"),
    "Dopravní značení": ("k dopravnímu značení", "k dopravnímu značení", "dopravní značení"),
    "Kanalizace": ("ke kanalizaci", "ke kanalizaci", "kanalizace"),
}

# Categories the obvod does not handle: what happens to them instead (the table's note line)
FORWARDED_NOTE = {
    "Městská policie": "předávají se strážníkům, stav v Dej Tipu se nemění",
    "Zastávky MHD": "řeší dopravní podnik, stav v Dej Tipu se nemění",
}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 podnět, 2–4 podněty, 5+ podnětů (0 counts as many)."""
    return one if n == 1 else few if 2 <= n <= 4 else many


def podnetu(n: int) -> str:
    return f"{n} {plural(n, 'podnět', 'podněty', 'podnětů')}"


def phrase(category: str) -> tuple[str, str, str]:
    return PHRASES.get(category) or (f"v kategorii „{category}“", f"v kategorii „{category}“", f"„{category}“")


def dm(d: dt.date) -> str:
    return f"{d.day}. {d.month}."


def dmy(d: dt.date) -> str:
    return f"{d.day}. {d.month}. {d.year}"


def days(n: float) -> str:
    """'do 1 dne' under a day, else '1 den', '3 dny', '9 dní' (rounded)."""
    if n < 1:
        return "do 1 dne"
    k = max(1, round(n))
    return f"{k} {plural(k, 'den', 'dny', 'dní')}"


def hours(h: float) -> str:
    """The first response: '17 h' under 48 hours, else days ('3 dny')."""
    if h < 48:
        return f"{max(1, round(h))} h"
    k = round(h / 24)
    return f"{k} {plural(k, 'den', 'dny', 'dní')}"


# one word for a category in a short phone sentence ("Nejčastěji hřiště (30), jiné (15) …")
SHORT = {
    "Pískoviště, hřiště, sportoviště": "hřiště", "Veřejná zeleň": "zeleň", "Odpadky, černá skládka": "odpadky",
    "Silnice, cyklostezky": "silnice", "Lavičky, zábradlí": "lavičky", "Veřejné osvětlení": "osvětlení",
    "Dopravní značení": "značení", "Poděkování, pochvala": "poděkování",
}


def short(category: str) -> str:
    return SHORT.get(category, category[:1].lower() + category[1:])


def waits(n: int) -> str:
    """'1 čeká', '3 čekají', '30 čeká'."""
    return f"{n} {'čekají' if 2 <= n <= 4 else 'čeká'}"


ZE_DAYS = {3, 4, 7, 13, 14, 17, 23, 24, 27}     # třetího, čtrnáctého, sedmého … are said with "ze"


def from_date(d: dt.date) -> str:
    """'ze 14. 11. 2025', 'z 21. 11. 2025'."""
    return f"{'ze' if d.day in ZE_DAYS else 'z'} {dmy(d)}"


def join(items: list[str]) -> str:
    """'a', 'a a b', 'a, b a c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " a " + items[-1] if items else ""
