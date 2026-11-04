# Úřední deska „pro lidi“ – pilot s lidskou kontrolou

Každé oznámení, které se týká MO Pardubice V, dostane kartu v běžné češtině: co se děje, kde,
kdy, koho se to týká a co s tím můžete udělat do kdy, s obrázkem tam, kde pomůže (výkres nebo
fotka z přílohy, letecký snímek ČÚZK s vyznačeným místem, mapa, značky, graf rozpočtu).
Během pilotu nic nejde ven bez schválení člověkem. Kód: `src/petka/uredni_deska/digest.py`.

## Denní běh (naplánovaná session Claude Code na homelab VM)

```bash
cd ~/Workspace/otevrena-petka && git pull
LLM_BACKEND=claude-cli uv run usneseni deska-drafts      # návrhy pro nová oznámení (max 20)
scripts/deska-sync.sh                                    # koncepty do produkce (náhled)
```

- `deska-drafts` vezme vyvěšená oznámení MO V z veřejného API, sloučí balíčky (směrnice +
  přílohy, změna rozpočtu + tabulky), stáhne přílohy a pro každý balíček bez karty připraví
  koncept do `data/uredni_deska/drafts/<id>/` (není v gitu). Text píše Claude přes
  předplatné (`claude -p`), obrázky vznikají deterministicky.
- Doručení písemností dostanou jednotnou kartu bez jména, bez volání modelu.
- Pak session pošle souhrn: počet návrhů, titulky a co hlásí automatická kontrola, s odkazem
  na náhled **https://opendata.mov.varecha.work/uredni-deska/navrhy** (heslo jako ostatní
  dev stránky). Každý návrh má vlastní ukázku `/uredni-deska/navrhy/<id>` přesně v podobě, jakou uvidí
  lidé, a tlačítko „Kopírovat název“ (id + titulek) pro odpověď v session.

## Posouzení a vydání (v téže session)

Uživatel napíše třeba „1 a 3 vydej, u 2 zkrať shrnutí a přidej mapu, 4 zahoď“. Session:

1. upraví koncepty podle pokynů (přímo `digest.json`, nebo znovu `deska-drafts <id>`),
2. `uv run usneseni deska-publish <id…>` – přesune do `data/uredni_deska/digests/`,
   `uv run usneseni deska-reject <id…>` – zahozené zůstanou jako `rejected`, aby se nenavrhovaly znovu,
3. `scripts/deska-sync.sh` – hned vidět na webu,
4. commit `data/uredni_deska/digests/` (zpráva „deska: <titulky>“) a push – schválené karty
   jsou tak v historii a v dalším image (bootstrap je nahraje).

## Pravidla, která hlídá kontrola i člověk

- Žádné osobní údaje soukromých osob: jména žadatelů a adresátů, SPZ, čísla průkazů ZTP,
  data narození. Kontrola hledá jméno žadatele z textu („Žadatel: … – fyzická osoba“), SPZ
  a zmínky o narození. **Fotky z příloh** zkontrolovat okem (čitelné SPZ, obličeje).
- Data a lhůty doslova z dokumentu. Dopočtené datum (konec lhůty pro připomínky) kontrola
  označí; v poznámce pro kontrolu je vysvětlený výpočet – ověřit.
- Obrázky: jen výkresy/fotky z příloh úřadu, ortofoto ČÚZK (CC BY 4.0, uvedeno u obrázku),
  mapa OpenStreetMap a značky z Wikimedia Commons (`config/uredni_deska/znacky.yaml`).
  Žádné snímky z Mapy.com ani Google Street View (licence to nedovolují) a žádné generované
  obrázky.

## Po pilotu

Až se postup osvědčí, poběží `deska-drafts` v CronJobu `deska` s `LLM_BACKEND=api` a shluky,
kterým věříme (třeba výpadky elektřiny), se vydají rovnou; ostatní dál přes návrhy.
