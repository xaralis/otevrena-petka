# Rozpočet a hospodaření – rešerše (11. 11. 2026)

Co umí hotová řešení (nepřebíráme je, jde o představu „svatého grálu“) a jaká data pro
MO Pardubice V skutečně existují. Co nešlo ověřit, je označeno „neověřeno“.

## Shrnutí

- **Svatý grál je rozklik až na platby** s dodavatelem a smlouvou, aktualizovaný měsíčně
  z účetního systému (CityVizor). Ostrava to tak má včetně svých 11 obvodů, exportem z GINIS
  – stejného systému, jaký používají Pardubice.
- **Hlavní zdroj je rozklikávací rozpočet GORDIC města**, který obsahuje i obvody (MO V pod
  vnitřním kódem `05274046`), roky 2018–2026, aktuální ke dni (ověřeno 11. 11. 2026). Má
  schváleno / upraveno / skutečnost podle odvětví, paragrafů a položek a **rozpis až na
  jednotlivé faktury** (popis plnění a částka, bez dodavatele a data). Každá sestava jde
  stáhnout jako Excel s celým stromem najednou – viz „Rozklikávací rozpočet GORDIC: jak z něj
  brát data“. Export z GINIS si tedy od MmP vyžadovat nemusíme.
- **MO V nemá vlastní IČO** (sdílí 00274046 s městem). V Monitoru státní pokladny, ve FIN 2-12 M
  ani na Hlídači státu není samostatně.
- **PDF obvodu** na https://pardubice.eu/rozpocet-mo5 (rozpočty, výhledy, rozpočtová opatření,
  závěrečné účty) jsou doplněk: v kapitolách obvodu, bez kódů rozpočtové skladby, ale s roky
  před 2018 a s texty, které GORDIC nemá (výhled, odůvodnění opatření).
- **Dodavatelé** v GORDIC chybí; doplnit je jde z registru smluv (datová schránka obvodu)
  párováním podle popisu a částky, nebo požádat MmP o přidání dodavatele do sestavy.

## Hotová řešení

### Česko

**CityVizor** – https://cityvizor.cz, repo https://github.com/otevrenamesta/cityvizor (AGPL),
Otevřená města; Praha má vlastní instanci.
- Rozklikávací rozpočet odvětvově i druhově, u řádku schváleno / upraveno / skutečnost, roky
  od 2012, rozklik na jednotlivé platby (datum, částka, účel, dodavatel s IČO), vazba na
  registr smluv a úřední desku. Veřejné API (`/api/public/profiles/{id}/payments`).
- Data z účetního systému; pro GINIS exportní modul ODT (GORDIC, od 2020).
- Živý: 26 profilů s daty 2026, „Ostrava a její městské obvody“ (11 obvodů) – precedens pro
  statutární město.
- Slabina: závislost na exportu. Praha 5 rok a půl bez dat kvůli závadě modulu ODT
  (interpelace 20. 5. 2026), Mariánské Lázně zamrzlé v roce 2022.

**Plzeň, klikací rozpočet** – https://rozpocetmesta.plzen.eu
- Grafický přehled, rozklik, výběr organizace (MMP, obvody) a roku; schváleno / upraveno /
  skutečnost / % plnění.
- **Detail každé investiční akce** (a neinvestiční nad 10 mil. Kč) s fází projektu (PRP, DÚR,
  DSP, RLZ) a odkazem na registr smluv. Nejlepší český vzor pro investice. Má slovník pojmů.

**Pardubice, rozklikávací rozpočet GORDIC** – https://rozpocet.pardubice.eu/gordic/Rozpocet/,
investiční mapa https://rozpocet.pardubice.eu/gordic/Imapa/
- Sestavy GORDIC (SQL Server Reporting Services nad GINIS) v iframe, roky 2018–2026, technicky
  zastaralé (jQuery, iframe, na mobilu špatně). Obsahuje magistrát i všechny obvody I–VIII.
- Z webu města na něj odkaz nevede; u plnění město odkazuje na Monitor
  (https://pardubice.eu/rozpocet-mesta). Podrobně níž.

**Monitor státní pokladny** – https://monitor.statnipokladna.gov.cz
- Profil účetní jednotky: rozklik příjmů a výdajů, rozvaha, výsledovka, ukazatele monitoringu
  (likvidita, podíl cizích zdrojů), kalkulačka pravidla dluhu (60 % průměru příjmů za 4 roky).
- Otevřená data FIN 2-12 M měsíčně (CSV, RSS `/api/opendata/rss`), od 1. 1. 2026 v nové
  struktuře (vyhl. 228/2025 Sb.). Žebříčky obcí MF nesestavuje.
- Pro MO V jen kontext za celé město (viz níž).

**Hlídač státu** – https://www.hlidacstatu.cz/subjekt/00274046
- Smlouvy, zakázky, dotace, dodavatelé, K-Index a rizikové příznaky. Rozpočet ne. Hodí se na
  žebříček dodavatelů a odkazy na smlouvy.

**rozpocetobce.cz** – mrtvé (přesměrování na kupnisila.cz, chyba 500).

Brno publikuje plnění čtvrtletně v PDF; vlastní nástroje Liberce, Děčína, Chrudimi neověřeny.
Aktuální kritéria TI ČR pro rozpočty neověřena; slovenská TIS („Otvorená samospráva“) chce
návrh rozpočtu se slovním komentářem, rozpočty aspoň 3 let zpět, smlouvy, objednávky a faktury.

### Zahraničí

- **Where Does My Money Go? / OpenSpending** (OKF, UK) – průkopníci „daňové účtenky“
  (kolik z mých daní jde kam). Mrtvé, repo archivované.
- **OpenBudgets.eu** (H2020, 2015–2017) – nahrání a srovnání rozpočtů ve Fiscal Data Package.
  Po skončení grantu jen pozůstatek.
- **Open Budget Oakland** – https://openbudgetoakland.org, dobrovolnický, živý od 2013. Grafy
  podle oddělení a zdrojů, API a hlavně „Budget Basics“: jak rozpočet vzniká a kdy se dá
  zapojit. Přežil díky vysvětlení procesu, ne díky grafům.
- **ClearGov / OpenGov** (komerční, USA) – srovnání na obyvatele s automaticky vybranou
  skupinou 10 podobných obcí, komentáře k číslům, digitální „budget book“.
- **Bratislava** – smlouvy, faktury a objednávky jako vyhledávatelná data; interaktivní
  rozpočet z roku 2017 dnes nejasný (neověřeno).
- **Taiwan (READr, g0v)** – vizualizace škrtů a podmínek v rozpočtu; inspirace pro
  rozpočtová opatření jako časovou osu.
- **Keňa (PesaYetu)** – rozpočty okresů propojené s daty ze sčítání.
- **IBP Citizens Budget** – zjednodušená verze rozpočtu pro veřejnost; Open Budget Survey ji
  počítá mezi 8 klíčových dokumentů spolu s průběžnými zprávami během roku.

## Rozklikávací rozpočet GORDIC: jak z něj brát data

Ověřeno 11. 11. 2026.

- **Obvody** mají vnitřní kódy odvozené od IČO města: magistrát `00274046`, MO I `01274046` …
  **MO V `05274046`** … MO VIII `08274046`. Stránka obvodu:
  `https://rozpocet.pardubice.eu/gordic/Rozpocet/index_MC.html?Ico=05274046`.
- **Sestava** je přímo adresovatelná:
  `default.aspx?report=/Gordic/S00B/UCR/ROZ/<SESTAVA>&Ico=05274046&Rok=<RRRR>&nazO=…&nazU=`.
- **Export**: po načtení sestavy v prohlížeči je v HTML `ExportUrlBase` (SSRS ReportViewer);
  s `Format=EXCELOPENXML` vrátí xlsx s celým rozbaleným stromem. CSV a XML server odmítá (404).
  Export funguje jen v rámci relace, která sestavu vykreslila (stačí headless Chrome
  + Playwright, pak stažení stejnou relací). Sestava v HTML se rozbaluje přes
  `InvokeReportAction('Toggle', …)`, proto web „nejde dál“ než přehled, dokud se neklikne
  na řádek.
- **Rok 2018** má „Stav ke dni 14. 3. 2019“ (uzavřený rok), 2026 je aktuální ke dni.

| sestava | obsah | ověřeno pro MO V 2026 |
|---|---|---|
| `RROZROZK0001_Va` (`&Odpa=(1=1)`) | výdaje podle odvětví: schváleno, upraveno, skutečnost, % | ano: 100 169,71 / 115 757,55 / 55 187,20 tis. Kč |
| `RROZROZK0001_Pa`, `RROZROZK0002` (`&Odpa=NN`), `RROZROZK0003` (`&Pol=NN`) | příjmy, rozpad odvětví na paragrafy, třídy položek | ne |
| `RROZROZK0018` | faktury podle položky (položka → popis faktury, profinancováno) | ano |
| `RROZROZK0019` | faktury podle skupin a paragrafů (skupina → paragraf → položka → faktura) | ano, 605 řádků; 2018: 741 |
| `RROZROZK0025` | významné akce nad 10 mil. Kč | ano, jen souhrnná „Akce – výdaje MO V 2026“ |
| `RROZROZK0005`, `0006` | významné příjmy, výdaje | ne |
| `RROZROZK0007`, `0008`, `0009` | vývoj výdajů, příjmů, obojího v letech | ne |
| `RROZROZK0010` | zdroje financování výdajů | ne |
| `RROZROZK0020` (`&RokR=`) | ukazatel dluhové služby | ne |
| `RROZROZK0021`, `0022` | poskytnuté příspěvky na provoz, investiční | ne |
| `RROZROZK0023`, `0032` | rekapitulace, kapitoly rozpočtu | ne |

Co v datech není: dodavatel, datum faktury, číslo dokladu, vazba na smlouvu, ORG akce.
Popisy faktur jsou ruční texty úřadu (překlepy, různé zápisy téže akce), pro seskupení podle
akcí bude potřeba normalizace.

## Data pro MO V

| zdroj | co obsahuje | formát | použitelnost |
|---|---|---|---|
| rozklikávací rozpočet GORDIC | 2018–2026, odvětví, paragrafy, položky, faktury s popisem, aktuální ke dni | xlsx export ze SSRS | **hlavní zdroj** |
| https://pardubice.eu/rozpocet-mo5 | schválené rozpočty (2022, 2025, 2026; 2023–2024 jen návrhy?), starší roky 2003–2021 (chybí 2017–2018), výhledy 2021–2029, rozpočtová opatření od 2022 (ZMO i RMO), závěrečné účty 2021, 2023–2025 | PDF s textem, starší ZIP | hlavní zdroj; parsovat `pdftotext -layout` |
| přílohy ZÚ | zpráva o přezkoumání, účetní závěrka | sken (závěrka bez OCR) | jen odkaz, případně OCR |
| rozpočet města 2026, str. 126 | „Finanční toky do rozpočtů MO“: MO V podíl na daních 25 276,5, transfer ŽP 23 503,5, doprava 12 432,8, celkem 61 212,8 tis. Kč (zpět TKO 8 026,0) | PDF s OCR | vysvětlení, odkud obvod bere peníze |
| FIN 2-12 M, IČO 00274046 | jeden výkaz za město včetně obvodů | CSV měsíčně | jen kontext města |
| registr smluv (https://data.smlouvy.gov.cz/) | smlouvy a objednávky obvodu, filtr datovou schránkou `mbbbxhp` (pole IČO prázdné), objednávky `OBJ_UMO5/…` | XML měsíčně | dodavatelé, vazba na akce |
| Hlídač státu | 691 záznamů pro „Městský obvod Pardubice V“, pseudo-IČO 06216234 (neověřeno) | web, API | křížová kontrola |
| úřední deska obvodu | oznámení o zveřejnění rozpočtových dokumentů | JSON (`/export/official-board-json?district_id=5`) | už stahujeme; nové RO lze zachytit odtud |
| „Pětka sobě“ | pravidla, projekty, hlasování (Mobilní rozhlas) | web, PDF | vazba na participativní rozpočet |

Rozpočet MO V 2026: příjmy 70 494,7, financování 25 073,2, výdaje 95 567,9 tis. Kč.

Otevřený datový katalog města s rozpočtem nebo fakturami neexistuje (https://pardubice.eu/open-data
má jen desky, aktuality a volný čas; v NKOD jen úřední deska).

## Úrovně funkcí

S GORDIC je většina „dobrého“ a polovina „svatého grálu“ (faktury, aktuálnost) dosažitelná
bez spolupráce úřadu; chybí jen dodavatelé a vazba na smlouvy.

**Základ** (dá se hned):
1. Roky vedle sebe: schváleno / upraveno / skutečnost a % plnění; příjmy, výdaje, saldo,
   financování; běžné a kapitálové zvlášť.
2. Struktura výdajů (treemap) podle oblastí obvodu lidskými názvy.
3. Časová řada 10+ let, přepočet na obyvatele.
4. „Rozpočet za 2 minuty“: odkud obvod bere peníze (statut, podíl na daních, transfery),
   za co smí utrácet, jak rozpočet vzniká a kdy se dá zapojit.
5. U každého čísla zdrojové PDF a datum; CSV ke stažení.

**Dobrý:**
6. Časová osa rozpočtových opatření s číslem usnesení (vazba na sekci Usnesení – máme ji).
7. Investiční akce s fází a mapou (vzor Plzeň), propojené s usneseními a smlouvami.
8. Výhled proti skutečnosti: drží plán?
9. Srovnání s ostatními obvody Pardubic na obyvatele (jejich PDF jsou na stejném webu).
10. Smlouvy a objednávky obvodu z registru smluv, žebříček dodavatelů.
11. Kontext města z Monitoru (dluh, likvidita) s výslovnou poznámkou, že jde o celé město.

**Svatý grál:**
12. Rozklik až na platby s dodavatelem a smlouvou.
13. Měsíční automatická aktualizace z GINIS (export ODT nebo CSV).
14. Srovnání s obvody jinde (ostravské v CityVizoru, pražské MČ v Monitoru), daňová účtenka.
15. Vazba na participativní rozpočet a plnění koaličních priorit; veřejné API (máme MCP).

## Čeho se vyvarovat

- **Mrtvé exporty**: když data přestanou chodit, musí to být vidět (datum „platné k“ u všeho).
  Praha 5 i Mariánské Lázně ukazovaly stará čísla bez varování.
- **Kódy bez výkladu**: paragraf 3745 nikomu nic neřekne. Lidské názvy a slovník pojmů.
- **Smrt závislá na grantu nebo jednom člověku** (WDMMG, OpenSpending, rozpocetobce.cz):
  udržovat jednoduché, automatické, bez ručního přepisování.
- **Zavádějící srovnání**: dluh města nevydávat za dluh obvodu; obvod pravidlu dluhu
  nepodléhá.
- **Iframe a desktop** (GORDIC): musí fungovat na mobilu.

## České datové základy

- **Rozpočtová skladba** (vyhl. 412/2021 Sb.): paragraf = odvětví (3745 zeleň, 6171 místní
  správa), položka = druh (1xxx–4xxx příjmy, 5xxx běžné a 6xxx kapitálové výdaje, 8xxx
  financování), ÚZ = účelový znak, ORJ/ORG = analytika obce (správce, akce). ORG je klíč
  k investičním akcím.
- **Zákon 250/2000 Sb.**: výhled (§ 3), zveřejnění návrhu 15 dní předem a schváleného
  rozpočtu a RO do 30 dnů (§ 11), závěrečný účet s přezkumem (§ 17). Povinné dokumenty jsou
  minimum, na kterém stavíme.
- **Zákon 23/2017 Sb.** (pravidlo dluhu) platí pro město, ne pro obvod.

## Kapitoly obvodu vs. GORDIC

Zastupitelstvo schvaluje rozpočet v kapitolách obvodu (13 sociální věci, 14 vnitřní správa,
15 životní prostředí, 27 doprava, 33 školství, mládež, tělovýchova a kultura, 34 knihovna,
98 rezervy, konsolidační převody) s pojmenovanými položkami („zpravodaj MO“, „rezerva
starosty“). GORDIC kapitoly nezná; z paragrafů je složit nejde (sedí jen 34 knihovna, § 3314).
Sestava RROZROZK0032 třídí podle ORJ: „Kancelář úřadu“ = kapitola 14 do koruny (33 739 tis. Kč
schváleno 2026), řádek bez názvu = ostatní kapitoly dohromady. Převodník je rozpis rozpočtu
podle § 14 z. 250/2000 Sb., který dělá vedoucí odboru ekonomického (usnesení o rozpočtu 2026,
bod 3). Řádek „Úroky z vklad. účtu“ (8 026 tis. Kč) je ve skutečnosti „převod podílu z výběru
MP KO z rozpočtu MO do rozp. města“ (konsolidační převody).

## Otevřené otázky

- Export rozpisu rozpočtu z GINIS (kapitola, položka obvodu, paragraf, položka, ORG) za roky
  2018–2026 – ptá se Filip na ekonomickém odboru. Trvaleji: ORG do veřejné sestavy GORDIC.

- Jak často se GORDIC aktualizuje (denně, týdně)? Sledovat „Stav ke dni“ při pravidelném
  stahování.
- Dá se do sestavy faktur přidat dodavatel (IČO) a datum? Otázka na MmP / GORDIC; jinak
  párování s registrem smluv.
- Snese server pravidelné stahování (headless prohlížeč, xlsx)? Stahovat šetrně, jednou denně.
- Existuje převodník kapitol obvodu (PDF) na paragrafy (GORDIC)? Potřeba pro roky před 2018.
- Schválené rozpočty 2023 a 2024, roky 2017–2018 a ZÚ 2022: chybí na webu, nebo jinde?
