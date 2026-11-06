"""Indicative polls: API under /api/v1/ankety. One vote per anonymous app install."""

import hashlib
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

api = APIRouter(prefix="/api/v1/ankety", tags=["ankety"])

VOTER = re.compile(r"^[0-9a-fA-F-]{16,64}$")


def _hash(voter: str) -> str:
    return hashlib.sha256(voter.lower().encode()).hexdigest()


def _polls(voter: str | None, poll_id: str | None = None) -> list[dict]:
    me = _hash(voter) if voter and VOTER.match(voter) else None
    with db.pool().connection() as conn:
        polls = conn.execute(
            """SELECT id, question, description, options, closes FROM polls
               WHERE active AND (closes IS NULL OR closes >= current_date) AND (%s::text IS NULL OR id = %s)
               ORDER BY created_at DESC, id""", (poll_id, poll_id)).fetchall()
        out = []
        for p in polls:
            rows = conn.execute("SELECT option, count(*) AS n FROM poll_votes WHERE poll_id = %s GROUP BY option",
                                (p["id"],)).fetchall()
            counts = [0] * len(p["options"])
            for r in rows:
                if r["option"] < len(counts):
                    counts[r["option"]] = r["n"]
            mine = conn.execute("SELECT option FROM poll_votes WHERE poll_id = %s AND voter = %s",
                                (p["id"], me)).fetchone() if me else None
            out.append({**p, "counts": counts, "total": sum(counts), "my_vote": mine["option"] if mine else None})
    return out


@api.get("")
def polls(voter: str | None = None):
    """Running polls with their results and, given the install's id, its own vote."""
    return _polls(voter)


class Vote(BaseModel):
    option: int
    voter: str


@api.post("/{poll_id}/hlas")
def vote(poll_id: str, body: Vote):
    """Cast a vote. The first vote of an install counts; repeating it changes nothing."""
    if not VOTER.match(body.voter):
        raise HTTPException(422, "neplatný identifikátor")
    found = _polls(None, poll_id)
    if not found:
        raise HTTPException(404, "anketa neběží")
    if not 0 <= body.option < len(found[0]["options"]):
        raise HTTPException(422, "neplatná možnost")
    with db.pool().connection() as conn:
        conn.execute("INSERT INTO poll_votes (poll_id, voter, option) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                     (poll_id, _hash(body.voter), body.option))
    return _polls(body.voter, poll_id)[0]
