"""Rectilinear view out of an equirectangular 360° panorama (Panoramax).
usage: pano_view.py PANO.jpg CENTER_AZIMUTH YAW PITCH FOV OUT.jpg [W H]"""
import sys, numpy as np
from PIL import Image
src, center, yaw, pitch, fov, out = sys.argv[1], *map(float, sys.argv[2:6]), sys.argv[6]
W, H = (int(sys.argv[7]), int(sys.argv[8])) if len(sys.argv) > 8 else (1200, 800)
pano = np.asarray(Image.open(src).convert("RGB")); ph, pw = pano.shape[:2]
f = (W / 2) / np.tan(np.radians(fov) / 2)
x, y = np.meshgrid(np.arange(W) - W / 2, np.arange(H) - H / 2)
d = np.stack([x, -y, np.full_like(x, f, dtype=float)], -1); d /= np.linalg.norm(d, axis=-1, keepdims=True)
p = np.radians(pitch); Rx = np.array([[1, 0, 0], [0, np.cos(p), np.sin(p)], [0, -np.sin(p), np.cos(p)]])
d = d @ Rx.T
lon = np.degrees(np.arctan2(d[..., 0], d[..., 2])) + (yaw - center)   # relative to the panorama centre
lat = np.degrees(np.arcsin(np.clip(d[..., 1], -1, 1)))
u = ((lon + 180) % 360) / 360 * pw; v = (90 - lat) / 180 * ph
img = pano[np.clip(v.astype(int), 0, ph - 1), np.clip(u.astype(int), 0, pw - 1)]
Image.fromarray(img).save(out, quality=90)
