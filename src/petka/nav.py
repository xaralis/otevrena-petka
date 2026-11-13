"""The header navigation: the portal's areas (level 1) and the pages in each (level 2).

Data, not template: base.html draws the two rows on wide screens and the full-screen menu on
phones from GROUPS. An item may name the section it stands for (`slug`); it is "připravujeme"
(soon) when that section is still planned, or when it says so itself (a section without a page
yet). Which item is current comes from the request path: the longest href it starts with.

The URLs follow the menu: /<area>/<page> (/radnice/usneseni). A section's page lives at its
item's href (Section.path); `was` is where the page used to be before the areas existed
(13. 11. 2026). Old URLs answer with a permanent redirect to the same subpath under the new
one (MOVED, applied by petka.web.app), feeds and calendars are served at both.
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
    was: str | None = None      # the page's URL before 13. 11. 2026 (redirected to href)

    @property
    def soon(self) -> bool:
        s = BY_SLUG.get(self.slug) if self.slug else None
        return self.planned or bool(s and s.status == "planned")


@dataclass(frozen=True)
class Group:
    label: str
    path: str                   # the area's own URL, a redirect to `href`
    items: list[Item] = field(default_factory=list)

    @property
    def href(self) -> str:
        """Where the area's own link goes: its first page that exists."""
        return next((i.href for i in self.items if not i.soon), self.items[0].href)


GROUPS = [
    Group("Radnice", "/radnice", [
        Item("Úřední deska", "/radnice/uredni-deska", "Co úřad právě vyvěsil?", "uredni-deska",
             was="/uredni-deska"),
        Item("Usnesení", "/radnice/usneseni", "Co se rozhodlo a kdo jak hlasoval?", "usneseni",
             was="/usneseni"),
        Item("Zastupitelé", "/radnice/zastupitele", "Kdo obvod vede a jak hlasuje?",
             was="/usneseni/clenove"),
    ]),
    Group("Finance", "/finance", [
        Item("Rozpočet", "/finance/rozpocet", "Kolik obvod utrácí a za co?", "rozpocet", was="/rozpocet"),
        Item("Smlouvy", "/finance/smlouvy", "Kdo pro obvod pracuje a za kolik?", "smlouvy", was="/smlouvy"),
    ]),
    Group("Veřejný prostor", "/verejny-prostor", [
        Item("Ulice", "/verejny-prostor/ulice", "Co se děje v mé ulici?", was="/ulice"),
        Item("Blokové čištění ulic", "/verejny-prostor/blokove-cisteni", "Kdy proběhne čištění mojí ulice?",
             "blokove-cisteni", was="/blokove-cisteni"),
        Item("Uzavírky", "/verejny-prostor/uzavirky", "Kde se teď nedá projet?", "uzavirky", was="/uzavirky"),
        Item("Podněty", "/verejny-prostor/podnety", "Co lidé hlásí a jak se to řeší?", "podnety", was="/podnety"),
    ]),
    Group("Zapojte se", "/zapojte-se", [
        Item("Ankety", "/zapojte-se/ankety", "Co si myslíte?", "ankety", planned=True, was="/ankety"),
    ]),
]
# pages that exist come first in every area, the "připravujeme" ones at its end (they move up
# by themselves once their section goes live)
for _g in GROUPS:
    _g.items.sort(key=lambda i: i.soon)

UTIL = Item("Data a API", "/data", "Stáhnout data, API a MCP pro AI asistenty")
SOON = {i.href for g in GROUPS for i in g.items if i.soon}   # served by the planned-section page
PATHS = {i.slug: i.href for g in GROUPS for i in g.items if i.slug}   # section slug -> its page

# old prefix -> new prefix, longest first: /usneseni/clenove goes to /radnice/zastupitele, not
# to /radnice/usneseni/clenove
MOVED = sorted([(i.was, i.href) for g in GROUPS for i in g.items if i.was]
               + [("/verejny-prostor/zavady", "/verejny-prostor/podnety")],    # „Závady“ until 13. 11. 2026
               key=lambda m: -len(m[0]))


def _under(path: str, href: str) -> bool:
    return path == href or path.startswith(href.rstrip("/") + "/")


def moved(path: str) -> str | None:
    """Where an old URL's path is now (the same subpath under the new prefix), None if it
    didn't move."""
    for old, new in MOVED:
        if _under(path, old):
            return new + path[len(old):]
    return None


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
