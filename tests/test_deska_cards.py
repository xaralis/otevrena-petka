"""The card store: layout, the moves between states and what each state may show."""

import io
import json
import tarfile

from petka.uredni_deska import cards


def card(nid="mo5-1", **kw):
    return {"notice_id": nid, "members": [], "status": "draft", "cluster": "ostatni", "headline": "H",
            "source": {"title": "T", "url": "u", "board": "mo5", "mo5": True}, **kw}


def store_with_draft(tmp_path, **kw):
    s = cards.CardStore(tmp_path)
    folder = s.write(card(**kw))
    (folder / "foto.jpg").write_bytes(b"jpg")
    return s


def test_layout_stays_drafts_and_digests_by_status(tmp_path):
    s = cards.CardStore(tmp_path)
    assert s.write(card()) == tmp_path / "drafts" / "mo5-1"
    assert s.write(card("mo5-2", status="published")) == tmp_path / "digests" / "mo5-2"
    assert s.write(card("mo5-3", status="rejected")) == tmp_path / "drafts" / "mo5-3"
    assert json.loads((tmp_path / "drafts" / "mo5-1" / "digest.json").read_text())["headline"] == "H"
    assert s.ids() == {"mo5-1", "mo5-2", "mo5-3"}


def test_publish_moves_the_card_with_its_images_and_leaves_no_draft(tmp_path):
    s = store_with_draft(tmp_path)
    assert s.publish("mo5-1", reviewed_by="model")
    assert not s.folder("mo5-1").exists()
    assert s.read("mo5-1", published=True)["status"] == "published"
    assert (s.folder("mo5-1", published=True) / "foto.jpg").exists()
    assert not s.publish("mo5-1")                    # nothing left to publish


def test_published_card_carries_no_working_notes(tmp_path):
    s = store_with_draft(tmp_path, fixes_given=["Oprav datum"],
                         quality={"level": "spolehlive", "issues": [], "fixes": ["Oprav datum"]})
    s.publish("mo5-1", reviewed_by="model")
    d = s.read("mo5-1", published=True)
    assert "fixes_given" not in d and "fixes" not in d["quality"]


def test_published_delivery_keeps_no_title_or_link(tmp_path):
    s = store_with_draft(tmp_path, cluster="doruceni")
    s.publish("mo5-1")
    assert s.read("mo5-1", published=True)["source"]["url"] == ""


def test_draft_images_are_for_reviewers_published_for_everybody(tmp_path):
    s = store_with_draft(tmp_path)
    assert s.asset_path("mo5-1", "foto.jpg", draft=True) and not s.asset_path("mo5-1", "foto.jpg")
    s.publish("mo5-1")
    assert s.asset_path("mo5-1", "foto.jpg") and not s.asset_path("mo5-1", "foto.jpg", draft=True)
    assert not s.asset_path("mo5-1", "../digest.json") and not s.asset_path("../x", "foto.jpg")


def test_rejected_card_is_never_served(tmp_path):
    s = store_with_draft(tmp_path)
    s.publish("mo5-1")
    assert s.reject("mo5-1", note="ne")                  # taken back down
    assert not s.folder("mo5-1", published=True).exists()
    assert s.read("mo5-1")["status"] == "rejected"
    assert not s.asset_path("mo5-1", "foto.jpg") and not s.asset_path("mo5-1", "foto.jpg", draft=True)


class Conn:
    def __init__(self, known):
        self.known, self.rows = known, []

    def execute(self, sql, params=None):
        if sql.startswith("SELECT"):
            return [{"id": k} for k in self.known]
        if sql.startswith("INSERT"):
            self.rows.append(params)
        return []


def test_load_prefers_the_published_card_over_a_stale_draft(tmp_path):
    s = cards.CardStore(tmp_path)
    s.write(card(status="published", headline="Vydaná"))
    s.write(card(headline="Stará"))
    s.write(card("mo5-2"))
    s.write(card("mo5-9"))                               # not on the board (any more)
    conn = Conn({"mo5-1", "mo5-2"})
    assert s.load(conn) == 2
    by = {r[0]: json.loads(r[4]) for r in conn.rows}
    assert by["mo5-1"]["headline"] == "Vydaná" and by["mo5-2"]["status"] == "draft"


def test_receive_swaps_drafts_and_drops_cards_taken_down(tmp_path):
    s = cards.CardStore(tmp_path / "data")
    s.write(card("mo5-1", status="published"))
    s.write(card("mo5-2", status="published"))
    s.write(card("mo5-3"))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, d in (("digests/mo5-1/digest.json", card("mo5-1", status="published", headline="Nová")),
                        ("drafts/mo5-4/digest.json", card("mo5-4"))):
            data = json.dumps(d).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    assert s.receive(buf) == {"drafts": 1, "published_files": 1}
    assert s.read("mo5-1", published=True)["headline"] == "Nová"
    assert s.read("mo5-2", published=True) is None and s.read("mo5-3") is None and s.read("mo5-4")
