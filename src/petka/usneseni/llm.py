"""Structured-output calls to Claude through one of two backends.

- `api`: the Anthropic SDK with ANTHROPIC_API_KEY (the daily CronJob in the cluster).
- `claude-cli`: `claude -p --json-schema` on a Claude subscription (the first backfill, run
  from a machine where Claude Code is logged in). No tools, no settings, no MCP – just the
  prompt and the schema, so the result is the same as through the API.

Both return the parsed JSON object that validates against `schema`.
"""

import base64
import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

BACKEND = os.environ.get("LLM_BACKEND", "api")
MODEL = os.environ.get("LLM_MODEL", "claude-opus-5-5")
CLI_MODEL = os.environ.get("LLM_CLI_MODEL", "opus")


class LLMError(RuntimeError):
    pass


def structured(system: str, user: str, schema: dict, *, effort: str = "high",
               max_tokens: int = 64000) -> dict:
    if BACKEND == "claude-cli":
        return _cli(system, user, schema)
    return _api(system, [{"type": "text", "text": user}], schema, effort, max_tokens)


def structured_files(system: str, user: str, files: list[Path], schema: dict, *,
                     effort: str = "high", max_tokens: int = 32000) -> dict:
    """Like `structured`, with PDFs/images for Claude to read (text and pictures)."""
    if BACKEND == "claude-cli":
        # the model may read these files and nothing else: run in their directory and allow
        # Read only there (the attachments come from outside; don't hand them the machine)
        dirs = sorted({str(p.resolve().parent) for p in files})
        if len(dirs) != 1:
            raise LLMError("claude-cli: attachments must be in one directory")
        listing = "\n".join(f"- {p.resolve()}" for p in files)
        return _cli(system, f"{user}\n\nPřílohy (přečti je nástrojem Read):\n{listing}", schema,
                    tools="Read", allowed=f"Read({dirs[0]}/**)", cwd=dirs[0])
    content = []
    for p in files:
        data = base64.standard_b64encode(p.read_bytes()).decode()
        if p.suffix.lower() == ".pdf":
            content.append({"type": "document", "title": p.name,
                            "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
        else:
            media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    content.append({"type": "text", "text": user})
    return _api(system, content, schema, effort, max_tokens)


def transcribe_pdf(path: Path) -> str:
    """Text of a scanned PDF (no text layer). Rare – one ZMO record so far."""
    system = ("Přepiš český úřední dokument (usnesení a zápis z jednání) přesně do prostého "
              "textu. Zachovej pořadí, odstavce, číslování a všechna čísla a jména. Nic "
              "nevynechávej, nic nepřidávej, neshrnuj.")
    schema = {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"], "additionalProperties": False}
    if BACKEND == "claude-cli":
        out = _cli(system, f"Přepiš soubor {path.resolve()} (použij nástroj Read).", schema,
                   tools="Read", add_dir=str(path.resolve().parent))
    else:
        data = base64.standard_b64encode(path.read_bytes()).decode()
        out = _api(system, [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": "Přepiš celý dokument."},
        ], schema, "medium", 64000)
    return out["text"]


def _api(system: str, content: list, schema: dict, effort: str, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise LLMError(f"refused: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise LLMError("output truncated at max_tokens")
    text = next(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    log.info("llm api model=%s in=%s cache_read=%s out=%s", msg.model, u.input_tokens,
             u.cache_read_input_tokens, u.output_tokens)
    return json.loads(text)


def _cli(system: str, user: str, schema: dict, tools: str = "", add_dir: str | None = None,
         allowed: str | None = None, cwd: str = "/tmp") -> dict:
    cmd = ["claude", "-p", "--model", CLI_MODEL, "--output-format", "json",
           "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
           "--disable-slash-commands", "--tools", tools, "--system-prompt", system,
           "--json-schema", json.dumps(schema, ensure_ascii=False)]
    if tools:
        cmd += ["--allowedTools", allowed or tools]
    if add_dir:
        cmd += ["--add-dir", add_dir]
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=1800,
                          cwd=cwd)
    try:
        res = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude -p failed ({proc.returncode}): {proc.stderr[-2000:]}") from e
    if res.get("is_error") or res.get("structured_output") is None:
        raise LLMError(f"claude -p error: {str(res.get('result'))[:2000]}")
    u = res.get("usage", {})
    log.info("llm cli in=%s cache_read=%s out=%s", u.get("input_tokens"),
             u.get("cache_read_input_tokens"), u.get("output_tokens"))
    return res["structured_output"]
