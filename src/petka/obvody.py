"""The registry of obvody the portal serves, and which one a request is for (ADR 0001).

One deployment serves every obvod; the obvod comes from the request's host. Today there is
only MO Pardubice V, and every unknown host falls back to it. Data are not split by obvod
yet (only the rozpočet has it, as `unit`, and the podněty, as `obvod`): the obvod's id is the
same string as that unit and as the id of the obvod's úřední deska board.
"""

from dataclasses import dataclass


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
