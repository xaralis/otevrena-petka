# Otevřená Pětka

Portál otevřených dat **městského obvodu Pardubice V**: co rozhodlo zastupitelstvo a rada
a kdo jak hlasoval, kde se to děje na mapě, kdo chodí na jednání a co právě visí na
úřední desce. Web, otevřená data, REST API a jeden MCP server pro Claude a další AI asistenty.

**https://otevrenapetka.cz** · [Data a API](https://otevrenapetka.cz/data) ·
[OpenAPI](https://otevrenapetka.cz/api/docs) · MCP: `https://otevrenapetka.cz/mcp`

Projekt Filipa Vařechy, budoucího starosty MO Pardubice V. Vzniká vedle webu města, protože zavádění
takových funkcí na pardubice.eu trvá dlouho; cílem je předat ho do správy statutárního města
Pardubice. Nejde o oficiální web města, závazné jsou vždy původní dokumenty.

## Sekce

| sekce | stav | co umí |
|---|---|---|
| [Usnesení](https://otevrenapetka.cz/usneseni) | běží | usnesení a hlasování ZMO a RMO od roku 2018, hledání slovy i podle smyslu, hlasy zastupitelů, mapa, účast na jednáních |
| [Úřední deska](https://otevrenapetka.cz/uredni-deska) | běží | deska obvodu a magistrátu každou hodinu z oficiálního JSON, hledání, archiv sejmutých |
| Rozpočet a hospodaření | ve výstavbě | |
| Smlouvy a zakázky | ve výstavbě | |

### Usnesení

- **Hledání** běžnými slovy i podle významu: fulltext bez diakritiky a sémantické hledání
  přes embeddingy bge-m3, výsledky spojené metodou RRF. Filtry podle orgánu, roku, tématu,
  výsledku a podle toho, jak hlasoval konkrétní člen. Výchozí je od nejnovějších a jen
  platná usnesení.
- **Detail usnesení**: doslovné znění z PDF, výsledek, hlasy jednotlivých zastupitelů, zrušení
  a změny jinými usneseními, mapa míst, odvozené shrnutí, klíčová slova a témata.
- **Mapa**: pozemky, adresy a ulice z usnesení na jedné mapě i u každého usnesení.
- **Jednání**: prezence, body programu, nepřijaté návrhy.
- **Zastupitelé**: podle stran, žebříček účasti na jednáních za volební období, u každého
  hlasování a účast po jednáních.

**Jak data vznikají.** Zdrojem jsou PDF „Usnesení (a zápis)“ na
[pardubice.eu](https://pardubice.eu/zapisy-z-jednani-zmo5):

1. `fetch`: index stránek po letech, stažení PDF, text přes `pdftotext -layout`. Sken bez
   textové vrstvy přepíše model.
2. `parse`: jazykový model (Claude) vrátí strukturu zápisu jako **ukazatele na řádky**:
   body programu, usnesení, hlasování, jmenovité hlasy, příchody a odchody. Znění usnesení
   se pak **vyřízne z PDF**, model ho nepřepisuje.
3. `build` (deterministické): počty hlasů se kontrolují proti hlasovacímu řádku a čísla
   usnesení proti textu. **Výsledek se určuje podle kvora** (nadpoloviční většina všech
   členů: ZMO 8 z 15, RMO 3 z 5). Návrh, který neprošel, není usnesení, i když mu zápis dal
   číslo; vedeme ho jako nepřijatý návrh. Co nesedí, jde k ruční kontrole.
4. `enrich`: model doplní název, shrnutí, klíčová slova, témata a místa (vždy označeno jako
   odvozené).
5. `geo`: místa a pozemky se převedou na geometrii z RÚIAN (ČÚZK). Obecná místa jako
   „Dukla“ se vynechají, pozemky jsou v dnešní podobě (staré číslo, které zaniklo, se nenajde).
6. `load` / `embed` / `export`: Postgres + pgvector, embeddingy, CSV/JSON/GeoJSON
   a `datapackage.json`.

**Hlasy jednotlivých zastupitelů:** zápisy MO V jmenovitě uvádějí jen menšinu (kdo byl proti nebo
se zdržel). Hlas ostatních se odvodí: přítomní v okamžiku hlasování minus jmenovaní hlasovali
pro zbývající možnost, jen pokud to přesně sedí na součet (`provenance = inferred`). Když to
nejde jednoznačně, zůstanou jen součty (`tallies_only`).

### Úřední deska

Zdroj je oficiální strojově čitelná deska podle OFN
[Úřední deska](https://ofn.gov.cz/úřední-desky/2021-07-20/) (JSON-LD):

- `https://pardubice.eu/export/official-board-json?district_id=5`: deska ÚMO Pardubice V
  (v NKOD není; `district_id` 1–8 = MO I–VIII),
- `https://pardubice.eu/export/official-board-json`: deska magistrátu (v NKOD).

`usneseni deska-update` (idempotentní, v clusteru každou hodinu) stáhne obě desky a upsertne
oznámení. Sejmutá se jen označí, nemažou se. **Týká se MO V** (`is_mo5`): vše z desky obvodu
a z desky magistrátu to, co obvod výslovně jmenuje v názvu, odboru nebo čísle jednacím.
Popis oznámení (často s datem narození) se neukládá. U sejmutých doručení písemnosti se
skryje jméno adresáta, přílohy, odkaz i čísla spisu.

## Otevřená data, API a MCP

- **Data**: `/data` na webu. Usnesení jako CSV + JSON s
  [Frictionless `datapackage.json`](https://otevrenapetka.cz/usneseni/data/datapackage.json),
  místa i jako GeoJSON, úřední deska jako CSV + JSON. Formát popisuje
  [docs/otevrena-data.md](docs/otevrena-data.md), včetně doporučení pro úřad.
- **REST API**: `/api/v1/usneseni/…` a `/api/v1/uredni-deska/…`, OpenAPI na `/api/docs`.
- **MCP** (bez přihlášení, jen čtení):

  ```bash
  claude mcp add --transport http otevrena-petka https://otevrenapetka.cz/mcp
  ```

  Nástroje: `hledej_usneseni`, `usneseni_detail`, `usneseni_k_mistu`, `jednani`, `clenove`,
  `hlasovani_clena`, `statistika`, `uredni_deska_hledej`.

## Soukromí a přístupnost

Žádné cookies, analytika ani přístupový log; nic se nenačítá od třetích stran (písma,
mapové podklady i vyhledávání podle smyslu běží na vlastním serveru). Podrobnosti na
[/soukromi](https://otevrenapetka.cz/soukromi). Web míří na WCAG 2.1 AA
([prohlášení o přístupnosti](https://otevrenapetka.cz/pristupnost)).

## Struktura repa

| cesta | co |
|---|---|
| `src/petka/web/` | portál: FastAPI aplikace, šablony, styly, statické soubory (včetně mapy) |
| `src/petka/sections.py` | seznam sekcí portálu a jejich stav |
| `src/petka/mcp_server.py` | jeden MCP server pro celý portál |
| `src/petka/usneseni/` | sekce Usnesení: pipeline, geokódování, hledání, web, API, MCP |
| `src/petka/uredni_deska/` | sekce Úřední deska: stahování, web, API, MCP |
| `migrations/` | schéma Postgresu (spouští se samo při startu) |
| `data/usneseni/sources.json` | index zveřejněných PDF (URL, sha256) |
| `data/usneseni/text/` | text každého zápisu |
| `data/usneseni/extracted/` | výstupy `parse` a `enrich` po jednáních: zdroj pravdy pro databázi |
| `data/usneseni/overrides/` | ručně ověřené výjimky (nesrovnalost je opravdu ve zdrojovém dokumentu) |
| `data/usneseni/embeddings.jsonl` | embeddingy, aby se při obnově databáze nepočítaly znovu |
| `data/usneseni/geo.json`, `geo_cache.json` | geometrie míst a odpovědi ČÚZK (dotazuje se jen nové) |
| `config/usneseni/` | členové podle volby.cz (`scripts/members_from_volby.py`), témata |
| `docs/` | formát otevřených dat, zpracování jednání subagenty, skici značky |

Týdenní workflow `opendata-snapshot` stahuje zpracovaná data z produkce zpět do gitu, takže
historie dat je v repu.

## Lokální běh

```bash
uv sync
createdb usneseni                               # Postgres s rozšířením pgvector
uv run usneseni load                            # databáze z data/
EMBED_URL=http://localhost:8080 uv run usneseni embed   # volitelně: llama.cpp server s bge-m3
uv run usneseni export
uv run usneseni deska-update                    # úřední deska
uv run usneseni serve --port 8099
uv run pytest
```

Nová jednání se zpracují `usneseni update` (stažení, Claude API, geokódování, načtení,
embeddingy, export; potřebuje `ANTHROPIC_API_KEY`). Spouští se ručně po zveřejnění zápisu:
zastupitelstvo zasedá zhruba čtvrtletně, rada jednou až dvakrát měsíčně. Bez API jde zpracování
přes přihlášený Claude Code (`LLM_BACKEND=claude-cli`, viz [docs/agent-backfill.md](docs/agent-backfill.md)).

Mapový podklad (`src/petka/web/static/map/pardubice.pmtiles`) je výřez okolí Pardubic
z buildu [Protomaps](https://protomaps.com) (OpenStreetMap). Vykresluje ho
[MapLibre GL JS](https://maplibre.org) (BSD-3-Clause), soubor čte knihovna
[PMTiles](https://github.com/protomaps/PMTiles) (BSD-3-Clause).

## Provoz

Běží v k3s (homelab, Flux) jako jeden image z GHCR (`sha-<short>`): web s API a MCP, Postgres
s pgvectorem, llama.cpp server s bge-m3 a dvě úlohy: `update` (pozastavená, spouští se ručně)
a `deska` (každou hodinu). Chyby hlásí GlitchTip.

## Licence

Kód: MIT. Data (`data/`, otevřená data na webu): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.cs).
Uveďte „Otevřená Pětka (otevrenapetka.cz), zdroj: Statutární město Pardubice“.
Zdrojové dokumenty jsou úřední dokumenty zveřejněné městem. Mapové podklady
© přispěvatelé OpenStreetMap (ODbL), polohy míst © ČÚZK (CC BY 4.0).
