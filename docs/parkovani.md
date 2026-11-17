# Otevřená data: Parkování

Parkoviště celého statutárního města Pardubice pro aplikaci Otevřené Pardubice a kohokoli
dalšího: parkoviště správce s čidly, ceník podle nařízení, SMS kódy DPMP, automaty, hranice zón,
lokalit a placených úseků ulic; obsazenost každou minutu a statistiky z její historie.
Kód: `src/petka/parkovani/`, data: `data/parkovani/`.

## Zdroje

| část | odkud | obnova |
|---|---|---|
| parkoviště | ChytřejšíParking (DPMP), `…/admin/api/app/parking/occupancy` a `…/parking/locations` | denně, `parkovani-update` |
| obsazenost | ChytřejšíParking, `…/parking/occupancy` | každých 60 s, `parkovani-obsazenost` |
| ceník | nařízení 3/2026, čl. 2 (`data/parkovani/cenik.json`) | ručně |
| SMS kódy | PDF DPMP z 1. 10. 2025 (`sms-kody.json`) | ručně |
| automaty | seznam DPMP, souřadnice z podkladů aplikace (`automaty.json`) | ručně |
| zóny | příloha 1 nařízení 2/2026 ve znění 5/2026 (`zony.json`) | ručně |
| přilehlá oblast zóny B | příloha 6 nařízení 2/2026 (`prilehla-oblast.json`) | ručně |
| lokality, návštěvnická místa | přílohy 2–4 nařízení 2/2026 (`lokality.json`) | ručně |
| placené úseky | přílohy 2–4, spárované se skupinami stání podle čidel (`useky.json`) | ručně |
| oblasti | Otevřená Pětka: části města, jak o nich mluví lidé, a jejich parkoviště (`oblasti.json`) | ručně |

Rozhraní ChytřejšíParkingu je **neoficiální**: bez dokumentace, bez licence a bez času měření.
Pětka se ptá s obecným `User-Agent` bez osobních údajů. Ručně udržovaná data přešla z repa
aplikace (`design/parkovani-*.json`, `design/automaty.json`, `assets/data/*.json`) 16. 11. 2026.
Každý soubor v `data/parkovani/` nese `source`, `url`, `checked` (kdy jsme ho naposledy ověřili
proti zdroji), případně `valid_from` a `note`; export je opakuje v `sources`.

**Údržba.** Když se změní nařízení nebo tabulka DPMP: opravit soubor, posunout `checked`
(a `valid_from`) a nasadit; ETag exportu obsahuje hash souborů, takže aplikace změnu stáhne
hned. Geometrie zón, lokalit a úseků vznikly převodem vektorových příloh nařízení nástrojem
`data-tools/build_static_data.py` v repu aplikace (PyMuPDF, vlícování přes automaty, kontrola
proti OpenStreetMap); ten se při změně příloh spustí znovu a jeho výstup se sem přenese.
`parkovani-update` vypisuje do `report.notes` rozpory mezi ceníkem správce a nařízením
(jiná cena, jiná provozní doba, placené parkoviště bez ceny).

## Adresy

Všechny jsou za celé město a berou `?obvod=` (`mo1`–`mo8`, víc oddělte čárkou; [ADR 0002](adr/0002-data-za-cele-mesto-filtr-obvod.md)).
Všechny posílají slabý `ETag`; dotaz s `If-None-Match` se stejným ETagem dostane 304 bez těla.

### `GET /api/v1/parkovani`

Jeden soubor, ze kterého aplikace nahradí své přibalené soubory jeden k jednomu:

```json
{ "v": 1,
  "built": "2026-11-16T04:00:00Z",
  "source": "https://otevrenapetka.cz/data#parkovani",
  "sources": {
    "lots": {"source": "ChytřejšíParking (DPMP), …", "url": "…", "fetched": "2026-11-16T04:00:00Z"},
    "tariffs": {"source": "Nařízení … 3/2026 …", "url": "https://pardubice.eu/parkovani",
                "valid_from": "2026-06-01", "checked": "2026-11-07", "note": "…"},
    "smsCodes": {…}, "machines": {…}, "zones": {…}, "adjacent": {…}, "localities": {…}, "sections": {…} },
  "parking": {                                   // = assets/data/parking.json
    "lots": [ { "id": "PRD.PRK.LOK-LI-1-1", "name": "Pernštýnské náměstí", "area": "Perštýnské náměstí",
                "zone": "A", "smsCode": "1", "paid": true, "note": "", "at": [15.779726, 50.038738],
                "locality": "L.1",
                "tariff": {"hours": [{"day": "pondělí–neděle", "time": "7:00–20:00"}],
                           "halfHour": 25, "firstHour": 50, "nextHour": 50},
                "kind": "visitor", "capacity": 29, "obvody": ["mo1"] } ],
    "machines": [ { "name": "Sladkovského I.", "at": [15.77229, 50.038225], "obvody": ["mo1"] } ] },
  "zones": [ { "zone": "A", "ring": [[15.77037, 50.03…], …], "obvody": ["mo1"] } ],      // = zones.json
  "adjacent": { "zone": "B", "ring": […], "obvody": ["mo3"] },                            // = adjacent.json
  "localities": {                                                                        // = localities.json
    "localities": [ { "code": "A-1", "zone": "A", "ring": […], "visitor": ["L.1", …], "streets": […], "obvody": ["mo1"] } ],
    "visitor": [ { "code": "L.1", "sheet": "A-1", "name": "…", "street": "…", "at": […], "sections": […], "zone": "A", "obvody": ["mo1"] } ],
    "tariffs": { "L.1": {…}, "A-1": {…} } },
  "sections": [ { "locality": "A-1", "kind": "mixed", "street": "Na Třísle", "rings": [[[…]]],
                  "lots": ["PRD.PRK.LOK-LII-59", null], "obvody": ["mo1"] } ],             // = sections.json
  "areas": [ { "id": "u-mlynu", "name": "U Mlýnů", "lots": ["PRD.PRK.LOK-LI-7-9", …], "obvody": ["mo1"] } ],
  "smsCodes": [ { "number": "1", "zone": "A", "name": "Pernštýnske náměstí", "sms": "1" } ] }
```

| pole | co |
|---|---|
| `built` | kdy úloha stáhla parkoviště (UTC) |
| `parking.lots[]` | `id` správce (stejné jako v obsazenosti a v `sections[].lots`), `name`, `area` (část města podle správce), `zone` a `smsCode` z tabulky DPMP podle čísla oblasti (jen placená), `paid` (lze zaplatit), `note` (u neplacených, kdo smí parkovat), `at` [lon, lat], `locality` (A-1 … C-3, L.1 … L.8), `tariff` (ceník lokality z nařízení; `hoursDiffer`: správce uvádí jinou provozní dobu), `kind` (`mixed`, `visitor`, `resident`), `capacity` (míst při stažení), `obvody` |
| `tariff` | `hours` [{day, time}], buď `wholeDay` (Kč za den), nebo `halfHour`, `firstHour`, `nextHour` a případně `dayCap` (strop za den), vše v Kč |
| `parking.machines[]` | parkovací automat: `name`, `at`, `obvody` |
| `zones[]`, `adjacent` | hranice zón A, B, C a přilehlé oblasti zóny B (uzavřený kruh [lon, lat]); chyba převodu ~4 m, do 20 m od hranice nelze říct jednu zónu |
| `localities` | lokality s hranicí a ulicemi, návštěvnická místa L.1–L.8 se středy zelených úseků, ceník podle kódu |
| `sections[]` | placené úseky jedné ulice v lokalitě jako pásy: `kind` `mixed` / `resident` / `visitor`, `rings`, ke každému pásu `lots` = id parkoviště, jehož čidla na něm leží, nebo `null` |
| `areas[]` | oblasti, jak o nich mluví lidé (Masarykovo náměstí, U Mlýnů, u nemocnice…): `id`, `name`, `lots` = id parkovišť (každé nejvýš v jedné oblasti), `obvody` = obvody jejích parkovišť. Je to náš seznam, ne hranice na mapě; volno oblasti = součet volna jejích parkovišť v obsazenosti |
| `obvody` | obvody podle polygonů RÚIAN: bod, u ploch obvody s aspoň 1 % plochy, u úseků podle středů pásů |

`?obvod=` zúží `parking.lots`, `parking.machines` a `sections`. Zóny, přilehlá oblast, lokality,
ceník a SMS kódy jsou pravidla celého města a přijdou vždy celé. `Cache-Control: public,
max-age=3600`; celé město ~215 kB, gzip ~40 kB. Před prvním stažením 503.

### `GET /api/v1/parkovani/obsazenost`

```json
{ "v": 1, "fetched_at": "2026-11-16T18:26:36Z", "source": "https://otevrenapetka.cz/data#parkovani",
  "note": "…",
  "lots": [ { "id": "PRD.PRK.LOK-LI-1-1", "free": 16, "total": 29,
              "changed_at": "2026-11-16T18:21:35Z", "obvody": ["mo1"] } ] }
```

- `fetched_at` – poslední **úspěšné** stažení. Při výpadku zdroje zůstanou poslední dobrá čísla
  a `fetched_at` stárne.
- `changed_at` – kdy Pětka naposledy viděla změnu `free` nebo `total` parkoviště (při prvním
  stažení čas stažení). Zdroj čas měření nemá; parkoviště, jehož čísla se dlouho nemění, může
  mít zamrzlé čidlo, nebo se tam jen nic neděje (v noci).
- **Stáří posuzujte podle `fetched_at`**: je-li starší než pár minut, Pětka ze zdroje nic nového
  nemá a čísla mohou být zastaralá. `changed_at` je jen nápověda: v noci nebo na klidném
  parkovišti se čísla hodiny nemění a jsou přesto platná.
- Parkoviště, které zdroj den neuvedl, v odpovědi chybí.
- ETag se mění s každým úspěšným stažením (`fetched_at` je v těle); 304 přijde, když od minula
  stažení neproběhlo. `Cache-Control: public, max-age=30`. Před prvním stažením 503.

### `GET /api/v1/parkovani/statistiky`

Z historie: vzorek každého parkoviště po 5 minutách (první úspěšné stažení v každém
pětiminutovém okně). Parametry `?dni=` (7, 28 nebo 91, výchozí 28; jiná hodnota = 422) a `?profily=true`.

```json
{ "v": 1, "days": 28, "from": "…", "to": "…", "history_from": "…",
  "profile": { "occupancy": [[0.21, …24 hodin], …7 dní], "full": [[…]] },
  "lots": [ { "id": "…", "name": "…", "obvody": ["mo1"], "occupancy": 0.83, "full": 0.41,
              "samples": 8064, "capacity": 45, "profile": {…jen s ?profily=true} } ],
  "areas": [ { "id": "u-mlynu", "name": "U Mlýnů", "lots": ["…"], "occupancy": 0.61, "full": 0.2,
               "samples": 32256, "capacity": 146, "profile": {…jen s ?profily=true} } ] }
```

- Mřížky 7 × 24: pondělí první, hodiny 0–23 pražského času; `null` = bez dat.
- `occupancy` – podíl obsazených míst (součet obsazených / součet všech přes vzorky, velké
  parkoviště váží víc). `full` – podíl vzorků s nejvýš desetinou volných míst („plno“).
- `lots` od nejvytíženějšího. Stránka /verejny-prostor/parkovani v žebříčku vynechá parkoviště
  s méně než 5 místy (často jedno čidlo).
- `areas` v pořadí souboru, jen oblasti s historií: vzorky jejich parkovišť sečtené, `capacity`
  = součet kapacit parkovišť.
- Na stránce /verejny-prostor/parkovani se řádek oblasti nebo parkoviště rozbalí: pod ním se
  ukáže typický týden (a u oblasti její parkoviště). Část stránky dodá /verejny-prostor/parkovani/oblast/{id}
  nebo /parkoviste/{id}, bez JS totéž otevře `?oblast=` / `?parkoviste=`. Větu „Nejplněji bývá…“
  stránka ukáže až po týdnu historie.
- Přepočítává se nejvýš každých 10 minut; `Cache-Control: public, max-age=600`.

## Úlohy

| příkaz | kdy | co |
|---|---|---|
| `petka parkovani-update` | denně (např. 4:00) | stáhne parkoviště, uloží sestavení (`parkovani_builds`); sestavení s méně než 70 % parkovišť posledního přijatého odmítne a skončí chybou, servíruje se dál poslední přijaté (`--force` ho uloží). Doplní polygony obvodů do `ruian_cache`, pokud chybí. `--obsazenost a.json --lokality b.json` načte uložené odpovědi. |
| `petka parkovani-obsazenost --smycka` | stále (Deployment, 1 replika) | každých 60 s (`--kazdych`) stáhne obsazenost do `parkovani_now`, každých 5 minut i do `parkovani_history`. Neúspěch nic nepřepíše; po 10 minutách neúspěchů jedno upozornění do GlitchTipu. SIGTERM ukončí smyčku mezi dvěma staženími. |

`parkovani-obsazenost` bez `--smycka` stáhne jednou a skončí (CronJob `* * * * *` místo
Deploymentu, kdyby byl potřeba; pod za minutu je ale dražší než jeden dotaz). Obě úlohy jsou
idempotentní a spouštějí migrace samy.

## Historie a místo

`parkovani_history` (lot smallint, at, free, total): ~32 000 řádků denně pro 111 parkovišť,
zhruba 0,8 GB ročně i s indexy. Uchovává se celá; zhuštění starších dat na hodiny je možné
později, statistiky čtou jen posledních `dni`.

**Při prvním nasazení** se historie nasbíraná lokálně přenese do produkce, aby statistiky
nezačínaly od nuly: po migraci a **před** spuštěním smyčky obsazenosti (jinak by produkce
přidělila čísla parkovišť `n` jinak) nahrát `parkovani_lots` a `parkovani_history`
se stejnými `n`, např. `pg_dump --data-only -t parkovani_lots -t parkovani_history`
a `psql` v podu databáze; pak `SELECT setval('parkovani_lots_n_seq', max(n)) FROM parkovani_lots`.
