# Otevřená data: usnesení a hlasování orgánů obce

Specifikace formátu, ve kterém tento projekt publikuje usnesení a hlasování Zastupitelstva
(ZMO) a Rady (RMO) městského obvodu Pardubice V. Je napsaná tak, aby ji mohl převzít úřad a
publikovat data rovnou ze svého systému, ve stejné struktuře a se stejnými identifikátory.

Verze 1.0 (31. 10. 2026). Strojově čitelná podoba: `datapackage.json`
([Frictionless Data Package](https://datapackage.org/), Table Schema), generovaná z
`src/usneseni/opendata_schema.py`.

## Stav standardizace v ČR

- **Otevřená formální norma (OFN) pro usnesení ani hlasování neexistuje.** Seznam OFN
  ([data.gov.cz/ofn](https://data.gov.cz/ofn/)) obsahuje mj. *Úřední desky*, *Lidé a osoby*,
  *Události*, *Časová specifikace* a *Číselníky*, nic pro jednání orgánů obce. Proto zde
  definujeme vlastní formát a tam, kde to jde, používáme pojmy blízké existujícím OFN.
- **Zákon nepředepisuje strojově čitelnou podobu.** Zákon o obcích (§ 95) požaduje v zápisu
  počet přítomných, schválený program, průběh a výsledek hlasování a přijatá usnesení;
  výsledek hlasování stačí jako součty pro / proti / zdržel se. Jmenovité hlasování je
  dobrovolné.
- **Precedenty:** Hl. m. Praha publikuje
  [Výsledky hlasování ZHMP](https://data.gov.cz/dataset?iri=https%3A%2F%2Fdata.gov.cz%2Fzdroj%2Fdatov%C3%A9-sady%2F00064581%2Faaf8f062015cc627d5f247d6bd6cf9ac)
  jako jednu plochou CSV (číslo usnesení, datum, součty, jméno hlasujícího), Most publikuje
  [hlasování zastupitelstva](https://opendata.mesto-most.cz/content/7f4da75b2cb346298a6011ceda63fef2).
  Jednotná struktura mezi obcemi není.
- **Mezinárodně** se pro parlamenty a zastupitelstva používá model
  [Popolo](https://www.popoloproject.com/) (Person, Organization, Membership, Motion,
  VoteEvent, Vote, Count). Náš formát mu odpovídá (viz mapování níže), takže data jdou snadno
  převést do nástrojů, které Popolo používají.

## Model

```
meetings 1 ── n resolutions 1 ── n votes 1 ── n ballots n ── 1 members
                    │                  (votes bez usnesení: program, protinávrhy, nepřijaté návrhy)
                    └── relations (usnesení A ruší / mění usnesení B)
```

Šest tabulek, každá jako CSV (UTF-8, čárka, hlavička) i JSON. Pole se seznamem hodnot
(`present`, `keywords` …) jsou v CSV oddělena středníkem.

### Identifikátory (stabilní, odvozené z údajů úřadu)

| entita | tvar | příklad |
|---|---|---|
| jednání | `<orgán>-<RRRR-MM-DD>-<číslo jednání>` | `zmo-2025-12-17-20` |
| usnesení | číslo usnesení malými písmeny, `/` a mezera → `-` | `154/2025 Z` → `154-2025-z` |
| hlasování | `<jednání>-<pořadí v zápisu>` | `zmo-2025-12-17-20-7` |
| člen | `jmeno-prijmeni` bez diakritiky | `filip-varecha` |

### Tabulky a pole

Úplný seznam polí s typy je v `datapackage.json`; zde význam.

**meetings** – jednání: `id`, `body` (`zmo`/`rmo`), `term` (volební období `2022-2026`),
`number`, `kind` (`radne`/`mimoradne`/`ustavujici`), `date`, `place`, `source_url`,
`present`/`excused`/`absent` (id členů), `status` (`ok`/`needs_review` – jen pro tento
projekt, úřad ho nepotřebuje).

**resolutions** – usnesení: `uid`, `number`, `meeting_id`, `body`, `date`, `agenda_no`,
`agenda_title`, `text` (doslovné znění), `responsible` (Z:), `deadline` (T:), `verbs`
(rozhodovací slovesa) a **`status`**:

| status | význam |
|---|---|
| `prijato` | usnesení prošlo |
| `neprijato` | **dostalo číslo, ale v hlasování neprošlo** – zápisy MO V to dělají |
| `castecne` | o částech se hlasovalo zvlášť a některé neprošly |
| `neovereno` | ze zápisu nelze výsledek určit (např. chybí hlasovací řádek) |

Pole `title`, `summary`, `keywords`, `topics`, `kind`, `places`, `parcels`,
`organizations`, `amounts` jsou **odvozená** (doplňuje je tento projekt jazykovým modelem
kvůli vyhledávání). Úřad je publikovat nemusí; pokud ano, `topics` a `kind` z číselníku
`config/topics.yaml`.

**votes** – každé hlasování v zápisu, i procedurální a i o návrzích, které číslo nedostaly:
`id`, `meeting_id`, `seq`, `resolution_uid` (prázdné u hlasování bez usnesení), `part`
(část usnesení hlasovaná zvlášť: bod, jedna osoba při volbě), `subject`, `proposer`,
`procedural`, `n_pro`, `n_proti`, `n_zdrzel`, `n_nehlasoval`, `n_present`, `quorum`
(nadpoloviční většina **všech** členů orgánu: ZMO 8 z 15, RMO 3 z 5), `passed`, `outcome`,
`stated_outcome` (co uvádí zápis), `ballots_status`, `raw` (hlasovací řádek doslova).

**ballots** – hlas člena: `vote_id`, `member_id`, `choice`
(`pro`/`proti`/`zdrzel`/`nehlasoval`/`omluven`/`nepritomen`) a **`provenance`**:

| provenance | původ |
|---|---|
| `named` | člen je jmenovitě uveden v zápisu |
| `inferred` | odvozeno: přítomní v okamžiku hlasování minus jmenovaní hlasovali pro zbývající možnost (jen pokud to přesně sedí na součet) |
| `attendance` | nepřítomen / omluven podle prezence |

Kdyby úřad publikoval jmenovité hlasování ze systému, byly by všechny hlasy `named`.

**members** – `id`, `name` (s tituly), `term`, `list` (kandidátní listina podle
[volby.cz](https://volby.cz/opendata/)), `elected` (zvolen / náhradník), `in_rada`.

**relations** – zrušení a změny usnesení: `source_uid` (rušící), `type` (`rusi` = ruší /
revokuje, `meni` = mění / doplňuje), `target_number`, `target_uid` (je-li v datech),
`scope` (`cele`/`cast`), `detail` (které body), **`effective`** (rušící usnesení prošlo –
neúspěšný návrh na revokaci nic neruší).

## Mapování

| tento formát | Popolo | Praha ZHMP (CSV) |
|---|---|---|
| meetings | (Event) | `cislojednani`, `datumjednani`, `volobd` |
| resolutions | Motion (`identifier`, `text`, `result`) | `cislousneseni`, `nazevtisku`, `cislotisku`, `predkladatel` |
| votes | VoteEvent + Count (`yes`/`no`/`abstain`) | `poradi`, `datumcas`, `pocetpro`, `pocetproti`, `pocetzdrzel`, `pritomno`, `nepritomno` |
| ballots | Vote (`voter_id`, `option`) | `osobaJmeno` (řádek na hlasujícího) |
| members | Person + Membership (`organization_id`, `on_behalf_of_id` = kandidátka) | – |
| relations | (Motion `requirement` / vlastní vazba) | – |

## Doporučení pro úřad (ÚMO Pardubice V)

1. **Publikovat jmenovité hlasování** – u každého hlasování všechny členy a jejich volbu
   (`ballots` s `provenance = named`). Odpadne odhadování z prezence a dohledávání příchodů
   a odchodů v textu zápisu.
2. **Publikovat strojově, ne jen PDF** – tabulky `meetings`, `resolutions`, `votes`,
   `ballots`, `members` (a `relations`) jako CSV podle tohoto schématu, ideálně ze stejného
   podkladu, ze kterého vzniká zápis. PDF zůstává úředním dokumentem.
3. **Výsledek u každého hlasování výslovně** („usnesení bylo / nebylo přijato“) a číslo
   usnesení **jen přijatým** usnesením; nepřijaté návrhy evidovat jako hlasování bez čísla.
4. **Rušení a změny vyznačit strukturovaně** – u usnesení, které ruší nebo mění jiné, uvést
   číslo dotčeného usnesení a rozsah (celé / body).
5. **Stabilní identifikátory** podle tabulky výše a **licence CC BY 4.0** (nebo CC0).
6. **Registrace v Národním katalogu otevřených dat** (NKOD, data.gov.cz) s metadaty
   DCAT-AP-CZ – přes lokální katalog obce nebo formulář NKOD; periodicita „nepravidelně“,
   kontaktní bod úřadu.
7. Výhledově **navrhnout OFN** „Jednání a usnesení orgánů obce“ na základě této
   specifikace – formát je obecný pro jakoukoli obec, městskou část či obvod.

## Verzování

Změny polí se zapisují sem a do `version` v `datapackage.json`. Přidání pole je zpětně
kompatibilní; přejmenování či odebrání zvyšuje hlavní verzi.
