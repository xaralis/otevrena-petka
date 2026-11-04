"""Plan view of a parking row today and after the change (SVG), drawn from what Claude read
off the office's drawing. Deterministic; only ever as good as the drawing it came from."""

from xml.sax.saxutils import escape

TYPES = {  # fill, stroke, mark
    "bezne": ("#ffffff", "#7d838b", ""),
    "ztp": ("#1e5bb8", "#1e5bb8", "♿"),
    "kratkodobe": ("#067352", "#067352", "⏱"),
    "doprovod": ("#b86e00", "#b86e00", "MŠ"),
    "rezident": ("#5b3fa0", "#5b3fa0", "R"),
    "vyhrazene": ("#3b3f44", "#3b3f44", "V"),
    "nabijeni": ("#0e7490", "#0e7490", "⚡"),
    "zakaz": ("url(#hatch)", "#de091c", ""),
}
NAMES = {"bezne": "běžné stání", "ztp": "vyhrazené pro osobu se zdravotním postižením",
         "kratkodobe": "krátkodobé stání", "doprovod": "jen doprovod dětí", "rezident": "rezidenti",
         "vyhrazene": "vyhrazené (firma, úřad…)", "nabijeni": "nabíjení elektromobilů",
         "zakaz": "zákaz stání / zastavení"}


def _row(items: list[dict], y: float, changed: set[int], kind: str) -> tuple[str, float, float]:
    w, h = {"kolme": (34, 58), "sikme": (40, 52), "podelne": (64, 30)}.get(kind, (34, 58))
    out, x = [], 0.0
    for i, it in enumerate(items):
        fill, stroke, mark = TYPES[it["type"]]
        n = max(1, int(it.get("n") or 1))
        span = n * w if it["type"] != "zakaz" else max(n, 2) * w
        if it["type"] == "zakaz":
            out.append(f'<rect x="{x}" y="{y}" width="{span}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        else:
            for k in range(n):
                out.append(f'<rect x="{x + k * w}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
                           f'stroke="{stroke}" stroke-width="1.5"/>')
                if mark:
                    out.append(f'<text x="{x + k * w + w / 2}" y="{y + h / 2 + 6}" class="mk">{mark}</text>')
        if it.get("label"):
            out.append(f'<text x="{x + span / 2}" y="{y - 6}" class="lb">{escape(it["label"])}</text>')
        if i in changed:
            out.append(f'<rect x="{x - 4}" y="{y - 4}" width="{span + 8}" height="{h + 8}" fill="none" '
                       f'stroke="#191c1f" stroke-width="3" stroke-dasharray="6 4" rx="3"/>')
        x += span + 6
    return "\n".join(out), x, h


def changed(before: list[dict], after: list[dict]) -> set[int]:
    key = lambda it: (it["type"], int(it.get("n") or 1), it.get("label") or "")
    return {i for i, it in enumerate(after) if i >= len(before) or key(it) != key(before[i])}


def svg(spec: dict) -> str:
    kind = spec.get("kind", "kolme")
    r1, w1, h = _row(spec["before"], 52, set(), kind)
    y2 = 52 + h + 84
    r2, w2, _ = _row(spec["after"], y2, changed(spec["before"], spec["after"]), kind)
    road = y2 + h + 10
    used = sorted({it["type"] for it in spec["before"] + spec["after"]}, key=list(TYPES).index)
    W = max(w1, w2, 360) + 40
    legend = "".join(
        f'<g transform="translate({(i % 2) * 300},{road + 58 + (i // 2) * 24})"><rect width="16" height="16" '
        f'fill="{TYPES[t][0]}" stroke="{TYPES[t][1]}" stroke-width="1.5"/><text x="24" y="13" class="lg">{NAMES[t]}</text></g>'
        for i, t in enumerate(used))
    height = road + 58 + ((len(used) + 1) // 2) * 24 + 10
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 0 {max(W, 620)} {height}" font-family="Bricolage Grotesque, Liberation Sans, sans-serif" role="img" aria-label="Schéma stání dnes a po změně">
<defs><pattern id="hatch" width="8" height="8" patternTransform="rotate(45)" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#fff"/><rect width="3" height="8" fill="#de091c" fill-opacity=".55"/></pattern>
<style>.t{{font-size:15px;font-weight:700;fill:#191c1f}}.mk{{font-size:17px;font-weight:700;fill:#fff;text-anchor:middle}}.lb{{font-size:11px;font-weight:700;fill:#3b3f44;text-anchor:middle}}.lg{{font-size:12px;fill:#3b3f44}}.rd{{font-size:12px;fill:#fff;font-weight:600}}</style></defs>
<text x="0" y="22" class="t">Dnes</text>{r1}
<text x="0" y="{y2 - 26}" class="t">Po změně</text>{r2}
<rect x="-20" y="{road}" width="{max(W, 620) + 20}" height="34" fill="#5f6368"/><text x="0" y="{road + 22}" class="rd">{escape(spec.get("street") or "")}</text>
{legend}
</svg>'''
