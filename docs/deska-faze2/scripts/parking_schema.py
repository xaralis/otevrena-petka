"""Plan view of a parking row today and after the change, as SVG. Input JSON:
{"title": ..., "street": "Bartoňova", "kind": "kolmé"|"podélné",
 "before": [{"type": "bezne"|"ztp"|"kratkodobe"|"doprovod"|"zakaz", "n": 3, "label": "..."}],
 "after":  [...]}"""
import json, sys
STYLE = {
    "bezne":      ("#ffffff", "#7d838b", ""),
    "ztp":        ("#1e5bb8", "#1e5bb8", "♿"),
    "kratkodobe": ("#067352", "#067352", "30′"),
    "doprovod":   ("#b86e00", "#b86e00", "MŠ"),
    "rezident":   ("#5b3fa0", "#5b3fa0", "R"),
    "zakaz":      ("url(#hatch)", "#de091c", ""),
}
NAMES = {"bezne": "běžné stání", "ztp": "vyhrazené pro vozíčkáře", "kratkodobe": "krátkodobé (kotouč)",
         "doprovod": "jen doprovod dětí MŠ", "rezident": "rezidenti", "zakaz": "zákaz stání"}

def row(items, y, changed, kind):
    w, h = (34, 58) if kind == "kolmé" else (64, 30)
    out, x = [], 0
    for i, it in enumerate(items):
        fill, stroke, mark = STYLE[it["type"]]
        n = it.get("n", 1)
        span = n * w if it["type"] != "zakaz" else max(n, 2) * w
        if it["type"] == "zakaz":
            out.append(f'<rect x="{x}" y="{y}" width="{span}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
            if it.get("label"): out.append(f'<text x="{x + span / 2}" y="{y + h / 2 + 4}" class="zl">{it["label"]}</text>')
        else:
            for k in range(n):
                out.append(f'<rect x="{x + k * w}" y="{y}" width="{w}" height="{h}" fill="{fill if it["type"] != "bezne" else "#fff"}" '
                           f'fill-opacity="{0.9 if it["type"] != "bezne" else 1}" stroke="{stroke}" stroke-width="1.5"/>')
                if mark: out.append(f'<text x="{x + k * w + w / 2}" y="{y + h / 2 + 6}" class="mk">{mark}</text>')
        if i in changed:
            out.append(f'<rect x="{x - 4}" y="{y - 4}" width="{span + 8}" height="{h + 8}" fill="none" stroke="#191c1f" stroke-width="3" stroke-dasharray="6 4" rx="3"/>')
        x += span + (6 if it["type"] == "zakaz" else 0)
    return "\n".join(out), x, h

spec = json.load(open(sys.argv[1]))
kind = spec.get("kind", "kolmé")
def diff(a, b):
    return {i for i, it in enumerate(b) if i >= len(a) or (it["type"], it.get("n", 1)) != (a[i]["type"], a[i].get("n", 1))}
r1, w1, h = row(spec["before"], 40, set(), kind)
r2, w2, _ = row(spec["after"], 40 + h + 70, diff(spec["before"], spec["after"]), kind)
W = max(w1, w2) + 40
road_y = 40 + h + 70 + h + 10
used = sorted({it["type"] for it in spec["before"] + spec["after"]}, key=list(STYLE).index)
legend = "".join(f'<g transform="translate({20 + i * 190},{road_y + 64})"><rect width="16" height="16" fill="{STYLE[t][0] if t != "bezne" else "#fff"}" stroke="{STYLE[t][1]}" stroke-width="1.5"/><text x="24" y="13" class="lg">{NAMES[t]}</text></g>' for i, t in enumerate(used))
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 0 {max(W, 20 + len(used) * 190)} {road_y + 96}" font-family="Bricolage Grotesque, Liberation Sans, sans-serif">
<defs><pattern id="hatch" width="8" height="8" patternTransform="rotate(45)" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#fff"/><rect width="3" height="8" fill="#de091c" fill-opacity=".55"/></pattern>
<style>.t{{font-size:15px;font-weight:700;fill:#191c1f}} .mk{{font-size:17px;font-weight:700;fill:#fff;text-anchor:middle}} .zl{{font-size:11px;font-weight:700;fill:#b00716;text-anchor:middle}} .lg{{font-size:12px;fill:#3b3f44}} .rd{{font-size:12px;fill:#fff;font-weight:600}}</style></defs>
<text x="0" y="28" class="t">Dnes</text>{r1}
<text x="0" y="{40 + h + 58}" class="t">Po změně</text>{r2}
<rect x="-20" y="{road_y}" width="{W + 20}" height="40" fill="#5f6368"/><text x="0" y="{road_y + 25}" class="rd">{spec.get("street", "")}</text>
{legend}
</svg>'''
open(sys.argv[2], "w").write(svg)
