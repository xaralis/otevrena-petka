# Usnesení MO Pardubice V

Prohledávatelná databáze usnesení a hlasování **Zastupitelstva (ZMO)** a **Rady (RMO)
městského obvodu Pardubice V** od roku 2018: web, otevřená data, REST API a MCP server pro
Claude a další AI asistenty.

**https://usneseni.dev.varecha.work** · [otevřená data](https://usneseni.dev.varecha.work/otevrena-data) ·
[API](https://usneseni.dev.varecha.work/api/docs) · MCP: `https://usneseni.dev.varecha.work/mcp`

## Co umí

- **Hledání** běžnými slovy i podle významu (fulltext bez diakritiky + sémantické hledání
  přes embeddingy bge-m3, výsledky spojené metodou RRF), filtry podle orgánu, roku, tématu,
  druhu rozhodnutí, výsledku a podle toho, jak hlasoval konkrétní člen.
- **Usnesení**: doslovné znění z PDF, výsledek hlasování, hlasy jednotlivých členů, odvozené
  shrnutí, klíčová slova, témata, místa, pozemky, organizace a částky.
- **Jednání**: prezence, body programu se shrnutím rozpravy, nepřijaté návrhy a protinávrhy.
- **Členové**: docházka, hlasování, kdy hlasovali jinak, než jak hlasování dopadlo.
- **Automatická aktualizace**: každý den se kontroluje pardubice.eu a nové zápisy se zpracují.

## Jak data vznikají (a jejich limity)

Zdrojem jsou PDF „Usnesení (a zápis)“ zveřejněná na
[pardubice.eu](https://pardubice.eu/zapisy-z-jednani-zmo5). Postup:

1. `fetch` – index stránek po letech, stažení PDF, text přes `pdftotext -layout`
   (sken bez textové vrstvy se přepíše modelem).
2. `parse` – jazykový model (Claude) vrátí strukturu zápisu jako **ukazatele na řádky**:
   body programu, usnesení, hlasování, jmenovité hlasy, příchody a odchody. Znění usnesení
   se pak **vyřízne z PDF**, model ho nepřepisuje.
3. `build` (deterministické) – kontrola počtů hlasů proti hlasovacímu řádku, kontrola, že žádné
   číslo usnesení z textu nechybí, **výsledek podle kvora** (nadpoloviční většina všech členů:
   ZMO 8 z 15, RMO 3 z 5). Návrh, který neprošel, není usnesení, i když mu zápis dal číslo –
   vedeme ho jako nepřijatý návrh. Pak rekonstrukce hlasů členů.
   Cokoli nesedí, označí jednání k ruční kontrole.
4. `enrich` – model doplní název, shrnutí, klíčová slova, témata a entity (označeno jako odvozené).
5. `load` / `embed` / `export` – Postgres + pgvector, embeddingy, CSV/JSON + `datapackage.json`.

**Hlasy jednotlivých členů:** zápisy MO V jmenovitě uvádějí jen menšinu (kdo byl proti nebo se
zdržel), někdy nikoho. Hlas ostatních se odvodí: přítomní v okamžiku hlasování minus jmenovaní
hlasovali pro zbývající možnost – jen pokud to přesně sedí na součet. Takový hlas má
`provenance = inferred`. Když to nejde jednoznačně, zůstanou jen součty (`tallies_only`).

## Struktura repa

| cesta | co |
|---|---|
| `data/sources.json` | index zveřejněných PDF (URL, sha256) |
| `data/text/` | text každého zápisu |
| `data/extracted/` | výstupy `parse` a `enrich` po jednáních – zdroj pravdy pro databázi |
| `data/overrides/` | ručně ověřené výjimky (nesrovnalost je opravdu ve zdrojovém dokumentu) |
| `config/members.yaml` | kandidáti a zvolení podle volby.cz (`scripts/members_from_volby.py`) |
| `config/topics.yaml` | pevný seznam témat a druhů rozhodnutí |
| `src/usneseni/` | pipeline, web (FastAPI), REST API, MCP server |
| `docs/otevrena-data.md` | specifikace formátu otevřených dat (+ doporučení pro úřad) |
| `docs/agent-backfill.md` | zpracování jednání subagentem Claude Code (první naplnění) |

## Lokální běh

```bash
uv sync
createdb usneseni                               # Postgres s rozšířením pgvector
uv run usneseni load                            # databáze z data/
EMBED_URL=http://localhost:8080 uv run usneseni embed   # volitelně, llama.cpp server s bge-m3
uv run usneseni export
uv run usneseni serve --port 8099
uv run pytest
```

Nová jednání: `uv run usneseni fetch && LLM_BACKEND=api uv run usneseni process`
(`ANTHROPIC_API_KEY`), nebo `LLM_BACKEND=claude-cli` přes přihlášený Claude Code.

## MCP

```bash
claude mcp add --transport http usneseni-mo5 https://usneseni.dev.varecha.work/mcp
```

Nástroje: `hledej_usneseni`, `usneseni_detail`, `jednani`, `clenove`, `hlasovani_clena`,
`statistika`. Bez přihlášení, jen čtení.

## Licence

Kód: MIT. Data (`data/`, otevřená data na webu): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.cs),
uveďte „Usnesení MO Pardubice V (usneseni.dev.varecha.work), zdroj: Statutární město Pardubice“.
Zdrojové dokumenty jsou úřední dokumenty zveřejněné městem.
