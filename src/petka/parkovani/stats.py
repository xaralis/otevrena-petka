"""Statistics of occupancy from the history (petka.parkovani.queries.history_rows): the typical
week as a grid of weekdays × hours, and the busiest lots. Pure: rows in, plain data out.

Occupancy is the share of occupied places: occupied over total, summed over the samples (so a
big lot weighs more than a small one in a sum over lots). „Plno“ is a sample with at most a tenth
of places free, the app's „obsazeno“. A cell without samples is None.
"""

DAYS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
DAYS_SHORT = ("po", "út", "st", "čt", "pá", "so", "ne")


def _share(a, b) -> float | None:
    return round(a / b, 3) if b else None


def grid(rows: list[dict]) -> dict:
    """{occupancy, full}: each a 7 × 24 grid (Monday first, hour 0–23) over the rows given."""
    occ = [[[0, 0] for _ in range(24)] for _ in range(7)]
    full = [[[0, 0] for _ in range(24)] for _ in range(7)]
    for r in rows:
        d, h = r["dow"] - 1, r["hour"]
        occ[d][h][0] += r["occupied"]
        occ[d][h][1] += r["total"]
        full[d][h][0] += r["full"]
        full[d][h][1] += r["n"]
    return {"occupancy": [[_share(*c) for c in day] for day in occ],
            "full": [[_share(*c) for c in day] for day in full]}


def by_lot(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["id"], []).append(r)
    return out


def lots(rows: list[dict], names: dict[str, str], obvody: dict[str, list[str]], profiles: bool = False) -> list[dict]:
    """Every lot with history, the busiest first: its mean occupancy, the share of samples it was
    full, its samples and capacity (the last total); `profiles` adds each lot's grid."""
    out = []
    for lot_id, rs in by_lot(rows).items():
        n = sum(r["n"] for r in rs)
        item = {"id": lot_id, "name": names.get(lot_id, lot_id), "obvody": obvody.get(lot_id, []),
                "occupancy": _share(sum(r["occupied"] for r in rs), sum(r["total"] for r in rs)),
                "full": _share(sum(r["full"] for r in rs), n), "samples": n,
                "capacity": round(sum(r["total"] for r in rs) / n) if n else None}
        if profiles:
            item["profile"] = grid(rs)
        out.append(item)
    return sorted(out, key=lambda x: (-(x["occupancy"] or 0), -(x["full"] or 0), x["name"]))


def busiest_hours(g: dict, top: int = 3) -> list[dict]:
    """The hours of the week that are fullest on average: [{day, hour, occupancy}]."""
    cells = [(v, d, h) for d, day in enumerate(g["occupancy"]) for h, v in enumerate(day) if v is not None]
    return [{"day": DAYS[d], "hour": h, "occupancy": v} for v, d, h in sorted(cells, reverse=True)[:top]]
