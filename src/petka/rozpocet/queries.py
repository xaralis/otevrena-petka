"""Reading the budget tables (pages). Amounts in the tables are thousands of Kč; pages show
millions. Grouping into oblasti (oddíly) is a pure function so it can be tested without a
database."""

import re

from .. import db
from ..uredni_deska.queries import tsquery
from . import names

UNIT = "mo5"
SMALL = 0.01          # oblasti under 1 % of the year's plan go to "Ostatní"


# --- pure ----------------------------------------------------------------------------------

def mil(v: float) -> str:
    """115757.55 (tis. Kč) -> '115,8'"""
    return f"{v / 1000:,.1f}".replace(",", " ").replace(".", ",").replace(" ", " ")


def tis(v: float) -> str:
    """12927.8 -> '12 928'"""
    return f"{v:,.0f}".replace(",", " ")


def pct(a: float, r: float) -> int:
    return min(100, round(a / r * 100)) if r else 0


def signed(d: float) -> str:
    return "0,0" if abs(d) < 50 else ("+" if d > 0 else "−") + mil(abs(d))


def _change(now: float, before: float, top: float) -> dict:
    """A dumbbell on one axis 0..top: hollow dot = previous year, filled dot = this year."""
    d = now - before
    pos = lambda v: round(v / top * 100, 1) if top else 0
    tone = "same" if abs(d) < 50 else "up" if d > 0 else "down"
    return {"d": d, "d_label": signed(d), "tone": tone, "prev_pos": pos(before), "cur_pos": pos(now),
            "line_left": pos(min(now, before)), "line_w": pos(abs(d)), "before": before}


def group(cur: dict, prev: dict, view: str = "plan") -> tuple[list[dict], dict]:
    """Oblasti for one year. cur/prev: {paragraf: (plán, utraceno, úřední název)} in tis. Kč.
    view "plan" sorts by plan, "zmena" by the change against prev and also lists paragrafy that
    had a plan last year only. Returns (groups, axis) – axis is for the dumbbells."""
    total = sum(x[0] for x in cur.values())
    codes = [p for p in {**prev, **cur} if (cur.get(p, (0, 0))[0] or cur.get(p, (0, 0))[1]
                                            or (view == "zmena" and prev.get(p, (0,))[0]))]
    by: dict[str, list[str]] = {}
    for p in codes:
        by.setdefault(names.key(p), []).append(p)
    plan = lambda d, ps: sum(d.get(p, (0,))[0] for p in ps)
    big = [(k, ps) for k, ps in by.items() if total and plan(cur, ps) >= total * SMALL]
    small = [(k, ps) for k, ps in by.items() if (k, ps) not in big]
    top = max([plan(cur, ps) for _, ps in big] + [plan(prev, ps) for _, ps in big] + [1])
    step = 10000 if top > 30000 else 5000 if top > 12000 else 2000
    top = -(-top // step) * step
    axis = {"top": top, "ticks": [{"pos": round(v / top * 100, 1), "label": mil(v) if v else "0"}
                                  for v in range(0, int(top) + 1, step)]}

    def row(p, with_oddil):
        x = cur.get(p, (0, 0, "")); official = x[2] if len(x) > 2 and x[2] else prev.get(p, (0, 0, ""))[2]
        code = "" if p == "odvod" else p
        off = f"{code} {official}".strip() if official else code
        if with_oddil:
            off += f", oddíl {names.key(p)}"
        return {"code": p, "label": names.PARAGRAF.get(p, official or p), "official": off,
                "plan": x[0], "actual": x[1], "plan_label": mil(x[0]), "actual_label": mil(x[1]),
                "pct": pct(x[1], x[0]), **_change(x[0], prev.get(p, (0,))[0], top)}

    def mk(name, official, ps, with_oddil=False):
        rows = [row(p, with_oddil) for p in ps]
        rows.sort(key=lambda r: -r["plan"] if view == "plan" else -r["d"])
        r, a = plan(cur, ps), sum(cur.get(p, (0, 0))[1] for p in ps)
        return {"name": name, "official": official, "plan": r, "actual": a, "plan_label": mil(r),
                "actual_label": mil(a), "pct": pct(a, r), "rows": rows, **_change(r, plan(prev, ps), top)}

    groups = [mk(names.oddil(k)[0], f"oddíl {k} {names.oddil(k)[1]}" if k != "odvod" else names.oddil(k)[1], ps)
              for k, ps in big]
    groups.sort(key=lambda g: -g["plan"] if view == "plan" else -g["d"])
    if small:
        groups.append(mk("Ostatní", "oddíly pod 1 % plánu: " + ", ".join(sorted(k for k, _ in small)),
                         [p for _, ps in small for p in ps], with_oddil=True))
    return groups, axis


# --- database ------------------------------------------------------------------------------

def _code(paragraph, name: str) -> str:
    if paragraph is not None:
        return str(paragraph)
    return "odvod" if name.lower().startswith("úroky z vklad") else "6310"


def years(unit: str = UNIT) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute("SELECT year, as_of FROM budget_years WHERE unit = %s ORDER BY year", (unit,)).fetchall()


def by_paragraph(year: int, unit: str = UNIT) -> dict:
    with db.pool().connection() as conn:
        rows = conn.execute(
            """SELECT paragraph, paragraph_name, sum(revised) AS r, sum(actual) AS a FROM budget_lines
               WHERE unit = %s AND year = %s GROUP BY 1, 2""", (unit, year)).fetchall()
    out: dict = {}
    for x in rows:
        c = _code(x["paragraph"], x["paragraph_name"])
        r, a, n = out.get(c, (0, 0, x["paragraph_name"]))
        out[c] = (r + float(x["r"]), a + float(x["a"]), n)
    return out


def totals(unit: str = UNIT) -> dict:
    """{year: {kind: {approved, revised, actual}}}"""
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM budget_totals WHERE unit = %s", (unit,)).fetchall()
    out: dict = {}
    for x in rows:
        out.setdefault(x["year"], {})[x["kind"]] = {k: float(x[k]) for k in ("approved", "revised", "actual")}
    return out


def paragraph_series(par: str, unit: str = UNIT) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT year, sum(revised)::float AS r, sum(actual)::float AS a FROM budget_lines
               WHERE unit = %s AND paragraph = %s GROUP BY year ORDER BY year""", (unit, int(par))).fetchall()


def paragraph_items(par: str, year: int, unit: str = UNIT) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT item, item_name, sum(revised)::float AS r, sum(actual)::float AS a FROM budget_lines
               WHERE unit = %s AND year = %s AND paragraph = %s GROUP BY 1, 2 ORDER BY 3 DESC""",
            (unit, year, int(par))).fetchall()


def invoices(year: int, q: str = "", oddil: str = "", par: str = "", sort: str = "castka",
             limit: int = 20, offset: int = 0, unit: str = UNIT) -> tuple[list[dict], int, float]:
    w, p = ["unit = %s", "year = %s"], [unit, year]
    if oddil:
        w.append("paragraph / 100 = %s"); p.append(int(oddil))
    if par:
        w.append("paragraph = %s"); p.append(int(par))
    tq = tsquery(q) if q.strip() else None
    if q.strip() and not tq:
        return [], 0, 0.0
    if tq:
        w.append("to_tsvector('simple', f_unaccent(lower(description))) @@ to_tsquery('simple', %s)"); p.append(tq)
    order = "amount DESC" if sort != "oblast" else "paragraph, amount DESC"
    where = " AND ".join(w)
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT * FROM budget_invoices WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
                            (*p, limit, offset)).fetchall()
        n, s = conn.execute(f"SELECT count(*), coalesce(sum(amount), 0)::float FROM budget_invoices WHERE {where}",
                            p).fetchone().values()
    return rows, n, s


def invoice_top(year: int, unit: str = UNIT, n: int = 5) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT paragraph, max(paragraph_name) AS name, sum(amount)::float AS s FROM budget_invoices
               WHERE unit = %s AND year = %s GROUP BY 1 ORDER BY 3 DESC LIMIT %s""", (unit, year, n)).fetchall()


def describe(text: str) -> str:
    """The office's invoice text for display: collapsed spaces, stray quotes gone, capital first."""
    t = re.sub(r"\s+", " ", (text or "").replace('"', "")).strip(" -–")
    return (t[:1].upper() + t[1:]) if t else "(bez popisu)"
