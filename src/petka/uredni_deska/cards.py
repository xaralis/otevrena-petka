"""The card store: where plain-language cards live and how they move between states.

A card is a directory `<id>/` with `digest.json` and its images:

    <root>/drafts/<id>/    draft (waiting for the check or a person) or rejected (never shown)
    <root>/digests/<id>/   published (in git, seeded into the cluster)

Where a card lives follows from its status: published cards are in `digests/`, everything else in
`drafts/`. Only `publish` and `reject` move a card between the two; a published card carries no
working notes. `work` is scratch space for a card's attachments (not kept).
"""

import datetime as dt
import json
import os
import re
import shutil
from pathlib import Path

from ..usneseni.store import ROOT
from .jobs import REDACTED_TITLE

DATA = Path(os.environ.get("DATA_DIR", ROOT / "data")) / "uredni_deska"
SEED = ROOT / "data" / "uredni_deska"
WORK = Path(os.environ.get("DESKA_WORK", "/tmp/petka-deska"))
FILE = "digest.json"


def strip_internal(d: dict) -> dict:
    """Working notes for rewrites stay out of what goes on the web and into git: unlike the sentences
    shown to readers, they may quote the document more closely."""
    d.pop("fixes_given", None)
    if d.get("quality"):
        d["quality"].pop("fixes", None)
    return d


def _dump(f: Path, d: dict) -> None:
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str) + "\n")


class CardStore:
    def __init__(self, root: Path = DATA, work: Path = WORK):
        self.root, self.work = Path(root), Path(work)
        self.drafts, self.digests = self.root / "drafts", self.root / "digests"

    # --- one card ---------------------------------------------------------------------------

    def folder(self, nid: str, published: bool = False) -> Path:
        return (self.digests if published else self.drafts) / nid

    def where(self, d: dict) -> Path:
        """The directory a card belongs in, by its status."""
        return self.folder(d["notice_id"], published=d["status"] == "published")

    def read(self, nid: str, published: bool = False) -> dict | None:
        f = self.folder(nid, published) / FILE
        return json.loads(f.read_text()) if f.exists() else None

    def write(self, d: dict) -> Path:
        """Store a card where its status says (images already in that directory stay)."""
        folder = self.where(d)
        folder.mkdir(parents=True, exist_ok=True)
        _dump(folder / FILE, d)
        return folder

    def new_draft(self, nid: str) -> Path:
        """The draft directory to put a new version's images in (`write` adds the card)."""
        folder = self.folder(nid)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def discard_draft(self, nid: str) -> None:
        if self.folder(nid).exists():
            shutil.rmtree(self.folder(nid))

    def scratch(self, nid: str) -> Path:
        """Where a card's attachments are downloaded and handed to the model."""
        d = self.work / nid
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- all cards ---------------------------------------------------------------------------

    def cards(self, published: bool) -> list[dict]:
        root = self.digests if published else self.drafts
        return [json.loads(f.read_text()) for f in sorted(root.glob(f"*/{FILE}"))]

    def ids(self) -> set[str]:
        """Notice ids that have a card in any state – leaders and members."""
        ids = set()
        for d in self.cards(published=False) + self.cards(published=True):
            ids |= {d["notice_id"], *d.get("members", [])}
        return ids

    # --- moves -------------------------------------------------------------------------------

    def publish(self, nid: str, note: str | None = None, reviewed_by: str = "clovek") -> bool:
        """The draft goes out: status published, cleaned of working notes, moved to `digests/`.
        `reviewed_by` says on the card who let it out: a person, or the quality check alone."""
        src, dst = self.folder(nid), self.folder(nid, published=True)
        d = self.read(nid)
        if d is None:
            return False
        if d["cluster"] == "doruceni":
            d["source"] |= {"title": REDACTED_TITLE, "url": ""}
        d.update(status="published", published_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                 review_note=note, reviewed_by=reviewed_by)
        if reviewed_by == "clovek" and d.get("quality", {}).get("level"):
            # a person has read it, and possibly fixed what the check found
            d["quality"].update(level="spolehlive", issues=[], approved_by_person=True)
        strip_internal(d)
        _dump(src / FILE, d)
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return True

    def reject(self, nid: str, note: str | None = None) -> bool:
        """Keep a rejected card (so it isn't proposed again) but never show it publicly; a published
        one is taken back down."""
        if (self.folder(nid, published=True) / FILE).exists():
            self.discard_draft(nid)
            shutil.move(str(self.folder(nid, published=True)), str(self.folder(nid)))
        d = self.read(nid)
        if d is None:
            return False
        d.update(status="rejected", review_note=note)
        _dump(self.folder(nid) / FILE, d)
        return True

    # --- serving -----------------------------------------------------------------------------

    def asset_path(self, nid: str, name: str, draft: bool = False) -> Path | None:
        """An image of a card: published ones for everybody, drafts only for the reviewers'
        preview (and never those of a rejected draft)."""
        if not re.fullmatch(r"[a-z0-9]+-\d+", nid) or not re.fullmatch(r"[a-z0-9_-]+\.(png|jpg|jpeg|svg)", name):
            return None
        folder = self.folder(nid, published=not draft)
        meta, p = folder / FILE, folder / name
        if not (meta.is_file() and p.is_file()):
            return None
        if json.loads(meta.read_text()).get("status") != ("draft" if draft else "published"):
            return None
        return p

    def load(self, conn) -> int:
        """Bring notice_digests in line with the card directories (drafts and published)."""
        rows = self.cards(published=True)
        rows += [d for d in self.cards(published=False)
                 if not self.folder(d["notice_id"], published=True).exists()]   # an approved copy wins over a stale draft
        known = {r["id"] for r in conn.execute("SELECT id FROM notices")}
        conn.execute("DELETE FROM notice_digests")
        n = 0
        for d in rows:
            if d["notice_id"] not in known:
                continue
            conn.execute(
                """INSERT INTO notice_digests (notice_id, members, status, cluster, data, prompt_version,
                     created_at, published_at, review_note)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (d["notice_id"], [m for m in d.get("members", []) if m in known], d["status"], d["cluster"],
                 json.dumps(d, ensure_ascii=False, default=str), d.get("prompt_version"), d.get("created_at"),
                 d.get("published_at"), d.get("review_note")))
            n += 1
        return n

    # --- sync --------------------------------------------------------------------------------

    def seed(self, source: Path = SEED) -> None:
        """Published cards from the image (git) into the store – they are the reviewed version."""
        if self.root.resolve() == source.resolve() or not (source / "digests").exists():
            return
        for src in (source / "digests").rglob("*"):
            if src.is_file():
                dst = self.digests / src.relative_to(source / "digests")
                if not dst.exists() or dst.read_bytes() != src.read_bytes():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

    def receive(self, stream) -> dict:
        """Replace the cards with a tar of `drafts/` and `digests/` (from scripts/deska-sync.sh):
        drafts are swapped wholesale (approved or dropped ones disappear), approved cards are updated
        and those taken back down (`deska-reject` on a published card) are removed."""
        import tarfile
        import tempfile
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".incoming-") as tmp:
            with tarfile.open(fileobj=stream, mode="r|") as tar:
                tar.extractall(tmp, filter="data")       # no absolute paths, links or devices
            new = Path(tmp)
            if (new / "drafts").is_dir():
                old = self.root / ".drafts-old"
                if old.exists():
                    shutil.rmtree(old)
                if self.drafts.exists():
                    self.drafts.rename(old)
                (new / "drafts").rename(self.drafts)
                if old.exists():
                    shutil.rmtree(old)
            n = 0
            if (new / "digests").is_dir() and self.digests.is_dir():
                # the tar holds every approved card; one missing from it was taken back down
                keep = {d.name for d in (new / "digests").iterdir()}
                for d in self.digests.iterdir():
                    if d.is_dir() and d.name not in keep:
                        shutil.rmtree(d)
            for src in (new / "digests").glob("*/*") if (new / "digests").is_dir() else []:
                dst = self.digests / src.relative_to(new / "digests")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                n += 1
        return {"drafts": len(list(self.drafts.glob(f"*/{FILE}"))), "published_files": n}
