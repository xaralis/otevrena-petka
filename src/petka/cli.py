"""Command line of the portal (`usneseni <command>`, also installed as `petka`).

One argparse tree: the portal's own commands (`serve`, `bootstrap`) and the commands each
section supplies (petka.section.Command). `bootstrap` (the web pod's init container) runs
every section's bootstrap hook in the registry's order; a section decides itself whether its
part is best effort.
"""

import argparse
import logging
import sys

from .section import Command
from .sections import REGISTRY


def serve(a) -> None:
    import uvicorn
    # no access log: it would keep visitors' IP addresses next to their searches
    uvicorn.run("petka.web.app:app", host=a.host, port=a.port, proxy_headers=True,
                forwarded_allow_ips="*", access_log=False)


def _serve_args(p) -> None:
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)


def bootstrap(a) -> None:
    for s in REGISTRY:
        if s.bootstrap:
            s.bootstrap()


PORTAL = [
    Command("bootstrap", "init container: seed volume from image, load changes", bootstrap),
    Command("serve", "run the web app, API and MCP server", serve, _serve_args),
]


def commands() -> list[Command]:
    out = []
    for s in REGISTRY:
        if s.commands:
            out += s.commands()
    return out + PORTAL


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="usneseni")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in commands():
        p = sub.add_parser(c.name, help=c.help)
        c.args(p)
        p.set_defaults(run=c.run)
    return ap


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    a = parser().parse_args(argv)
    sys.exit(a.run(a) or 0)


if __name__ == "__main__":
    main()
