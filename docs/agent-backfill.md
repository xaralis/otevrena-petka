# Zpracování jednoho jednání subagentem

Postup pro Claude Code subagenta, který místo API (`usneseni process`) zpracuje jedno
jednání ZMO/RMO ručně. Pracovní adresář je kořen repa `usneseni-mo5`. Výsledek ukládá jen
`uv run usneseni agent-accept-*`, které ho validuje stejně jako automatická cesta.

Neměň kód, konfiguraci ani soubory jiných jednání. Nespouštěj git.

## 0. Text

Pokud `data/text/<ID>.txt` neexistuje (sken bez textové vrstvy), přečti
`data/pdf/<ID>.pdf` nástrojem Read a celý dokument přesně přepiš do `data/text/<ID>.txt`
(prostý text, pořadí, odstavce, číslování, všechna čísla a jména; nic neshrnuj).

## 1. Struktura (parse)

1. `uv run usneseni agent-prepare-parse <ID>` vytvoří ve `work/<ID>/`:
   `parse-system.md` (instrukce), `parse-schema.json` (JSON schéma), `numbered.txt` (text
   s čísly řádků).
2. Přečti instrukce a celý `numbered.txt`. Vytvoř `work/<ID>/parse.json` – jeden JSON
   objekt přesně podle schématu (všechna pole povinná, `null` kde schéma dovoluje).
3. `uv run usneseni agent-accept-parse <ID>`. Při `REJECTED` oprav `parse.json` podle
   hlášení a spusť znovu. `[warn]` nevadí, `[error]` ano.

Chyby typu `vote-count-mismatch`, `resolution-missing`, `outcome-contradiction` téměř vždy
znamenají chybu v `parse.json` – vrať se k textu. Jen když chyba je opravdu ve zdrojovém
dokumentu (např. město uvádí počty, které nesedí, nebo číslované usnesení bez hlasování),
vytvoř `data/overrides/<ID>.yaml`:

```yaml
accept: [resolution-no-vote]
note: "ř. 214: usnesení 45/2021 R je v textu bez hlasovacího řádku"
```

a v `note` uveď čísla řádků a co přesně je v dokumentu. Výsledek („přijato“) nikdy
neodvozuj z toho, že návrh má číslo usnesení.

## 2. Popis (enrich)

1. `uv run usneseni agent-prepare-enrich <ID>` vytvoří `enrich-system.md`,
   `enrich-schema.json`, `enrich-input.txt`.
2. Podle instrukcí vytvoř `work/<ID>/enrich.json` (jeden objekt podle schématu, všechna
   usnesení z `enrich-input.txt`).
3. `uv run usneseni agent-accept-enrich <ID>`; při `REJECTED` oprav a opakuj.

## 3. Výsledek

Vrať: ID, zda parse i enrich prošly, výpis z `agent-accept-parse` (stav, počty, warn/error)
a případné poznámky k nesrovnalostem ve zdroji.
