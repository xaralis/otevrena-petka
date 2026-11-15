# 0002 – Datové zdroje za celé město, filtr `?obvod=`

Datum: 15. 11. 2026 · Stav: přijato

## Kontext

Některé zdroje pokrývají celé město, ne jen obvod: harmonogram blokového čištění je jedna
tabulka pro všech osm obvodů a databáze ho drží celý (podíl místa v každém obvodu). API
čištění přitom vracelo jen obvod podle domény a export bral jediný obvod, každý po svém.
Stejná otázka přijde u dalších zdrojů (podněty, uzavírky, místa).

## Rozhodnutí

- **Datové zdroje (API, exporty) vracejí výchozí celé město.** Parametr `?obvod=` je zúží na
  vybrané obvody: id oddělená čárkou (`mo5`, `mo4,mo5`), mezery a velikost písmen nevadí,
  prázdný = celé město, neznámé id = chyba 422 se seznamem platných.
- Každý záznam nese pole `obvody`: seřazená id obvodů, kterých se týká. Záznam patří do
  výběru, když leží aspoň v jednom z vybraných obvodů (u geometrie podle podílu, u čištění
  aspoň 5 %).
- Jeden mechanismus pro všechny sekce (`petka.obvody`): registr všech osmi obvodů města
  (`TOWN`, mo1–mo8 s kódem RÚIAN) oddělený od obvodů, které portál obsluhuje (`OBVODY`),
  a závislost FastAPI `ObvodParam`, kterou endpoint deklaruje jedním řádkem a dostane
  `ObvodFilter` (porovnání s `obvody` záznamu, podmínka SQL nad jsonb podílů).
- **Stránky portálu dál ukazují obvod podle domény** (ADR 0001). Když stránka čte vlastní
  API (mapa), posílá svůj obvod v `?obvod=`.

## Důsledky

- `/api/v1/cisteni` a `/verejny-prostor/blokove-cisteni/data/terminy.{json,csv}` jsou za celé
  město s filtrem `?obvod=`. Kdo API volal bez parametru, dostane víc míst; obvod V vrátí
  `?obvod=mo5`.
- MCP nástroje zatím zůstávají u obvodu portálu.
- Další sekce převezmou filtr, až budou mít data za celé město; zdroj jen za jeden obvod ho
  nepotřebuje.
