"""Commands of the Odpady section (`petka odpady-…`)."""

import json

from ..section import Command


def update(a) -> int:
    """Read SmP's list of the separační dvory (its link changes with each version) into
    DATA_DIR/odpady/dvory.json when it changed; the page and the API read that."""
    import datetime as dt
    import os
    import re
    from pathlib import Path

    import httpx

    from . import dvory
    out = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[3] / "data")) / "odpady" / "dvory.json"
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "otevrena-petka"}) as c:
        page = c.get(dvory.PAGE)
        page.raise_for_status()
        m = dvory.LINK.search(page.text)
        if not m:
            raise SystemExit("odpady: the list's link is not on the page")
        f = m.group(1)
        r = c.get("https://smp-pce.cz" + f)
        r.raise_for_status()
    ys = dvory.parse(dvory.doc_text(r.content))
    new = {"file": f.rsplit("/", 1)[1], "checked": dt.date.today().isoformat(), "yards": dvory.as_json(ys)}
    old = json.loads(out.read_text()) if out.exists() else {}
    changed = old.get("yards") != new["yards"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(new, ensure_ascii=False, indent=1))
    print(json.dumps({"yards": len(ys), "file": new["file"], "changed": changed}, ensure_ascii=False))
    return 0


COMMANDS = [
    Command("odpady-update", "read the separační dvory and their hours from Služby města Pardubic (daily)", update),
]
