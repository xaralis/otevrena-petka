# Fáze 2 – pohled z ulice: prototypy

Srovnání tří variant na třech reálných oznámeních: [srovnani.png](srovnani.png).

| varianta | verdikt |
|---|---|
| A. Skutečná fotka (příloha úřadu nebo Panoramax 360° → pohled kamerou, značky dosazené podle výkresu) | nejsrozumitelnější, kde fotka existuje; v MO V je pokrytí Panoramaxu mizivé |
| B. Schéma parkování dnes / po změně (SVG z popisu, který Claude vytáhne z výkresu) | vždy použitelné, bez licencí – zavést jako první |
| C. 3D pohled z otevřených dat (MapLibre, budovy z OSM) | nepoužitelné: bez kamery ve výšce očí, jen šedé kvádry |

Skripty jsou prototypy (ne součást aplikace): `pano_view.py` (výřez z 360° panoramatu),
`photo_after.py` (přeškrtnutí rušených a vložení nových značek do fotky), `parking_schema.py`
(schéma řady stání), `3d_view.html` (3D render). Fotka: Dvorný, Panoramax, CC BY-SA 4.0.
