"""The data directory – the source of truth. The database is rebuilt from it.

    data/sources.json               index of published PDFs (+ sha256 once downloaded)
    data/text/<id>.txt              text of the PDF (pdftotext -layout, or a transcription)
    data/extracted/<id>.parse.json  parse output for that text  {version, text_sha256, result}
    data/extracted/<id>.enrich.json enrichment                  {version, text_sha256, result}
    data/overrides/<id>.yaml        reviewed exceptions: {accept: [issue codes], note: ...}

In git for the history; in the cluster DATA_DIR is a volume seeded from the image copy.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
SEED = ROOT / "data"


def sources() -> list[dict]:
    p = DATA / "sources.json"
    return json.loads(p.read_text()) if p.exists() else []


def save_sources(docs: list[dict]) -> None:
    _write(DATA / "sources.json", json.dumps(docs, ensure_ascii=False, indent=1) + "\n")


def text_path(mid: str) -> Path:
    return DATA / "text" / f"{mid}.txt"


def text(mid: str) -> str:
    return text_path(mid).read_text()


def text_sha(mid: str) -> str:
    return hashlib.sha256(text(mid).encode()).hexdigest()


def extracted(mid: str, stage: str) -> dict | None:
    """Stored result of `stage` (parse | enrich) if it was made from the current text."""
    p = DATA / "extracted" / f"{mid}.{stage}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return d if d.get("text_sha256") == text_sha(mid) else None


def save_extracted(mid: str, stage: str, version: str, result: dict, via: str) -> None:
    d = {"version": version, "text_sha256": text_sha(mid), "via": via, "result": result}
    _write(DATA / "extracted" / f"{mid}.{stage}.json",
           json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def override(mid: str) -> dict:
    p = DATA / "overrides" / f"{mid}.yaml"
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def seed() -> set[str]:
    """Bring the image's data/ into DATA_DIR; returns ids of meetings whose files changed.

    Files in git (the image) win: they are the reviewed version. Files only on the volume –
    meetings the cron job processed since the last snapshot into git – are left alone.
    sources.json is merged by URL so the volume keeps documents the image doesn't know.
    """
    changed: set[str] = set()
    if DATA.resolve() == SEED.resolve() or not SEED.exists():
        return changed
    for src in SEED.rglob("*"):
        if not src.is_file() or src.name == "sources.json":
            continue
        dst = DATA / src.relative_to(SEED)
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed.add(src.name.split(".")[0])
    seed_sources = json.loads((SEED / "sources.json").read_text())
    merged = {d["url"]: d for d in sources()}
    for d in seed_sources:
        merged[d["url"]] = {**merged.get(d["url"], {}), **d}
    save_sources(list(merged.values()))
    return changed


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(p)
