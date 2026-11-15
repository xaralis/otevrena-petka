"""Uzavírky as a section of the portal (see petka.section): closures, road works and accidents
from NDIC (ŘSD), kept for the whole town. Planned in the header until its page is done; the
data job already runs."""

from ..section import Section


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "uzavirky", "Uzavírky", "Uzavírky",
    "Kde se teď nedá projet?", "planned",
    sources=[("Dopravní informace NDIC (ŘSD)", "https://www.dopravniinfo.cz/")],
    commands=_commands,
)
