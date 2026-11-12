# 0001 – Jeden portál pro více obvodů, obvod podle subdomény

Datum: 12. 11. 2026 · Stav: přijato (směr), podrobnosti se dojednávají

## Kontext

Portál vznikl pro MO Pardubice V. Má se z něj stát iniciativa Otevřené Pardubice: moderní
otevřený přístup k informacím pro lidi a zároveň platforma, která ukazuje magistrátu, jak to
jde. Připojit se chce MO IV, podmínky nejsou dojednané.

## Rozhodnutí

- Jedna aplikace a jedno nasazení pro všechny obvody. Obvod se určuje z domény požadavku
  (subdoména, u MO V i stávající otevrenapetka.cz).
- **Obvod je parametr**, ne konfigurace instance: sekce, dotazy, joby a MCP nástroje ho
  dostávají zvenku; nic nového nesmí natvrdo předpokládat `mo5`.
- Teď zavádíme jen seam: registr obvodů s jediným obvodem MO V a jeho určení z domény.
  Datové migrace (obvod u usnesení a desky) a značky dalších obvodů přijdou, až bude dohodnutý
  první další obvod.

## Důsledky

- Rozpočet už obvod v datech má (`unit`), ostatní sekce ho zatím mají implicitně.
- Sdílené části (vzhled, design systém, LLM, geo, hledání) zůstávají společné pro všechny obvody.
