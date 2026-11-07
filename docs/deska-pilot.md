# Úřední deska „pro lidi“ – autonomní karty se semaforem

Každé oznámení, které se týká MO Pardubice V, dostane kartu v běžné češtině: co se děje, kde,
kdy, koho se to týká a co s tím můžete udělat do kdy, s obrázkem tam, kde pomůže (výkres nebo
fotka z přílohy, letecký snímek ČÚZK s vyznačeným místem, mapa, značky, graf rozpočtu). Karta jde
ven bez člověka, pokud obstojí v kontrole. Kód: `src/petka/uredni_deska/digest.py` a `score.py`.

## Denní běh (naplánovaná session Claude Code na homelab VM)

```bash
cd ~/Workspace/otevrena-petka && git pull --rebase --autostash
LLM_BACKEND=claude-cli uv run usneseni deska-auto     # napsat, ohodnotit, vydat, nebo nechat čekat
scripts/deska-sync.sh                                 # hned vidět na webu
git add data/uredni_deska/digests && git commit -m "deska: <titulky>" && git push
```

Session pak napíše jen to, co potřebuje člověka: karty ve stavu `ceka` a chyby. Když se všechno
vydalo, stačí jedna věta.

## Semafor

Kartu po napsání přečte druhý, nezávislý běh modelu a porovná ji s originály i s obrázky z karty.
Známkuje 0–5 přesnost, úplnost, srozumitelnost a obrázky podle předem popsaných stupňů. Kód z toho
udělá jeden ze tří stavů (`score.py`):

| stav | kdy | co se stane |
|---|---|---|
| Spolehlivé | nic z níže uvedeného | karta vyjde sama |
| Buďte obezřetní | úplnost do 3, srozumitelnost nebo obrázky do 2 | čeká na člověka, důvod je u ní |
| Něco je špatně | přesnost pod 4; některý jiný rozměr do 1; osobní údaje v textu nebo na obrázku; špatné datum; neověřená lhůta; zavádějící tvrzení; obrázek jiného místa; oznámení mimo obvod; pokyny pro model v dokumentu | čeká na člověka |

Když karta není zelená a jde to napravit, model ji přepíše podle výtek a znovu se ohodnotí, karta se
napíše nejvýš třikrát (`MAX_ATTEMPTS`) a výtky se sčítají. Kontrola není úplně stálá, proto přepsaná karta
musí projít dvěma samostatnými čteními po sobě, aby neprošla náhodou. Pak buď vyjde, nebo čeká na **https://otevrenapetka.cz/uredni-deska/navrhy** i s důvodem. Doručení
písemností jsou pevná šablona bez modelu, takže semafor nemají.

Semafor je na webu u každé karty. Po najetí nebo klepnutí bublina vysvětlí, že text přepsala a zkontrolovala AI, a ukáže výsledek po rozměrech. Pod kartou je věta, jestli
ji pustil člověk, nebo jen kontrola. Když kartu schválí člověk, semafor je zelený. Staré karty ohodnotí
`uv run usneseni deska-score`; ty prošly člověkem, takže se u nich nic jiného nezmění a červený stav
se u nich na webu neukazuje, jen ho dostane redaktor ve výpisu. `deska-improve` je přepíše podle výtek: zelený
přepis kartu nahradí, jinak vydaná karta zůstane beze změny.

Doplňující poznámky:

- `deska-auto` vezme vyvěšená oznámení MO V z veřejného API, sloučí balíčky (směrnice + přílohy,
  změna rozpočtu + tabulky) a stáhne přílohy. Hotové obrázky vznikají deterministicky.
- Kartu dostane každé oznámení, které na desce visí. Co už proběhlo, karta popíše v minulém čase;
  dlouhodobě vyvěšené dokumenty (rozpočet, závěrečný účet, směrnice) podle obsahu.

## Obrázky u úprav provozu

- **Fotka z ulice**: nejbližší 360° snímek z Panoramaxu do 40 m (CC BY-SA, autor uveden). Claude
  vybere ze tří pohledů ten, na kterém místo opravdu odpovídá výkresu, a určí, kde stojí rušené
  značky a kam patří nové. Když si není jistý (nízká shoda), fotka „po změně“ nevznikne. Do fotky
  se značky jen kreslí (rušené přeškrtnuté, nové v panelu se šipkou ke sloupu), nic se negeneruje.
  V náhledu je u fotky zdůvodnění – ověřit, že sedí s výkresem.
- **Schéma stání** jen tam, kde výkres řadu stání opravdu ukazuje a dají se spočítat; Claude uvádí,
  podle čeho počty určil, a bez výkresu se schéma nikdy nekreslí. V náhledu je hned nad výkresem.
- 3D pohledy ani generované obrázky se nepoužívají.

## Co dělá člověk

Jen karty, které čekají, a případné stížnosti. Uživatel napíše v session třeba „1 vydej, u 2 zkrať
shrnutí, 3 zahoď“. Session:

1. upraví koncepty podle pokynů (přímo `digest.json`, nebo znovu `deska-drafts <id>`),
2. `uv run usneseni deska-publish <id…>`, nebo `deska-reject <id…>`: zahozené zůstanou jako `rejected`
   a znovu se nenavrhují; `deska-reject` u vydané karty ji stáhne z webu,
3. `scripts/deska-sync.sh`, commit `data/uredni_deska/digests/` a push.

## Pravidla, která hlídá kontrola

- Žádné osobní údaje soukromých osob: jména žadatelů a adresátů, SPZ, čísla průkazů ZTP,
  data narození. Kontrola hledá jméno žadatele z textu („Žadatel: … – fyzická osoba“), SPZ
  a zmínky o narození. Fotky z příloh čte druhý běh modelu (čitelné SPZ, obličeje).
- Data a lhůty doslova z dokumentu. Dopočtené datum (konec lhůty pro připomínky) kontrola
  označí a druhý běh modelu výpočet zopakuje.
- Obrázky: jen výkresy/fotky z příloh úřadu, ortofoto ČÚZK (CC BY 4.0, uvedeno u obrázku),
  mapa OpenStreetMap a značky z Wikimedia Commons (`config/uredni_deska/znacky.yaml`).
  Žádné snímky z Mapy.com ani Google Street View (licence to nedovolují) a žádné generované
  obrázky.
