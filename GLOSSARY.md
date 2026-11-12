# Slovník

Doménové pojmy portálu. Kód, testy a návrhy používají tyhle názvy.

- **Obvod** – městský obvod Pardubic (MO I–VIII), pro který portál ukazuje data. Dnes jen
  MO Pardubice V (`mo5`), portál se má rozšířit na další (ADR 0001). V kódu `obvod`; v datech
  rozpočtu sloupec `unit` (`mo5`, `mmp` = magistrát).
- **Iniciativa Otevřené Pardubice** – zastřešující projekt: portál otevřených dat obvodů
  (tento repozitář, značka obvodu např. „Otevřená Pětka“) a městská aplikace
  (repozitář otevrene-pardubice).
- **Sekce** – samostatná část portálu odpovídající na jednu otázku (Usnesení, Úřední deska,
  Rozpočet, Smlouvy, Ankety). Má stav `live` / `planned`.
- **Usnesení** – rozhodnutí zastupitelstva (ZMO) nebo rady (RMO) obvodu; nepřijatý návrh
  s číslem usnesením není.
- **Oznámení** – položka úřední desky (deska obvodu nebo magistrátu).
- **Karta** – srozumitelné převyprávění oznámení („pro lidi“), psané LLM a kontrolované
  druhým modelem. Stavy: draft → published / rejected. Semafor kvality: spolehlivé,
  buďte obezřetní, nespolehlivé.
- **Rozklikávací rozpočet** – sestavy GORDIC nad účetnictvím města (GINIS), náš zdroj rozpočtu.
- **Oblast** – oddíl rozpočtové skladby (první dvě číslice paragrafu), s lidským názvem.
- **Účel** – paragraf rozpočtové skladby, s lidským názvem.
- **Položka** – druhové třídění výdaje (5169 služby, 6121 stavby…).
- **Kapitola** – vlastní třídění rozpočtu obvodu v materiálech pro zastupitelstvo; portál ho
  nepoužívá (nelze ho složit z paragrafů).
- **Plán** – upravený rozpočet (schválený i se všemi změnami během roku).
- **Utraceno** – skutečnost; u běžícího roku „utraceno zatím“.
- **Odvod** – převod podílu z místního poplatku za komunální odpad městu (v GORDIC bez
  paragrafu, chybně jako „Úroky z vklad. účtu“).
