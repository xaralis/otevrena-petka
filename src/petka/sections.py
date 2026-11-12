"""The registry of the portal's sections (the interface is petka.section.Section).

A section with code supplies its own record (`<package>/section.py`); a planned section
without code is only metadata here. Order is the order of the header navigation."""

from .ankety.section import SECTION as ANKETY
from .rozpocet.section import SECTION as ROZPOCET
from .section import Section
from .uredni_deska.section import SECTION as UREDNI_DESKA
from .usneseni.section import SECTION as USNESENI

SMLOUVY = Section(
    "smlouvy", "Smlouvy", "Smlouvy a zakázky",
    "Kdo pro obvod pracuje a za kolik?", "planned",
    examples=["Kdo opravoval chodníky a za kolik?",
              "Které zakázky šly bez soutěže?",
              "S kým má obvod nejvíc smluv?"],
    bridges=[("přímá zadání zakázek", "/usneseni?q=p%C5%99%C3%ADm%C3%A9+zad%C3%A1n%C3%AD"),
             ("výběrová řízení a jejich výsledky", "/usneseni?tema=zakazky")],
    sources=[("Registr smluv", "https://smlouvy.gov.cz/"),
             ("Hlídač státu", "https://www.hlidacstatu.cz/")],
)

REGISTRY: list[Section] = [UREDNI_DESKA, USNESENI, ROZPOCET, SMLOUVY, ANKETY]

SECTIONS = [s for s in REGISTRY if s.listed]    # what the portal's pages show
BY_SLUG = {s.slug: s for s in REGISTRY}

__all__ = ["Section", "REGISTRY", "SECTIONS", "BY_SLUG"]
