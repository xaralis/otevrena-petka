"""The header navigation: the portal's areas (level 1) and the pages in each (level 2).

Data, not template: base.html draws the two rows on wide screens and the full-screen menu on
phones from GROUPS. An item may name the section it stands for (`slug`); it is "připravujeme"
(soon) when that section is still planned, or when it says so itself (a section without a page
yet). Which item is current comes from the request path: the longest href it starts with.
"""

from dataclasses import dataclass, field

from .sections import BY_SLUG


@dataclass(frozen=True)
class Item:
    label: str
    href: str
    hint: str                   # the question under the label in the phone menu
    slug: str | None = None     # the section it stands for
    planned: bool = False       # no page yet even though the section has code

    @property
    def soon(self) -> bool:
        s = BY_SLUG.get(self.slug) if self.slug else None
        return self.planned or bool(s and s.status == "planned")


@dataclass(frozen=True)
class Group:
    label: str
    items: list[Item] = field(default_factory=list)

    @property
    def href(self) -> str:
        """Where the area's own link goes: its first page that exists."""
        return next((i.href for i in self.items if not i.soon), self.items[0].href)


GROUPS = [
    Group("Radnice", [
        Item("Úřední deska", "/uredni-deska", "Co úřad právě vyvěsil?", "uredni-deska"),
        Item("Usnesení", "/usneseni", "Co se rozhodlo a kdo jak hlasoval?", "usneseni"),
        Item("Zastupitelé", "/usneseni/clenove", "Kdo obvod vede a jak hlasuje?"),
    ]),
    Group("Finance", [
        Item("Rozpočet", "/rozpocet", "Kolik obvod utrácí a za co?", "rozpocet"),
        Item("Smlouvy", "/smlouvy", "Kdo pro obvod pracuje a za kolik?", "smlouvy"),
    ]),
    Group("Veřejný prostor", [
        Item("Blokové čištění ulic", "/blokove-cisteni", "Kdy proběhne čištění mojí ulice?", "blokove-cisteni"),
        Item("Uzavírky", "/uzavirky", "Kde se teď nedá projet?", "uzavirky"),
        Item("Závady", "/podnety", "Co lidé hlásí a jak se to řeší?", "podnety"),
    ]),
    Group("Zapojte se", [
        Item("Ankety", "/ankety", "Co si myslíte?", "ankety", planned=True),
    ]),
]
UTIL = Item("Data a API", "/data", "Stáhnout data, API a MCP pro AI asistenty")
SOON = {i.href.strip("/") for g in GROUPS for i in g.items if i.soon}   # served by the planned-section page


def _under(path: str, href: str) -> bool:
    return path == href or path.startswith(href.rstrip("/") + "/")


def current(path: str) -> tuple[Group | None, Item | None]:
    """The area and the page a path belongs to (None, None outside the areas: the home page,
    a street, the data catalog)."""
    best = None
    for g in GROUPS:
        for i in g.items:
            if _under(path, i.href) and (best is None or len(i.href) > len(best[1].href)):
                best = (g, i)
    return best or (None, None)


TEMPLATE_GLOBALS = {"NAV": GROUPS, "NAV_UTIL": UTIL, "nav_current": current}
