"""From parse output + PDF text to a meeting record: resolutions, votes, ballots, issues.

Everything here is deterministic. The rules that matter:

- A resolution passes because of its vote, never because it has a number. Some numbered
  "usnesení" were voted down (e.g. 18/2019 Z: pro 1). `passed` is computed from the count
  for against the quorum (majority of all members: ZMO 8 of 15, RMO 3 of 5); an explicit
  "bylo / nebylo přijato" in the text must agree, otherwise the meeting goes to review.
- Ballots per member are reconstructed: people present at that moment (attendance list
  plus arrivals/departures before the vote line) minus the names listed for the minority
  options all voted for the one option whose names are not listed. Every ballot says
  whether it was `named` in the minutes or `inferred`; when the counts don't add up the
  vote keeps only its totals (`tallies_only`) rather than guessing.
"""

import datetime as dt
import re
from dataclasses import asdict, dataclass, field

from . import members as reg
from .parse import counts_in_raw, normalize_number, number_lines, resolution_numbers_in_text
from .text import clean_block, fold, slug, ws

OPTIONS = ("pro", "proti", "zdrzel", "nehlasoval")
SEATS = {"zmo": 15, "rmo": 5}


@dataclass
class Issue:
    severity: str  # error | warn
    code: str
    message: str
    line: int | None = None


@dataclass
class Meeting:
    id: str
    body: str
    term: str
    number: int
    kind: str
    date: dt.date
    place: str | None
    source_url: str
    source_title: str
    attendance: dict            # present/excused/absent -> [member ids]
    attendance_raw: dict
    agenda_items: list = field(default_factory=list)
    resolutions: list = field(default_factory=list)
    votes: list = field(default_factory=list)
    members: dict = field(default_factory=dict)   # member id -> {name, list}
    issues: list = field(default_factory=list)
    model_notes: list = field(default_factory=list)

    @property
    def status(self) -> str:
        return "needs_review" if any(i.severity == "error" for i in self.issues) else "ok"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["status"] = self.status
        return d


def _agenda_key(no: str | None) -> str:
    return re.sub(r"[^0-9a-zivx]", "", fold(no or ""))


def build(doc: dict, text: str, parsed: dict, accepted_issues: frozenset[str] = frozenset()) -> Meeting:
    """`doc`: index metadata (body, url, title, number, date); `parsed`: parse.SCHEMA output."""
    lines, _ = number_lines(text)
    h = parsed["header"]
    body = h["body"]
    date = dt.date.fromisoformat(h["date"])
    term = reg.term_for(date)
    issues: list[Issue] = []

    def issue(sev, code, msg, line=None):
        if code in accepted_issues:
            sev = "warn"
        issues.append(Issue(sev, code, msg, line))

    # header vs. index title
    if doc.get("body") and doc["body"] != body:
        issue("error", "header-body", f"title says {doc['body']}, document says {body}")
    if doc.get("number") and doc["number"] != h["number"]:
        issue("error", "header-number", f"title says {doc['number']}, document {h['number']}")
    if doc.get("date") and str(doc["date"]) != h["date"]:
        issue("error", "header-date", f"title says {doc['date']}, document {h['date']}")

    # attendance -> member ids
    people: dict[str, dict] = {}
    att: dict[str, list[str]] = {}
    for key in ("present", "excused", "absent"):
        att[key] = []
        for raw in parsed["attendance"][key]:
            mid = reg.resolve_attendee(raw, term)
            if mid is None:
                mid = "x-" + slug(" ".join(t for t in raw.split() if not t.endswith(".")))
                issue("warn", "unknown-member", f"'{raw}' is not in the {term.id} registry")
                people[mid] = {"name": raw, "list": None}
            att[key].append(mid)
    registry, _ = reg.registry()
    for mid in {m for v in att.values() for m in v}:
        if mid in registry:
            people[mid] = {"name": registry[mid].full_name, "list": term.lists.get(mid)}
    everyone = [m for k in ("present", "excused", "absent") for m in att[k]]
    if len(set(everyone)) != len(everyone):
        issue("error", "attendance-duplicate", "a member is listed twice in attendance")
    if len(set(everyone)) != SEATS[body]:
        issue("warn", "attendance-size",
              f"{len(set(everyone))} members in attendance lists, body has {SEATS[body]} seats")

    events = []
    for e in parsed["presence_events"]:
        mid = reg.match(e["name"], everyone)
        if mid is None:
            issue("error", "event-unknown-member", f"arrival/departure of '{e['name']}'", e["line"])
            continue
        events.append((e["line"], mid, e["event"]))
    events.sort()

    def present_at(line: int) -> set[str]:
        here = set(att["present"])
        first = {}
        for ln, mid, ev in events:
            first.setdefault(mid, ev)
        for mid, ev in first.items():  # someone whose first event is arriving was not there
            if ev == "arrive":
                here.discard(mid)
        for ln, mid, ev in events:
            if ln >= line:
                break
            (here.add if ev == "arrive" else here.discard)(mid)
        return here

    # agenda
    agenda = []
    for a in parsed["agenda_items"]:
        spk = [reg.match(s, everyone) for s in a["speakers"]]
        agenda.append({"no": a["no"], "title": ws(a["title"]), "line": a["line"],
                       "speakers": [s for s in spk if s]})
    agenda_by_key = {_agenda_key(a["no"]): a for a in agenda}

    quorum = SEATS[body] // 2 + 1

    # votes
    vote_lines: set[int] = set()  # whole-resolution vote lines, cut from resolution text
    votes = []
    for i, v in enumerate(sorted(parsed["votes"], key=lambda v: v["line"]), 1):
        raw = "\n".join(lines[v["line"] - 1:v["last_line"]]) if 1 <= v["line"] <= v["last_line"] <= len(lines) else ""
        if not raw:
            issue("error", "vote-lines", f"vote #{i} has invalid lines {v['line']}–{v['last_line']}", v["line"])
        if not v["part"]:  # part votes ("Ing. X (pro 5, …)") are part of the text itself
            vote_lines.update(range(v["line"], v["last_line"] + 1))
        counts = {k: v[k] for k in OPTIONS}
        raw_counts = counts_in_raw(raw)
        for k in OPTIONS:
            if raw_counts[k] is not None and raw_counts[k] != (counts[k] or 0):
                issue("error", "vote-count-mismatch",
                      f"vote #{i}: {k} is {counts[k]} in parse but {raw_counts[k]} in text", v["line"])
            if raw_counts[k] is None and k != "nehlasoval" and counts[k]:
                issue("warn", "vote-count-unverified", f"vote #{i}: {k} not found in raw line", v["line"])
        passed = counts["pro"] >= quorum
        outcome = "prijato" if passed else "neprijato"
        if v["stated_outcome"] and v["stated_outcome"] != outcome:
            issue("error", "outcome-contradiction",
                  f"vote #{i}: text says {v['stated_outcome']}, pro {counts['pro']} vs quorum {quorum}",
                  v["line"])
            outcome = None
        here = present_at(v["line"])
        ballots, status, notes = _ballots(v, counts, here, everyone, att)
        for n in notes:
            issue("warn", "ballots", f"vote #{i}: {n}", v["line"])
        n_voting = sum(counts[k] or 0 for k in OPTIONS)
        if n_voting > len(here):
            issue("warn", "vote-exceeds-present",
                  f"vote #{i}: {n_voting} votes but {len(here)} members present", v["line"])
        motion = None
        if v["motion_first_line"] and v["motion_last_line"]:
            motion = clean_block(lines[v["motion_first_line"] - 1:v["motion_last_line"]])
        votes.append({
            "seq": i, "line": v["line"], "raw": ws(raw),
            "resolution": normalize_number(v["resolution"], body) if v["resolution"] else None,
            "part": v["part"], "subject": v["subject"], "proposer": v["proposer"],
            "motion_text": motion, "procedural": v["procedural"],
            **counts, "quorum": quorum, "passed": passed, "stated_outcome": v["stated_outcome"],
            "outcome": outcome, "present": len(here), "ballots_status": status,
            "ballots": ballots,
        })

    # resolutions
    markers = resolution_numbers_in_text(text)
    parsed_numbers = [normalize_number(r["number"], body) for r in parsed["resolutions"]]
    markers = {normalize_number(m, body) for m in markers}
    for missing in sorted(markers - set(parsed_numbers)):
        issue("error", "resolution-missing", f"{missing} is in the text but not in the parse")
    for extra in sorted(set(parsed_numbers) - markers):
        issue("warn", "resolution-unmarked", f"{extra} parsed but no standalone marker line")
    if len(set(parsed_numbers)) != len(parsed_numbers):
        issue("error", "resolution-duplicate", "a resolution number is parsed twice")

    resolutions = []
    for r, number in zip(parsed["resolutions"], parsed_numbers):
        fl, ll = r["first_line"], r["last_line"]
        if not (1 <= fl <= ll <= len(lines)):
            issue("error", "resolution-lines", f"{number}: invalid lines {fl}–{ll}", fl)
            body_lines = []
        else:
            body_lines = [l if (n not in vote_lines and not re.match(r"\s*[ZT]\s*:", l)) else ""
                          for n, l in enumerate(lines[fl - 1:ll], fl)]
        text_clean = clean_block(body_lines)
        if not text_clean:
            issue("error", "resolution-empty", f"{number}: empty text", fl)
        rv = [v for v in votes if v["resolution"] == number]
        whole = [v for v in rv if not v["part"]]
        parts = [v for v in rv if v["part"]]
        if whole:
            status = whole[-1]["outcome"] or "neovereno"
        elif parts:
            outs = {v["outcome"] for v in parts}
            status = ("neovereno" if None in outs else
                      "prijato" if outs == {"prijato"} else
                      "neprijato" if outs == {"neprijato"} else "castecne")
        else:
            status = "neovereno"
            issue("error", "resolution-no-vote", f"{number}: no vote found", fl)
        a = agenda_by_key.get(_agenda_key(r["agenda_no"]))
        resolutions.append({
            "number": number, "uid": slug(number), "agenda_no": r["agenda_no"],
            "agenda_title": a["title"] if a else None, "first_line": fl,
            "text": text_clean, "responsible": r["responsible"], "deadline": r["deadline"],
            "status": status, "verbs": verbs(text_clean),
        })

    return Meeting(
        id=f"{body}-{h['date']}-{h['number']}", body=body, term=term.id, number=h["number"],
        kind=h["kind"], date=date, place=h["place"], source_url=doc.get("url", ""),
        source_title=doc.get("title", ""), attendance=att, attendance_raw=parsed["attendance"],
        agenda_items=agenda, resolutions=resolutions, votes=votes, members=people,
        issues=issues, model_notes=parsed.get("notes", []),
    )


def _ballots(v: dict, counts: dict, here: set[str], everyone: list[str], att: dict):
    """Ballots for one vote: (list, status, notes). status: complete | partial | tallies_only."""
    notes = []
    named: dict[str, str] = {}
    unresolved = False
    for k in OPTIONS:
        names = v["names"][k]
        if not names:
            continue
        ids = [reg.match(n, everyone) for n in names]
        if None in ids:
            notes.append(f"cannot match names {[n for n, i in zip(names, ids) if i is None]}")
            unresolved = True
        for mid in ids:
            if mid:
                named[mid] = k
        if len(names) != (counts[k] or 0):
            notes.append(f"{k}: {len(names)} names but count {counts[k]}")
            unresolved = True
    stray = [m for m in named if m not in here]
    if stray:
        notes.append(f"named but not present by attendance/events: {stray}")
        unresolved = True
    ballots = [{"member": m, "choice": k, "provenance": "named"} for m, k in named.items()]
    status = "partial" if ballots else "tallies_only"
    open_opts = [k for k in OPTIONS if (counts[k] or 0) > 0 and not v["names"][k]]
    remaining = sorted(here - set(named))
    if not unresolved:
        if len(open_opts) == 1 and len(remaining) == counts[open_opts[0]]:
            ballots += [{"member": m, "choice": open_opts[0], "provenance": "inferred"}
                        for m in remaining]
            status = "complete"
        elif not open_opts and not remaining:
            status = "complete"
    if status == "complete":
        for m in everyone:
            if m not in here:
                choice = "omluven" if m in att["excused"] else "nepritomen"
                ballots.append({"member": m, "choice": choice, "provenance": "attendance"})
    return ballots, status, notes


_VERBS = ("schvaluje", "neschvaluje", "souhlasí", "nesouhlasí", "bere na vědomí", "ukládá",
          "doporučuje", "nedoporučuje", "zřizuje", "ruší", "jmenuje", "odvolává", "volí",
          "revokuje", "pověřuje", "vyhlašuje", "rozhoduje", "stanovuje", "deleguje",
          "zmocňuje", "žádá", "vydává", "projednala", "konstatuje", "určuje")


def verbs(text: str) -> list[str]:
    """Decision verbs in the resolution ('schvaluje', 'bere na vědomí', …) – a cheap facet."""
    t = fold(text)
    found = []
    for v in _VERBS:
        if re.search(r"(?<![a-z])" + fold(v) + r"(?![a-z])", t):
            found.append(v)
    if "neschvaluje" in found and "schvaluje" in found and not re.search(r"(?<!ne)schvaluje", t):
        found.remove("schvaluje")
    if "nesouhlasí" in found and "souhlasí" in found and not re.search(r"(?<!ne)souhlasi", t):
        found.remove("souhlasí")
    return found
