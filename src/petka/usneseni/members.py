"""Members of ZMO Pardubice V per term and matching of names as written in the minutes.

The registry (config/members.yaml) comes from the election results: elected members and
substitutes of every list that won a seat. Minutes write names many ways – "Ing. Filip
Vařecha", "Ing. Vařecha", "Ing. F. Vařecha", "J. Rejda, DiS." – so matching works on the
surname, narrowed by first name or initial, and only among people at that meeting.
"""

import datetime as dt
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from .text import fold, slug, strip_titles

CONFIG = Path(__file__).resolve().parents[3] / "config" / "usneseni"


@dataclass(frozen=True)
class Member:
    id: str
    first: str
    last: str
    before: str = ""
    after: str = ""

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"

    @property
    def full_name(self) -> str:
        n = f"{self.before} {self.first} {self.last}".strip()
        return f"{n}, {self.after}" if self.after else n


@dataclass
class Term:
    id: str
    start: dt.date
    seats: int
    lists: dict[str, str] = field(default_factory=dict)       # member id -> list name
    elected: set[str] = field(default_factory=set)


@cache
def registry() -> tuple[dict[str, Member], list[Term]]:
    data = yaml.safe_load((CONFIG / "members.yaml").read_text())
    members: dict[str, Member] = {}
    terms = []
    for t in data["terms"]:
        term = Term(id=t["id"], start=dt.date.fromisoformat(t["election"]), seats=t["seats"])
        for c in t["candidates"]:
            mid = slug(f"{c['first']} {c['last']}")
            m = Member(mid, c["first"], c["last"], c.get("before", ""), c.get("after", ""))
            members[mid] = m  # latest term wins for titles
            term.lists[mid] = c["list"]
            if c["elected"]:
                term.elected.add(mid)
        terms.append(term)
    terms.sort(key=lambda t: t.start)
    return members, terms


@cache
def aliases() -> dict[str, str]:
    p = CONFIG / "aliases.yaml"
    if not p.exists():
        return {}
    return {fold(k): v for k, v in (yaml.safe_load(p.read_text()) or {}).items()}


def term_for(d: dt.date) -> Term:
    _, terms = registry()
    current = [t for t in terms if t.start <= d]
    if not current:
        raise ValueError(f"no term for {d}")
    return current[-1]


def _edit1(a: str, b: str) -> bool:
    """At most one substitution/insertion/deletion (typos like 'Kutílek'/'Kutilek')."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def match(raw: str, pool: list[str]) -> str | None:
    """Member id for a name as written, looking only at member ids in `pool`."""
    members, _ = registry()
    al = aliases().get(fold(raw.strip()))
    if al:
        return al
    tokens = strip_titles(raw)
    if not tokens:
        return None
    last = fold(tokens[-1])
    given = [fold(t).rstrip(".") for t in tokens[:-1]]
    # compare the last word of the surname: volby.cz splits double names inconsistently
    # ("Anna Gudrun" + "Vavrečková" in 2018, "Anna" + "Gudrun Vavrečková" in 2022)
    known = [mid for mid in pool if mid in members]
    surname = {mid: fold(members[mid].last).split()[-1] for mid in known}
    cands = [mid for mid in known if surname[mid] == last]
    if not cands:
        cands = [mid for mid in known if len(last) > 4 and _edit1(surname[mid], last)]
    if len(cands) > 1 and given:
        g = given[0]
        cands = [mid for mid in cands
                 if fold(members[mid].first).startswith(g) or fold(members[mid].name).startswith(g)]
    return cands[0] if len(cands) == 1 else None


def resolve_attendee(raw: str, term: Term) -> str | None:
    """Match an attendance-list name against everyone on the term's winning lists."""
    return match(raw, list(term.lists))
