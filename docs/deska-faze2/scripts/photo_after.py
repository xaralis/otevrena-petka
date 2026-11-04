"""'Po' over a real photo: strike the signs that go, add the new ones (official pictures)."""
import sys
from PIL import Image, ImageDraw, ImageFont
ZN = "/home/xaralis/Workspace/otevrena-petka/src/petka/web/static/znacky/"
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
img = Image.open(sys.argv[1]).convert("RGB"); out = sys.argv[2]
d = ImageDraw.Draw(img, "RGBA")
RED = (222, 9, 28, 255)

def strike(box):
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=RED, width=4)
    d.line([(x0, y0), (x1, y1)], fill=RED, width=5); d.line([(x0, y1), (x1, y0)], fill=RED, width=5)

def sign(code, xy, h):
    s = Image.open(ZN + code + (".jpg" if code.startswith("IP") else ".png")).convert("RGBA")
    s = s.resize((round(s.width * h / s.height), h)); img.paste(s, xy, s)
    return s.width

def plate(text, xy, w, size=11):
    f = ImageFont.truetype(FONT, size); x, y = xy
    lines = text.split("\n"); hh = len(lines) * (size + 3) + 6
    d.rectangle([x, y, x + w, y + hh], fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=2)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=f); d.text((x + (w - tw) / 2, y + 4 + i * (size + 3)), l, font=f, fill=(20, 20, 20, 255))

def label(text, xy, bg):
    f = ImageFont.truetype(FONT, 15); x, y = xy; tw = d.textlength(text, font=f)
    d.rectangle([x - 6, y - 4, x + tw + 6, y + 20], fill=bg); d.text((x, y), text, font=f, fill=(255, 255, 255, 255))

if sys.argv[3] == "after":
    strike((403, 203, 428, 245)); strike((492, 200, 520, 248))      # the two IP12 for the reserved space go
    w = sign("IP13b", (540, 140), 64)                                # short-term parking takes its place
    plate("MAX. 30 min\nod 7:30\ndo 18:00 hod.", (532, 208), 82, size=12)
    label("ruší se: vyhrazené místo (ZTP)", (230, 172), (222, 9, 28, 230))
    label("nově: parkování s kotoučem, max. 30 min", (620, 112), (6, 115, 82, 235))
else:
    label("dnes: vyhrazené místo pro vozíčkáře", (330, 168), (25, 28, 31, 220))
f = ImageFont.truetype(FONT, 11)
d.text((8, img.height - 18), "Foto: Dvorný, Panoramax, CC BY-SA 4.0" + (" · upraveno: značky podle přílohy OOP, poloha přibližná" if sys.argv[3] == "after" else ""),
       font=f, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
img.save(out, quality=90)
