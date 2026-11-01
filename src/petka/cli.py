"""Command line of the portal (`usneseni <command>`, also installed as `petka`).

Úřední deska commands are handled here; everything else goes to the usnesení CLI
(petka.usneseni.cli). `bootstrap` (the web pod's init container) also refreshes the boards,
best effort, so a fresh deploy shows current notices.
"""

import json
import logging
import sys

from .usneseni import cli as usneseni_cli

DESKA_HELP = "  deska-update        download the úřední deska boards and update the notices (idempotent)"


def deska_update() -> int:
    from .uredni_deska import jobs
    report = jobs.update()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["failures"] else 0


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "deska-update":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        sys.exit(deska_update())
    if cmd in ("-h", "--help", ""):
        print("section úřední deska:\n" + DESKA_HELP + "\n")
    usneseni_cli.main()
    if cmd == "bootstrap":
        try:
            deska_update()
        except Exception:
            logging.getLogger(__name__).exception("bootstrap: úřední deska not refreshed")


if __name__ == "__main__":
    main()
