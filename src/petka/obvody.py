"""The obvody: the town's eight městské obvody, the ones the portal serves, which one a request
is for (ADR 0001), and the `?obvod=` filter of data sources (ADR 0002).

One deployment serves every obvod; the obvod comes from the request's host. Today it serves
only MO Pardubice V, and every unknown host falls back to it. The obvod's id is the same string
as the rozpočet's unit and the id of the obvod's úřední deska board.

Pages show the host's obvod. Data sources (API, exports) cover the whole town by default and
take `?obvod=mo1,mo5` (`ObvodParam`); every record they give carries its `obvody`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query


@dataclass(frozen=True)
class TownObvod:
    id: str                 # "mo1" … "mo8"
    name: str               # "Městský obvod Pardubice I"
    abbr: str               # "MO Pardubice I"
    momc: int               # RÚIAN code of the městský obvod


_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
_MOMC = (574716, 555126, 557064, 555096, 557072, 555100, 555118, 575020)    # RÚIAN (ČÚZK), obec 555134

# Every obvod of the town, served by the portal or not: what data sources filter by.
TOWN = [TownObvod(f"mo{i}", f"Městský obvod Pardubice {r}", f"MO Pardubice {r}", m)
        for i, (r, m) in enumerate(zip(_ROMAN, _MOMC, strict=True), 1)]
TOWN_BY_ID = {o.id: o for o in TOWN}


@dataclass(frozen=True)
class Obvod:
    id: str                 # "mo5": rozpočet unit, úřední deska board id
    name: str               # "Městský obvod Pardubice V"
    abbr: str               # "MO Pardubice V", how texts name it
    brand: str              # "Otevřená Pětka", the portal's name for this obvod
    hosts: tuple[str, ...]  # hosts that serve it
    gordic: str             # IČO-like code of the unit in the city's rozklikávací rozpočet (GORDIC)
    district_id: int        # district_id of its board in the city's úřední deska feed
    momc: int               # RÚIAN code of the městský obvod (Dej Tip calls it CS_MUNICODE)


MO5 = Obvod("mo5", "Městský obvod Pardubice V", "MO Pardubice V", "Otevřená Pětka",
            ("otevrenapetka.cz", "localhost", "127.0.0.1"), "05274046", 5, 557072)

OBVODY = [MO5]
BY_ID = {o.id: o for o in OBVODY}
DEFAULT = MO5
_BY_HOST = {h: o for o in OBVODY for h in o.hosts}


def from_host(host: str | None) -> Obvod:
    """The obvod a request is for, from its Host header (port and a leading www. ignored);
    an unknown host gets the default obvod."""
    h = (host or "").strip().lower().rsplit(":", 1)[0] if not (host or "").startswith("[") else ""
    h = h.removeprefix("www.")
    return _BY_HOST.get(h, DEFAULT)


# --- the filter of data sources (ADR 0002) ---------------------------------------------------

@dataclass(frozen=True)
class ObvodFilter:
    """Which obvody of the town a data source's answer covers: `ids` in the town's order, none
    = the whole town. A record matches when it lies in any of them."""
    ids: tuple[str, ...] = ()

    @classmethod
    def only(cls, *ids: str) -> "ObvodFilter":
        """Just these obvody (a page's own obvod); unknown ids raise ValueError."""
        return parse(",".join(ids))

    @property
    def whole_town(self) -> bool:
        return not self.ids

    def matches(self, obvody: Iterable[str]) -> bool:
        """Whether a record lying in `obvody` (ids) is in the answer; the whole town takes
        every record, even one we couldn't place in any obvod."""
        return self.whole_town or not set(self.ids).isdisjoint(obvody)

    def sql(self, column: str, min_share: float) -> tuple[str, list]:
        """A WHERE condition and its parameters for a jsonb column of shares {obvod id: share}:
        the record lies at least `min_share` in one of the obvody. `column` is code's, never
        the request's."""
        if self.whole_town:
            return "TRUE", []
        return (f"EXISTS (SELECT 1 FROM jsonb_each_text({column}) s(k, v) "
                "WHERE s.k = ANY(%s) AND s.v::float >= %s)"), [list(self.ids), min_share]


WHOLE_TOWN = ObvodFilter()


def parse(value: str | None) -> ObvodFilter:
    """`?obvod=` as given: ids separated by commas, spaces and case ignored; none = the whole
    town. Raises ValueError (a Czech message listing the valid ids) for an unknown id."""
    asked = {x.strip().lower() for x in (value or "").split(",") if x.strip()}
    unknown = sorted(asked - TOWN_BY_ID.keys())
    if unknown:
        raise ValueError(f"Neznámý obvod: {', '.join(unknown)}. Platné jsou {', '.join(TOWN_BY_ID)} "
                         "(Pardubice I–VIII), víc jich oddělte čárkou; bez parametru celé město.")
    return ObvodFilter(tuple(i for i in TOWN_BY_ID if i in asked))


def share_ids(shares: dict[str, float] | None, min_share: float) -> list[str]:
    """The obvody a record lies in, from its shares {obvod id: share}: sorted ids with at least
    `min_share`. What a record's `obvody` field carries."""
    return sorted(k for k, v in (shares or {}).items() if v >= min_share)


OBVOD_DOC = ("Jen záznamy z těchto obvodů města: id oddělená čárkou, např. `mo5` nebo `mo1,mo5` "
             "(mo1–mo8 = Pardubice I–VIII). Bez parametru celé město. Každý záznam má pole `obvody`.")


def obvod_filter(obvod: str | None = Query(None, description=OBVOD_DOC, examples=["mo5", "mo1,mo5"])) -> ObvodFilter:
    """FastAPI dependency: the `?obvod=` filter of a data source; an unknown id is a 422."""
    try:
        return parse(obvod)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


# A data source's endpoint declares the filter with `obvod: ObvodParam`.
ObvodParam = Annotated[ObvodFilter, Depends(obvod_filter)]
