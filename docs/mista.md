# Otevřená data: Místa

Jeden denní export bodů celého statutárního města Pardubice (všech osm obvodů) z
OpenStreetMap: místa „Co je v okolí“ aplikace Pardubice do kapsy, stojany na kola, kontejnery
na tříděný odpad, sběrné dvory a všechna další pojmenovaná místa (firmy, úřady, lékaři, školy…). Aplikace soubor stahuje celý jednou denně a neposílá s ním
žádnou polohu.

Verze souboru 2 (16. 11. 2026; 26. 11. 2026 přibyla pole `phone`, `web` a `email`). Kód: `src/petka/mista/`.

## Adresy

- `GET https://otevrenapetka.cz/api/v1/mista` – soubor níže (JSON).
- `GET https://otevrenapetka.cz/api/v1/mista.geojson` – stejná místa jako GeoJSON
  FeatureCollection: `Point`, `id` prvku = `id` místa, `properties` = pole místa bez `at`.

Obě berou:

- `?obvod=` – jen místa z těchto obvodů (`mo1`–`mo8`, víc oddělte čárkou), bez parametru celé
  město ([ADR 0002](adr/0002-data-za-cele-mesto-filtr-obvod.md)). Neznámý obvod = 422.
- `?druh=` – jen tyto druhy, oddělené čárkou, bez parametru všechny. Neznámý druh = 422.

Odpověď má slabý `ETag` (sestavení + filtr) a `Cache-Control: public, max-age=3600`; dotaz s
`If-None-Match` se stejným ETagem dostane 304 bez těla. S `Accept-Encoding: gzip` přijde
zkomprimovaná (celé město ~750 kB, gzip ~110 kB). Dokud žádné sestavení neproběhlo, 503.

```bash
curl --compressed 'https://otevrenapetka.cz/api/v1/mista?obvod=mo5&druh=stojan,kontejner'
```

## Soubor (verze 2)

```json
{ "v": 2,
  "built": "2026-11-16T04:40:00Z",
  "licence": "© přispěvatelé OpenStreetMap, ODbL 1.0",
  "source": "https://otevrenapetka.cz/data#mista",
  "places": [
    { "id": "n123", "kind": "potraviny", "name": "Albert", "what": "Supermarket",
      "address": "Teplého 2119", "at": [15.77669, 50.03809], "hours": "Mo-Su 07:00-21:00",
      "obvody": ["mo5"] },
    { "id": "n456", "kind": "kontejner", "name": null, "what": "Kontejnery na tříděný odpad",
      "address": null, "at": [15.77077, 50.04822], "hours": null, "obvody": ["mo2"],
      "odpad": ["papir", "plast", "sklo"] },
    { "id": "n789", "kind": "stojan", "name": null, "what": "Stojan na kola",
      "address": null, "at": [15.77714, 50.03871], "hours": null, "obvody": ["mo1"],
      "capacity": 10 } ] }
```

| pole | co |
|---|---|
| `v` | verze formátu; nekompatibilní změna tvaru ji zvýší |
| `built` | kdy se místa naposledy změnila (UTC): sestavení z Overpassu, nebo pozdější týdenní doplnění otevíracích dob |
| `licence`, `source` | licence a odkud data jsou |
| `id` | typ objektu OSM (`n` uzel, `w` cesta, `r` relace) + jeho id; stálé mezi dny |
| `kind` | druh, viz níže |
| `name` | název; `null` jen u `stojan`, `kontejner`, `dvur` a `vykupna`. U „Co je v okolí“ vlastní název, jinak značka (u bankomatu i provozovatel), jinak co to je („Veřejné WC“) |
| `what` | co to je, česky |
| `address` | ulice (nebo místo) a číslo z OSM `addr:*`, nebo `null` |
| `at` | `[lon, lat]` na 5 desetinných míst; u cesty a relace její střed |
| `hours` | OSM `opening_hours` beze změny; když ho OSM nemá, doplněná doba (`hours_from`); jinak `null` |
| `obvody` | obvod, ve kterém bod leží (polygony obvodů z RÚIAN; do 20 m za hranicí nejbližší), `[]` mimo všechny |
| `odpad` | jen `kontejner`, `dvur` a `vykupna`: druhy odpadu, které bere; jinde pole chybí |
| `capacity` | jen `stojan`: OSM `capacity` jako celé číslo, nebo `null`; jinde pole chybí |
| `phone` | telefon z OSM `phone`, `contact:phone`, `contact:mobile` nebo `mobile` (první z nich, z více čísel oddělených `;` první); české číslo jako `+420 466 123 456`, jiné jako `+` a číslice. Pole chybí, když OSM číslo nemá |
| `web` | web z OSM `website`, `contact:website` nebo `url`, jinak stránka na Facebooku nebo Instagramu (`contact:facebook`, `facebook`, `contact:instagram`), vždy jako odkaz s `https://`. Pole chybí, když OSM žádný nemá |
| `email` | e-mail z OSM `email` nebo `contact:email`. Pole chybí, když OSM žádný nemá |
| `hours_from` | jen když otevírací doba není z OSM: odkud je (`mesto`, `alltheplaces`, `web`), viz Doplněné otevírací doby. Pole chybí, když je `hours` z OSM nebo `null` |
| `hours_url` | jen u `hours_from` `mesto` a `web`: stránka, ze které doba je |

Místa jsou seřazená podle druhu a `id`. Čtenář neznámá pole a neznámé druhy ignoruje.

### Druhy (`kind`)

Území: OSM `area["name"="Pardubice"]["admin_level"="8"]["boundary"="administrative"]`.

| druh | z OSM | `what` |
|---|---|---|
| `potraviny` | `shop` = supermarket, convenience, greengrocer, bakery, butcher, deli, grocery, general, health_food, farm, frozen_food | Supermarket, Večerka, Ovoce a zelenina, Pekařství, Řeznictví, Lahůdky, Potraviny, Smíšené zboží, Zdravá výživa, Farmářská prodejna, Mražené potraviny |
| `bankomat` | `amenity=atm`; `amenity=bank` + `atm=yes`; bez kryptoměnových automatů | Bankomat; Bankomat u pobočky |
| `lekarna` | `amenity=pharmacy` | Lékárna |
| `jidlo` | `amenity` = restaurant, cafe, fast_food, pub, bar, ice_cream, biergarten | Restaurace, Kavárna, Rychlé občerstvení, Hospoda, Bar, Zmrzlina, Pivní zahrádka |
| `pamatky` | s názvem: `historic=*` (bez pamětních desek a kamenů zmizelých), `tourism` = museum, attraction, `amenity=place_of_worship` | podle `historic` (Zámek, Kostel, Pomník, Památník, Kříž, …, jinak Památka); Muzeum; Zajímavé místo; Kaple / Kostel |
| `wc` | `amenity=toilets`, ne `access` = private, no, customers, permit | Toaleta, placená / zdarma / Toaleta |
| `posta` | `amenity=post_office` | Balíkovna; Pobočka České pošty; Pošta |
| `stojan` | `amenity=bicycle_parking`, ne `access` = private, no | Stojan na kola; Kryté stání pro kola (`covered=yes` nebo `bicycle_parking` = shed, building, shelter); Boxy na kola (`bicycle_parking=lockers`) |
| `kontejner` | `amenity=recycling`, ne `recycling_type=centre`; kontejner, který nebere žádný z druhů odpadu níže, vynecháme | Kontejnery na tříděný odpad |
| `dvur` | `amenity=recycling` + `recycling_type=centre` do 200 m od městského separačního dvora podle seznamu Služeb města Pardubic; dvůr, který v OSM chybí, doplněný z toho seznamu (`id` = `dvur-…`). Název a otevírací doba podle SmP | Sběrný dvůr |
| `vykupna` | ostatní `amenity=recycling` + `recycling_type=centre`: soukromé výkupny a recyklační centra (Kovošrot, JARÝ…) | Výkupna, recyklační centrum |
| `misto` | každý další objekt s názvem (u obchodu a `amenity` stačí značka `brand`), který nepatří do druhů výše a má některý z klíčů `healthcare`, `amenity`, `shop`, `craft`, `office`, `tourism`, `leisure`, `club`, `emergency`, `government`, `company`, `man_made` (závody, ČOV, vodárny, mlýny…), `landuse` (průmyslové, komerční, obchodní areály, hřbitovy, zahrádky, lesy…), `natural` (lesy, vodní plochy, památné stromy…), `building` nebo `place` (městské obvody, části města, čtvrti, místní názvy). Bez mobiliáře (lavičky, koše, parkovací místa…), garáží, kůlen a rodinných domů. Firma zakreslená jako budova i jako bod v ní se stejným názvem do 150 m je jedno místo | podle prvního klíče v tom pořadí, česky (Firma, Zubař, Poliklinika, Škola, Kadeřnictví, Hřiště, Průmyslová budova, Čtvrť…); hodnota mimo slovník dostane obecné slovo klíče (Obchod, Firma, Řemeslo, Budova…). Slovník je v `src/petka/mista/other.py` |

Prvních sedm druhů vybírá a pojmenovává stejně jako `data-tools/build_places.mjs` aplikace
(verze 1 souboru). Druh `misto` aplikace jen prohledává (najde firmu nebo ordinaci podle
názvu), na mapě „Co je v okolí“ ho nekreslí.

### Druhy odpadu (`odpad`)

Z `recycling:<x>=yes`, v tomto pořadí:

| druh | `<x>` |
|---|---|
| `papir` | paper, cardboard, newspaper, magazines, paper_packaging |
| `plast` | plastic, plastic_packaging, plastic_bottles, pet_drink_bottles |
| `sklo` | glass, glass_bottles |
| `kov` | cans, metal_packaging, scrap_metal |
| `textil` | clothes, textiles, shoes |
| `elektro` | electrical_appliances, electrical_items, small_appliances, small_electrical_appliances |
| `baterie` | batteries |
| `olej` | cooking_oil |
| `bio` | green_waste, organic, food_waste |

## Obnova

Úloha `usneseni mista-update` běží jednou denně (CronJob v 4:40). Pošle jeden dotaz na
Overpass API (User-Agent `OtevrenaPetka/1 (+https://otevrenapetka.cz/data#mista)`, při 429,
502 nebo 504 jednou zopakuje po minutě), místa zařadí do obvodů a nahradí je v jedné
transakci. Sestavení, kde je celkem nebo v některém druhu (s aspoň 10 místy v posledním
přijatém) méně než 70 % míst posledního přijatého sestavení, odmítne: Overpass občas vrátí
jen část území. Pak dál platí poslední přijatý export a úloha nahlásí chybu.

Chybějící nebo špatné místo se opravuje přímo v OpenStreetMap; do exportu se dostane při
další obnově.

## Doplněné otevírací doby

Otevírací dobu má v OSM jen asi třetina služeb ve městě. Úloha `usneseni mista-doplnky` (jednou
týdně) proto doplní dobu, případně telefon a web, místům, jejichž objekt v OSM ji nemá, ze tří
otevřených zdrojů (`src/petka/mista/doplnky.py`):

| `hours_from` | zdroj | jak se páruje |
|---|---|---|
| `mesto` | ruční seznam úřadů a institucí města v `data/mista/hodiny.json`: úřední hodiny magistrátu a obvodů, knihovny, bazény…, každá doba se stránkou, odkud je, a dnem ověření | podle `id` místa |
| `alltheplaces` | [All The Places](https://www.alltheplaces.xyz/) (CC0): oficiální vyhledávače poboček řetězců (Albert, Lidl, Dr.Max, Česká pošta, banky…), jednou týdně | nejbližší místo do 100 m, jehož název obsahuje značku řetězce; u pošty nejbližší pošta |
| `web` | vlastní web místa (jeho `web` z OSM, ne Facebook ani Instagram), jen když stránka dobu uvádí jako strukturovaná data schema.org (`openingHoursSpecification`, `openingHours`) | podle `web` místa |

Doba z webu se vezme, jen když vypadá věrohodně (každý úsek aspoň 30 minut, nic neotevírá mezi půlnocí a pátou, přes půlnoc nejdéle do šesti). Úloha chodí jen na veřejné adresy http(s), i po přesměrování. OSM má vždy přednost; ze zdrojů `mesto` před `alltheplaces` před `web`. Zdroj, který se ten
týden nepodaří načíst, nechá doplňky z minula. Chybějící dobu je nejlepší doplnit přímo do OSM.

## Licence

Databáze odvozená z OpenStreetMap: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/),
© [přispěvatelé OpenStreetMap](https://www.openstreetmap.org/copyright). Kdo ji použije,
uvede OpenStreetMap a odvozenou databázi sdílí pod stejnou licencí. Na rozdíl od ostatních
dat portálu (CC BY 4.0).
