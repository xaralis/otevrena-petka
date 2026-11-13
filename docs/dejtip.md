# Dej Tip – podněty občanů (13. 11. 2026)

Dej Tip je městská aplikace na hlášení závad a podnětů (mobilní aplikace a formulář na webu).
Veřejná mapa: https://amg.dejtip.eu/pardubice/. Sekce `podnety` z ní přebírá podněty obvodu
(`petka podnety-update`, API `/api/v1/podnety`, MCP nástroj `podnety`).

## Odkud data bereme

Mapa se ptá jednoho endpointu, stejně se ptáme i my:

```
POST https://amg.dejtip.eu/DbConn/handler.aspx/Database
Content-Type: application/json; charset=utf-8

{"json": "{\"db\":{\"app\":\"dejtip\",\"sql\":\"sql\",\"ins\":false,\"upd\":false,\"city\":\"pardubice\",
          \"monthsBack\":\"\",\"yearsBack\":\"\",\"dateFrom\":\"2026-01-01\",\"dateTo\":\"2026-11-12\"}}"}
```

- `json` je řetězec, ve kterém je JSON. Data ISO fungují, `"yearsBack": 2` vrátí dva roky zpět.
- Odpověď `{"d": "<JSON pole řádků jako řetězec>"}`, celé město najednou. Filtr na obvod
  endpoint nemá; obvod poznáme podle `CS_MUNICODE` (kód MOMC v RÚIAN, MO V = 557072,
  v kódu `obvody.Obvod.momc`).
- Dva roky celého města jsou zhruba 1,3 MB. Starší data zdroj má (od ledna 2020 je to dalších
  3 892 podnětů celého města); první běh je přesto nebere, viz „Okno stahování“.
- Číselníky: kategorie https://amg.dejtip.eu/upload/data/c_category.csv
  (`ID, KATEGORIE, TEMA_ID, DESCRIPTION, PICTURE`), stavy
  https://amg.dejtip.eu/upload/data/c_status.csv (`ID, POPIS, ICON`). Název kategorie je
  i v každém řádku, stavy máme v `podnety/source.py`.

Stavy: 1 Evidováno, 2 V řešení, 3 Vyřešeno, 4 Nelze vyřídit, 5 Chybné/nepravdivé,
6 Nepřísluší, 7 Spam, 8 Předáno, 9 Zařazeno do plánu, 99 Smazané. Stavy 5, 7 a 99 nebereme
a podnět, který do nich přejde, mažeme.

## Pozice polí v řádku

Řádek je pole o 23 prvcích. Konfigurace mapy (`model.db.conversionArray` v cfg.json) jmenuje
21 sloupců, ale od pozice 13 nesedí: `NOTE_DATE` vlastní sloupec nemá (datum je uvnitř `NOTE`)
a na konci jsou tři sloupce navíc. Pozice jsme určili z reálné odpovědi (3 602 řádků od
1. 1. 2025, 12. 11. 2026) podle typů a hodnot:

| pozice | pole | co v něm je | bereme |
|---|---|---|---|
| 0 | INCIDENTID | id podnětu (10000101690) | ano, jako `id` |
| 1 | ID | vnitřní id | ne |
| 2 | DEVICEPLATFORM | „Android 14“, „iOS …“, „formular“ | ne |
| 3 | DEVICEVERSION | model telefonu | ne |
| 4 | ACCURACY | přesnost GPS | ne |
| 5 | KAT_TYPE | název kategorie | ano |
| 6 | ADDRESS | „Pardubice, Ulice 123, Pardubice, PSČ, část obce“ | jen ulice |
| 7 | COMMENT01 | popis od občana | ano, telefony a e-maily skryté („[telefon]“, „[e-mail]“) |
| 8 | LAT | zeměpisná šířka | ano |
| 9 | LNG | zeměpisná délka | ano |
| 10 | CS_IMAGEURL | fotka (`http://www.dejtip.eu/_fotoobce/…`) | jen adresu, a jen když `PHOTOISPUBLIC` = 1; ukládáme jako https |
| 11 | CS_ADMINURL | fotka v administraci | **nikdy** |
| 12 | NOTE | „datum¦e-mail úředníka¦text“ – poznámky úřadu | jen datum první a poslední poznámky |
| 13 | CATEGORYID | id kategorie | ano |
| 14 | DISTANCETOADDRESS | vzdálenost bodu od adresy (m) | ne |
| 15 | TEMAID | téma (vždy 1) | ne |
| 16 | PHOTOISPUBLIC | 0/1, autor fotku zveřejnil | čteme, neukládáme |
| 17 | STATUS | stav 1–9, 99 | ano |
| 18 | TIP_DATE | „dd.mm.rrrr HH:MM“ | ano |
| 19 | CS_MUNICODE | kód obvodu (MOMC) | ano |
| 20 | – | vždy null | ne |
| 21 | – | login úředníka, který podnět vyřizuje | **nikdy** |
| 22 | – | vždy null | ne |

`source.parse` kontroluje délku řádku a typy klíčových pozic; když zdroj sloupce posune, job
spadne, místo aby do ulice zapsal třeba popis od občana.

## Co ukládáme a proč ne víc

Tabulka `citizen_reports`: id, kategorie (id a název), stav, datum nahlášení, souřadnice,
ulice bez čísla domu, obvod (náš id a `CS_MUNICODE`), data první a poslední poznámky úřadu,
popis od občana se skrytými kontakty (`description`), adresa veřejné fotky (`photo_url`) a kdy
jsme podnět poprvé a naposledy viděli a kdy se mu změnil stav. `citizen_report_statuses` drží každý stav s datem, kdy jsme ho
uviděli (první řádek je `initial`: podnět ho už měl, datum je jen horní mez); z toho půjde
spočítat dobu vyřízení.

Popis a fotka (rozhodnutí starosty 13. 11. 2026):

- **Popis od občana** (`COMMENT01`) ukazujeme v bublině podnětu na mapě a vydáváme v API, protože
  bez něj z kategorie a ulice nepoznáte, o co jde. Mapa Dej Tipu ho ukazuje taky. Lidé ale
  píšou volně, a tak telefonní čísla (devět číslic po trojicích či bez mezer, i s +420) a
  e-mailové adresy nahrazujeme „[telefon]“ a „[e-mail]“ už při stahování (`source.mask`);
  původní text neukládáme. Data („12. 11. 2026“) a čísla popisná („2517-2521“) zůstávají.
  Jméno v textu takhle skrýt nejde; kdo ho napíše do veřejné aplikace, zveřejní ho i tam.
- **Fotka** (`CS_IMAGEURL`) jen tam, kde ji autor na Dej Tipu označil jako veřejnou
  (`PHOTOISPUBLIC` = 1); jinak adresu vůbec neuložíme. Fotku nekopírujeme, stránka ji načítá
  přímo z Dej Tipu (https://www.dejtip.eu/_fotoobce/…, https funguje, ověřeno 13. 11. 2026).

Proč ne zbytek:

- **Poznámky úřadu** (`NOTE`) obsahují e-mail úředníka, **login** (pozice 21) jméno úředníka.
  Bereme jen data první a poslední poznámky; text necháváme na Dej Tipu, odkaz vede na podnět.
- **Číslo domu, PSČ, část obce**: podnět u domu prozrazuje, kdo bydlí kde; ulice na mapu
  a hledání stačí. Adresa, která není ulice (jen číslo popisné), zůstane bez ulice.
- **Odkaz do administrace** (`CS_ADMINURL`), **neveřejné fotky**, **zařízení a přesnost GPS**:
  nic z toho portál nepotřebuje.

## Okno stahování

První běh obvodu bere dva roky zpět, další běhy posledních 120 dní: v tom okně podněty ještě
mění stav. Starší změnu i starší historii (zdroj má podněty od roku 2020) zachytí ruční
`petka podnety-update --od RRRR-MM-DD`. Podnět, který ze zdroje úplně zmizí, u nás zůstane
(poznat podle `last_seen`).

## Odkaz na jeden podnět

`https://amg.dejtip.eu/pardubice/?id=<INCIDENTID>` otevře mapu Dej Tipu na konkrétním podnětu
(ověřeno 13. 11. 2026; skript mapy `app.min.js` stejný odkaz nabízí zkopírovat). Každý záznam
v API ho má v `detail` (`source.detail`), stránka podnětů na něj odkazuje z bubliny i seznamu.

## Pro vlastní formulář: jak Dej Tip přijímá nové podněty

Z obfuskovaného skriptu formuláře https://amg.dejtip.eu/app/dejtip.form.min.js (žádný
podnět jsme neodeslali, nic z toho není ověřené):

- Adresa z konfigurace mapy: `dejtip.tipPostUrl = http://www.dejtip.eu`,
  `dejtip.tipPostUrlS = https://www.dejtip.eu`.
- Odeslání: `POST {tipPostUrl}/dejtippro/v3/newincident?…` s parametry v query stringu:
  `categoryId`, `categoryType` (název kategorie), `latitude`, `longitude`, `accuracy`,
  `altitudeAccuracy`, `heading`, `speed`, `comment`, `creationTime`, `devicePlatform`,
  `deviceVersion`, `photoIsPublic`, `isimgattached` (`false` bez fotky). Tělo je fotka jako
  `binary/octet-stream` (skript ji předtím zmenšuje knihovnou `libs/js/compress.js`).
- Formulář má ověřovací kód: `../Captcha/captcha.aspx/Captcha` (a varianta `captcha.php`),
  pole `#tip-captcha`. Kontakt na oznamovatele (e-mail) ve formuláři nevidíme.
- Kategorie formulář čte z `c_category.csv` (výše); `temaId` je 1.

Vlastní formulář by tedy potřeboval dohodu s provozovatelem (AMG) nebo městem: captcha je
tam právě proto, aby podněty neposílal nikdo jiný než člověk na jejich stránce.
