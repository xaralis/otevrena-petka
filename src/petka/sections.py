"""Sections of the portal. A section is live (has its own router) or planned (a page saying
what will be there and where the data comes from)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    slug: str
    title: str
    short: str              # one line for navigation and the home page
    status: str             # live | planned
    question: str           # the question a citizen asks that this section answers
    sources: list = field(default_factory=list)   # (label, url)


SECTIONS = [
    Section("usneseni", "Usnesení a hlasování", "Co rozhodla rada a zastupitelstvo a kdo jak hlasoval",
            "live", "Co se rozhodlo a kdo pro to hlasoval?",
            [("Zápisy z jednání ZMO a RMO na pardubice.eu", "https://pardubice.eu/zapisy-z-jednani-zmo5")]),
    Section("rozpocet", "Rozpočet a hospodaření", "Kolik obvod vybírá, utrácí a za co",
            "planned", "Kolik stojí obvod a kam jdou peníze?",
            [("Monitor státní pokladny (rozpočty územních celků)", "https://monitor.statnipokladna.gov.cz/"),
             ("Rozpočet a závěrečný účet MO Pardubice V", "https://pardubice.eu/obvod5")]),
    Section("smlouvy", "Smlouvy a zakázky", "S kým obvod uzavřel smlouvy a komu zadal zakázky",
            "planned", "Kdo pro obvod pracuje a za kolik?",
            [("Registr smluv", "https://smlouvy.gov.cz/"),
             ("Hlídač státu", "https://www.hlidacstatu.cz/")]),
    Section("uredni-deska", "Úřední deska", "Co úřad právě zveřejňuje",
            "planned", "Co úřad právě vyvěsil?",
            [("Úřední deska MO Pardubice V (JSON, OFN Úřední desky)",
              "https://www.pardubice.eu/export/official-board-json?district_id=5")]),
]

BY_SLUG = {s.slug: s for s in SECTIONS}
