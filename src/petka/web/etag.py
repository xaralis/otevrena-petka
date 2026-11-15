"""Conditional answers of the data sources (API, exports): a weak ETag of what an answer is
made of (the data's version and the request's normalised parameters) and 304 Not Modified
when the client already has it, so a phone downloads a file only when it changed.

Weak, because the portal gzips answers: the bytes change, the content doesn't.
"""

import hashlib

from fastapi import Request
from fastapi.responses import Response


def weak(*parts) -> str:
    """A weak ETag of the parts (each turned into a string, joined by "|")."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return f'W/"{h[:24]}"'


def fresh(request: Request, tag: str) -> bool:
    """Whether the request's If-None-Match names `tag` or "*" (weak comparison: W/ ignored)."""
    sent = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
    return tag.removeprefix("W/") in sent or "*" in sent


def not_modified(headers: dict) -> Response:
    """304 with the answer's ETag and Cache-Control and no body."""
    return Response(status_code=304, headers=headers)
