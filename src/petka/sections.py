"""Sections of the portal. A section is live (has its own router) or planned (a page saying
what it will answer, where to look meanwhile and where the data will come from).

A section is named by the question it answers; `title` is the short name used everywhere
else, `nav` the label in the header."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    slug: str
    nav: str
    title: str
    question: str               # h1 of the section and the line on the home page
    status: str                 # live | planned
    examples: list = field(default_factory=list)   # questions the section answers
    bridges: list = field(default_factory=list)    # (label, url) already answerable elsewhere here
    sources: list = field(default_factory=list)    # (label, url) where the data comes from


SECTIONS = [
    Section("usneseni", "Usnesení", "Usnesení a hlasování",
            "Co se rozhodlo a kdo pro to hlasoval?", "live",
            sources=[("Zápisy z jednání ZMO a RMO na pardubice.eu", "https://pardubice.eu/zapisy-z-jednani-zmo5")]),
    Section("rozpocet", "Rozpočet", "Rozpočet a hospodaření",
            "Kolik stojí obvod a kam jdou peníze?", "planned",
            examples=["Kolik obvod letos utratí za údržbu zeleně?",
                      "Jak se rozpočet změnil během roku?",
                      "Kolik šlo na dotace spolkům?"],
            bridges=[("rozpočtová opatření a změny rozpočtu", "/usneseni?q=rozpo%C4%8Dtov%C3%A9+opat%C5%99en%C3%AD"),
                     ("schválení rozpočtu a závěrečného účtu", "/usneseni?q=z%C3%A1v%C4%9Bre%C4%8Dn%C3%BD+%C3%BA%C4%8Det"),
                     ("dotace z rozpočtu obvodu", "/usneseni?tema=dotace")],
            sources=[("Monitor státní pokladny – rozpočty obcí a jejich částí", "https://monitor.statnipokladna.gov.cz/"),
                     ("Rozpočet a závěrečný účet na webu obvodu", "https://pardubice.eu/obvod5")]),
    Section("smlouvy", "Smlouvy", "Smlouvy a zakázky",
            "Kdo pro obvod pracuje a za kolik?", "planned",
            examples=["Kdo opravoval chodníky a za kolik?",
                      "Které zakázky šly bez soutěže?",
                      "S kým má obvod nejvíc smluv?"],
            bridges=[("přímá zadání zakázek", "/usneseni?q=p%C5%99%C3%ADm%C3%A9+zad%C3%A1n%C3%AD"),
                     ("výběrová řízení a jejich výsledky", "/usneseni?tema=zakazky")],
            sources=[("Registr smluv", "https://smlouvy.gov.cz/"),
                     ("Hlídač státu", "https://www.hlidacstatu.cz/")]),
    Section("uredni-deska", "Úřední deska", "Úřední deska",
            "Co úřad právě vyvěsil?", "planned",
            examples=["Jaké stavby se v obvodu povolují?",
                      "Kdy je další zasedání zastupitelstva?",
                      "Které oznámení se týká mé ulice?"],
            bridges=[("program a zápisy jednání", "/usneseni/jednani")],
            sources=[("Úřední deska MO Pardubice V (JSON podle OFN Úřední desky)",
                      "https://www.pardubice.eu/export/official-board-json?district_id=5")]),
]

BY_SLUG = {s.slug: s for s in SECTIONS}
