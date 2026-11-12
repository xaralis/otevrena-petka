"""Plain names for the parts of the rozpočtová skladba MO V actually uses.

Oblasti are oddíly (first two digits of the paragraf), účely are paragrafy. The official names
come from the MF codelist (data/rozpocet/ciselnik.json); these are ours, for people. A paragraf
that is not here shows its official name. "odvod" is the share of the local waste fee the
district passes on to the city: GORDIC lists it without a paragraf (as "Úroky z vklad. účtu"),
up to 2022 it sat on § 6330.
"""

ODDIL = {
    "61": ("Chod úřadu a zastupitelstvo", "Státní moc, státní správa, územní samospráva a politické strany"),
    "22": ("Silnice a chodníky", "Doprava"),
    "37": ("Zeleň a odpady", "Ochrana životního prostředí"),
    "34": ("Sport a volný čas", "Sport a zájmová činnost"),
    "64": ("Rezervy", "Ostatní činnosti"),
    "odvod": ("Odvod a převody městu", "konsolidační převody"),
    "33": ("Kultura a zpravodaj", "Kultura, církve a sdělovací prostředky"),
    "36": ("Osvětlení a komunální služby", "Bydlení, komunální služby a územní rozvoj"),
    "31": ("Školy", "Vzdělávání a školské služby"),
    "32": ("Vzdělávání a volný čas", "Vzdělávání a školské služby"),
    "35": ("Zdravotnictví", "Zdravotnictví"),
    "52": ("Krizová připravenost", "Civilní připravenost na krizové stavy"),
    "53": ("Bezpečnost", "Bezpečnost a veřejný pořádek"),
    "55": ("Dobrovolní hasiči", "Požární ochrana a integrovaný záchranný systém"),
    "62": ("Humanitární pomoc", "Jiné veřejné služby a činnosti"),
    "63": ("Finanční operace", "Finanční operace"),
    "23": ("Kanalizace", "Vodní hospodářství"),
}

PARAGRAF = {
    "6171": "Chod úřadu", "6112": "Zastupitelstvo", "6115": "Komunální volby",
    "6114": "Volby do Parlamentu", "6117": "Volby do Evropského parlamentu", "6118": "Volba prezidenta",
    "6173": "Místní referendum",
    "2219": "Chodníky, parkoviště a značení", "2212": "Silnice", "2229": "Ostatní doprava",
    "2221": "Veřejná doprava",
    "3745": "Veřejná zeleň", "3723": "Svoz odpadu a koše", "3729": "Ostatní odpady",
    "3716": "Měření ovzduší",
    "3421": "Volný čas dětí a mládeže, hřiště", "3419": "Podpora sportu", "3412": "Sportoviště",
    "3429": "Ostatní zájmová činnost",
    "6409": "Rezervy rozpočtu, rady, starosty a místostarosty",
    "odvod": "Podíl z místního poplatku za komunální odpad", "6330": "Převody vlastním fondům",
    "3319": "Kulturní akce", "3314": "Knihovna", "3349": "Zpravodaj a média", "3399": "Ostatní kultura",
    "3312": "Koncerty", "3311": "Divadlo", "3313": "Kino",
    "3639": "Služby a rozvoj území", "3631": "Veřejné osvětlení", "3635": "Územní plánování",
    "3699": "Ostatní bydlení a rozvoj",
    "3111": "Mateřské školy", "3113": "Základní školy", "3149": "Ostatní školská zařízení",
    "3233": "Střediska volného času", "3299": "Ostatní vzdělávání",
    "5213": "Krizová opatření", "5311": "Bezpečnost a veřejný pořádek", "5512": "Dobrovolní hasiči",
    "6221": "Humanitární pomoc", "6310": "Bankovní poplatky a úroky", "6399": "Ostatní finanční operace",
    "2321": "Kanalizace",
}

# items of the druhové třídění, for invoices
ITEM_KIND = {"6121": "stavba (investice)", "5169": "služby", "5171": "opravy a údržba",
             "5499": "příspěvek", "5139": "materiál", "5137": "drobný majetek"}


def key(paragraph: str) -> str:
    """The oblast of a paragraf code (or "odvod")."""
    return "odvod" if paragraph in ("odvod", "6330") else paragraph[:2]


def oddil(k: str) -> tuple[str, str]:
    return ODDIL.get(k, (f"Oddíl {k}", f"oddíl {k}"))


# one sentence about a paragraf, for its page (others fall back to the official name)
ABOUT = {
    "3745": "Sečení trávníků, pletí a zálivka záhonů, kácení a ořez stromů.",
    "6171": "Platy a provoz úřadu městského obvodu.",
    "2219": "Chodníky, parkoviště, dopravní značení a jejich údržba.",
    "2212": "Opravy a údržba místních silnic.",
    "3421": "Dětská hřiště a akce pro děti a mládež.",
    "3723": "Vysypávání košů a svoz odpadu z veřejných ploch.",
}

# položky (druhové třídění) people meet in the detail of an oblast; others show the official name
POLOZKA = {
    "5011": "Platy zaměstnanců", "5019": "Ostatní platy", "5021": "Dohody a ostatní osobní výdaje",
    "5023": "Odměny zastupitelů", "5031": "Sociální pojištění", "5032": "Zdravotní pojištění",
    "5038": "Pojištění odpovědnosti zaměstnavatele", "5039": "Ostatní povinné pojistné",
    "5132": "Ochranné pomůcky", "5133": "Léky a zdravotnický materiál", "5134": "Pracovní oděvy",
    "5136": "Knihy a tiskoviny", "5137": "Drobný majetek", "5139": "Materiál",
    "5151": "Voda", "5152": "Teplo", "5153": "Plyn", "5154": "Elektřina", "5156": "Pohonné hmoty",
    "5161": "Poštovní služby", "5162": "Telefony a internet", "5163": "Bankovní poplatky",
    "5164": "Nájemné", "5166": "Poradenské a právní služby", "5167": "Školení",
    "5168": "Zpracování dat a IT služby", "5169": "Služby", "5171": "Opravy a údržba",
    "5172": "Software do 80 tisíc Kč", "5173": "Cestovné", "5175": "Pohoštění", "5192": "Náhrady",
    "5194": "Věcné dary", "5123": "Technické zhodnocení do 80 tisíc Kč",
    "5199": "Ostatní výdaje", "5362": "Daně státu",
    "5222": "Příspěvky spolkům", "5229": "Příspěvky neziskovým organizacím",
    "5492": "Dary občanům", "5499": "Příspěvky občanům",
    "6111": "Software", "6121": "Stavby", "6122": "Stroje a zařízení", "6123": "Dopravní prostředky",
}
