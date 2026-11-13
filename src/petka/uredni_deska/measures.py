"""What a notice means on the street: where (the obvod's streets its title names), how long the
measure holds and what it is, for the front page's map.

The posting dates say nothing about the measure itself (a closure of 9.–13. 11. stays posted
until 27. 11.), so for traffic orders (kind `doprava`) the job reads the attached PDF: the
Magistrát's orders have regular lines

    Platnost úpravy:   16. 11. 2026 – 16. 12. 2026        (or "Termín: od 8:00 hod. 9. 11. 2026 do …")
    Důvod:             stavební práce

and a list of the signs it sets (Z2, B28 + E8d (20m), V7a …), from which a rule turns out one
human line: „Uzavřená stezka kvůli stavebním pracím“. Only the dates, the reason, the sign codes
and that line are stored (`notice_measures`); never the applicant, officials or contacts.

Parsing and the wording are pure (tests over cut-down texts of real orders); `refresh` is the
job's unit that downloads and reads what is new.
"""

import datetime as dt
import logging
import re
import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from ..usneseni.text import fold

log = logging.getLogger(__name__)

# kinds of notices that are about a place; the rest (budget, fees, deliveries…) never go on a map
PLACE_KINDS = ("doprava", "stavby", "energie", "prostredi", "majetek", "drazby", "ostatni")

_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")
_LABEL = re.compile(r"^\s{0,3}\S[^:]{0,60}:")         # "Důvod:", "Velikost dopravního značení:" at the line start
_PERIOD = re.compile(r"^\s{0,3}(Platnost úpravy|Celkový termín|Termín)\s*:(.*)$")
_REASON = re.compile(r"^\s{0,3}Důvod( přechodné úpravy)?\s*:(.*)$")
_SIGNS_START = re.compile(r"(užití|použití|použity)\s+dopravních\s+značek|použity dopravní značky")
_SIGNS_END = re.compile(r"S ohledem na|Dopravní značení (a zařízení )?(proveďte|bude)")
_SIGN = re.compile(r"\b(IP|IS|IZ|A|B|C|E|P|S|V|Z)\s?(\d{1,2}[a-z]?)(?![\d/])")


# --- reading the order ----------------------------------------------------------------------

def _dates(s: str) -> list[dt.date]:
    out = []
    for d, m, y in _DATE.findall(s):
        try:
            out.append(dt.date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return out


def _block(lines: list[str], i: int, first: str) -> str:
    """A labelled value and its continuation lines (indented, no label of their own)."""
    out = [first.strip()]
    for line in lines[i + 1:]:
        if not line.strip() or _LABEL.match(line):
            break
        out.append(line.strip())
    return " ".join(x for x in out if x)


def period(text: str) -> tuple[dt.date | None, dt.date | None]:
    """The first and last date the measure holds, from "Platnost úpravy:" (with its continuation
    lines: a substitute date, the days cars are towed) or "Termín:" (the value may sit on the
    next line). None, None when the order doesn't say."""
    lines = text.splitlines()
    found: list[dt.date] = []
    for i, line in enumerate(lines):
        m = _PERIOD.match(line)
        if not m:
            continue
        value = _block(lines, i, m.group(2))
        if not _dates(value):          # "Termín:" alone, the dates on the next line
            nxt = next((x for x in lines[i + 1:] if x.strip()), "")
            value = nxt
        found += _dates(value)
        if m.group(1) == "Platnost úpravy":
            break                       # the order's own validity wins over any other "Termín"
    return (min(found), max(found)) if found else (None, None)


def reason(text: str) -> str | None:
    """'stavební práce', 'kulturní akce', 'oprava nájezdu zvýšené křižovatky (…)'."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _REASON.match(line)
        if m:
            r = re.sub(r"\s+", " ", _block(lines, i, m.group(2))).strip(" .")
            return r[:200] or None
    return None


def signs_block(text: str) -> str:
    """The part of the order that lists the signs."""
    m = _SIGNS_START.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    e = _SIGNS_END.search(rest)
    return rest[:e.start()] if e else rest[:1500]


def signs(text: str) -> list[str]:
    """Sign codes in the order of the document, each once: ['Z2', 'E13'], 'IP10 a-b' -> 'IP10'."""
    return list(dict.fromkeys(a + b for a, b in _SIGN.findall(signs_block(text))))


def intro(text: str) -> str:
    """The sentence that names where: '… přechodnou úpravu provozu na parkovišti Zborovského náměstí …'."""
    m = re.search(r"přechodnou úpravu provozu(.{0,300}?)(\.\s|\n\s*\n)", text, re.S)
    return re.sub(r"\s+", " ", m.group(1)) if m else ""


# --- the human line -------------------------------------------------------------------------

# the reason after "kvůli": the dative of the first noun, the rest (a genitive) stays
_DATIVE = {"prace": "pracím", "akce": "akci", "oprava": "opravě", "kontrola": "kontrole", "vystavba": "výstavbě",
           "udrzba": "údržbě", "demolice": "demolici", "rekonstrukce": "rekonstrukci", "vymena": "výměně",
           "pokladka": "pokládce", "montaz": "montáži", "stavba": "stavbě", "uzavirka": "uzavírce",
           "prekladka": "překládce"}
_ADJ = {"stavebni": "stavebním", "kulturni": "kulturní", "sportovni": "sportovní", "spolecenska": "společenské",
        "zemni": "zemním", "vykopove": "výkopovým", "udrzbove": "údržbovým"}


def because(r: str | None) -> str:
    """'stavební práce' -> 'kvůli stavebním pracím'; '' when the reason is only road safety
    (BESIP) or can't be put in the dative."""
    if not r:
        return ""
    r = re.split(r"[(,;]", r)[0].strip()
    words = r.split()
    if not words or fold(words[0]) in ("besip", "bezpecnost"):
        return ""
    out = []
    for i, w in enumerate(words):
        f = fold(w)
        if f in _ADJ and i < len(words) - 1:
            out.append(_ADJ[f])
            continue
        if f in _DATIVE or re.search(r"(ení|ání|ění|ití|utí)$", w):     # verbal nouns stay: umístění, označení
            out.append(_DATIVE.get(f, w))
            out += words[i + 1:]
            return "kvůli " + " ".join(out)
        return ""
    return ""


def what(codes: list[str], text: str, place: str = "", r: str | None = None) -> str:
    """One line of what the order does, from its signs and reason:
    'Uzavřená stezka kvůli stavebním pracím', 'Na parkovišti zákaz zastavení v úseku 20 m …',
    'Zákaz vjezdu a zastavení kvůli kulturní akci', 'Dočasný přechod pro chodce'.
    Without a sign we know: 'Přechodná úprava provozu …'."""
    has = set(codes)
    block = fold(signs_block(text))
    where = fold(intro(text) + " " + place)
    full = fold(r or "") + " " + fold(intro(text))
    parts = []

    if "uplna uzavirka" in full or "uplnou uzavirku" in full:
        parts.append("úplná uzavírka")
    banned = []
    if "B1" in has and "úplná uzavírka" not in parts:
        banned.append("vjezdu")
    if "B28" in has:
        banned.append("zastavení")
    elif "B29" in has or "IZ8a" in has:
        banned.append("stání")
    if banned:
        s = "zákaz " + " a ".join(banned)
        m = re.search(r"E8d\s*\(?\s*(\d+)\s*m", signs_block(text))
        if m:
            s += f" v úseku {m.group(1)} m"
        if "parkovist" in where:
            s = "na parkovišti " + s
        parts.append(s)
    if "Z2" in has and not ({"B1"} & has) and "úplná uzavírka" not in parts:
        if "stezk" in block or "stezk" in where:
            parts.append("uzavřená stezka")
        elif re.search(r"chodnik\w* za .{0,12}uzavren", block):
            parts.append("uzavřený chodník")
        elif "b/17" in block or "chodnik" in block:
            parts.append("zábrany na chodníku")
        else:
            parts.append("zábrany")
    if "V7a" in has or "V7b" in has:
        parts.append("dočasný přechod pro chodce")
    if {"A15", "Z4d", "Z4a", "Z4b", "Z4c"} & has and not parts:
        parts.append("práce na silnici")
    if {"S1a", "S1b", "S1"} & has:
        parts.append("provoz řízený semafory")
    if "IP22" in has and not parts:
        m = re.search(r"IP\s?22[^„\"]{0,20}[„\"]([^“\"]+)[“\"]", signs_block(text))
        if m:
            parts.append(m.group(1).strip().lower())
    if not parts:
        parts.append("přechodná úprava provozu")
    line = " a ".join(parts)
    line = line[:1].upper() + line[1:]
    tail = because(r)
    if tail:
        return f"{line} {tail}"
    if parts == ["přechodná úprava provozu"] and r and fold(r) != "besip":
        return f"{line}, důvod: {re.split(r'[(;]', r)[0].strip()}"
    return line


def read(text: str, place: str = "") -> dict:
    """Everything we keep from one order's text."""
    a, b = period(text)
    r = reason(text)
    codes = signs(text)
    return {"valid_from": a, "valid_to": b, "reason": r, "signs": codes, "what": what(codes, text, place, r)}


# --- where: the streets a title names ------------------------------------------------------

def place_part(title: str) -> str:
    """The part of a title that says where: after the last " - " („… v Pardubicích - Češkova“),
    or the whole title."""
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", title) if p.strip()]
    return parts[-1] if parts else title


def streets_in(title: str, names: list[str]) -> list[str]:
    """The obvod's streets named in the title's place part, in the order they appear:
    '… - V Ráji a Gorkého' -> ['V Ráji', 'Gorkého']. Longer names first, so 'náměstí Dukelských
    hrdinů' is not also 'Dukelských hrdinů'."""
    hay = fold(place_part(title))
    hits = []
    for name in sorted(names, key=len, reverse=True):
        pat = r"(?<![\w])" + re.escape(fold(name)) + r"(?![\w])"
        m = re.search(pat, hay)
        if m:
            hits.append((m.start(), name))
            hay = hay[:m.start()] + " " * (m.end() - m.start()) + hay[m.end():]
    return [n for _, n in sorted(hits)]


def subject(title: str, found: list[str]) -> str:
    """What a non-traffic notice is about, without its street: 'Změna rozhodnutí - povolení
    stavby - chodníky Staňkova' -> 'změna rozhodnutí, povolení stavby, chodníky'."""
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", title) if p.strip()]
    last = parts.pop() if parts else ""
    for n in found:
        last = re.sub(re.escape(n), " ", last, flags=re.I)
    last = re.sub(r"\s+", " ", re.sub(r"(^|\s)(a|ul\.|ulice)(?=\s|$)", " ", last)).strip(" ,")
    if last:
        parts.append(last)
    s = ", ".join(parts)
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


# --- the job --------------------------------------------------------------------------------

def pending(conn) -> list[dict]:
    """Posted traffic orders of the obvod without a reading, or whose attachments changed since."""
    return conn.execute(
        """SELECT n.id, n.title, n.attachments FROM notices n
           LEFT JOIN notice_measures m ON m.notice_id = n.id
           WHERE n.removed_at IS NULL AND n.is_mo5 AND n.kind = 'doprava' AND jsonb_array_length(n.attachments) > 0
             AND (m.notice_id IS NULL OR m.attachments IS DISTINCT FROM n.attachments)
           ORDER BY n.id""").fetchall()


def store(conn, n: dict, m: dict) -> None:
    conn.execute(
        """INSERT INTO notice_measures (notice_id, attachments, valid_from, valid_to, reason, signs, what)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (notice_id) DO UPDATE SET attachments = EXCLUDED.attachments,
             valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to, reason = EXCLUDED.reason,
             signs = EXCLUDED.signs, what = EXCLUDED.what, read_at = now()""",
        (n["id"], Jsonb(n["attachments"]), m["valid_from"], m["valid_to"], m["reason"], m["signs"], m["what"]))


def refresh(conn, limit: int = 40) -> dict:
    """Read the new traffic orders' PDFs (the deska job's last unit). A download that fails is
    tried again next run; a file without the usual lines is stored without dates (the page then
    says when it was posted) and not read again until its attachments change."""
    from .digest import download, pdf_text       # digest imports the job module
    todo = pending(conn)[:limit]
    done = dated = 0
    with tempfile.TemporaryDirectory() as tmp:
        for n in todo:
            try:
                files = download([n], Path(tmp) / n["id"])
            except Exception as e:      # noqa: BLE001 – one bad file must not stop the rest
                log.warning("measures: %s not downloaded: %s", n["id"], e)
                continue
            store(conn, n, read(pdf_text(files), place_part(n["title"])))
            done += 1
            dated += conn.execute("SELECT valid_to IS NOT NULL AS d FROM notice_measures WHERE notice_id = %s",
                                  (n["id"],)).fetchone()["d"]
    return {"pending": len(todo), "read": done, "dated": dated}
