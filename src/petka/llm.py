"""Structured-output calls to Claude, one interface with two adapters.

- `AnthropicAPI`: the Anthropic SDK with ANTHROPIC_API_KEY (the daily CronJobs in the cluster).
- `ClaudeCLI`: `claude -p --json-schema` on a Claude subscription (backfills, run from a machine
  where Claude Code is logged in). No tools, no settings, no MCP – just the prompt and the schema,
  so the result is the same as through the API.

Both return the parsed JSON object that validates against `schema`. `default()` picks one from
the environment (LLM_BACKEND, LLM_MODEL, LLM_CLI_MODEL); callers take an `LLM` as a parameter
so tests can hand them a fake.
"""

import base64
import functools
import json
import logging
import os
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


# --- usage (per thread, across adapters: one card is written by one model and checked by another)

_usage = threading.local()


def track_usage() -> dict:
    """Start adding up what this thread's calls use; returns the running totals. `usd` is what the
    calls would cost through the API (the CLI reports it; on a subscription nothing is billed)."""
    _usage.totals = {"calls": 0, "input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "usd": 0.0}
    return _usage.totals


def _add_usage(u: dict, usd: float = 0.0) -> None:
    t = getattr(_usage, "totals", None)
    if t is not None:
        t["calls"] += 1
        t["input"] += u.get("input_tokens") or 0
        t["cache_read"] += u.get("cache_read_input_tokens") or 0
        t["cache_write"] += u.get("cache_creation_input_tokens") or 0
        t["output"] += u.get("output_tokens") or 0
        t["usd"] = round(t["usd"] + (usd or 0), 4)


# --- the interface -----------------------------------------------------------------------------

TRANSCRIBE_SYSTEM = ("Přepiš český úřední dokument (usnesení a zápis z jednání) přesně do prostého "
                     "textu. Zachovej pořadí, odstavce, číslování a všechna čísla a jména. Nic "
                     "nevynechávej, nic nepřidávej, neshrnuj.")
TRANSCRIBE_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"], "additionalProperties": False}


class LLM:
    """What callers see. `backend` names the adapter ("api", "claude-cli"); `model_id` is what a
    result records as its author."""

    backend: str = ""
    model_id: str = ""

    def structured(self, system: str, user: str, schema: dict, *, effort: str = "high",
                   max_tokens: int = 64000) -> dict:
        raise NotImplementedError

    def structured_files(self, system: str, user: str, files: list[Path], schema: dict, *,
                         effort: str = "high", max_tokens: int = 32000, model: str | None = None) -> dict:
        """Like `structured`, with PDFs/images for Claude to read (text and pictures). `model`
        overrides the adapter's default for this call."""
        raise NotImplementedError

    def transcribe_pdf(self, path: Path) -> str:
        """Text of a scanned PDF (no text layer). Rare – one ZMO record so far."""
        raise NotImplementedError

    track_usage = staticmethod(track_usage)


class AnthropicAPI(LLM):
    backend = "api"

    def __init__(self, model: str = "claude-opus-5-5"):
        self.model = model
        self.model_id = model

    def structured(self, system, user, schema, *, effort="high", max_tokens=64000):
        return self._call(system, [{"type": "text", "text": user}], schema, effort, max_tokens)

    def structured_files(self, system, user, files, schema, *, effort="high", max_tokens=32000, model=None):
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
        return self._call(system, content, schema, effort, max_tokens, model=model)

    def transcribe_pdf(self, path):
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return self._call(TRANSCRIBE_SYSTEM, [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": "Přepiš celý dokument."},
        ], TRANSCRIBE_SCHEMA, "medium", 64000)["text"]

    def _call(self, system: str, content: list, schema: dict, effort: str, max_tokens: int,
              model: str | None = None) -> dict:
        import anthropic

        client = anthropic.Anthropic()
        with client.beta.messages.stream(
            model=model or self.model,
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


class ClaudeCLI(LLM):
    backend = "claude-cli"

    def __init__(self, model: str = "opus"):
        self.model = model
        self.model_id = f"cli:{model}"

    def structured(self, system, user, schema, *, effort="high", max_tokens=64000):
        return self._call(system, user, schema)

    def structured_files(self, system, user, files, schema, *, effort="high", max_tokens=32000, model=None):
        # the model may read these files and nothing else: run in their directory and allow
        # Read only there (the attachments come from outside; don't hand them the machine)
        dirs = sorted({str(p.resolve().parent) for p in files})
        if len(dirs) != 1:
            raise LLMError("claude-cli: attachments must be in one directory")
        listing = "\n".join(f"- {p.resolve()}" for p in files)
        return self._call(system, f"{user}\n\nPřílohy (přečti je nástrojem Read):\n{listing}", schema,
                          tools="Read", allowed=f"Read({dirs[0]}/**)", cwd=dirs[0], model=model)

    def transcribe_pdf(self, path):
        return self._call(TRANSCRIBE_SYSTEM, f"Přepiš soubor {path.resolve()} (použij nástroj Read).",
                          TRANSCRIBE_SCHEMA, tools="Read", add_dir=str(path.resolve().parent))["text"]

    def _call(self, system: str, user: str, schema: dict, tools: str = "", add_dir: str | None = None,
              allowed: str | None = None, cwd: str = "/tmp", model: str | None = None) -> dict:
        cmd = ["claude", "-p", "--model", model or self.model, "--output-format", "json",
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
        _add_usage(u, res.get("total_cost_usd"))
        log.info("llm cli in=%s cache_read=%s out=%s", u.get("input_tokens"),
                 u.get("cache_read_input_tokens"), u.get("output_tokens"))
        return res["structured_output"]


# --- the factory -------------------------------------------------------------------------------

def from_env(env=os.environ) -> LLM:
    """The adapter LLM_BACKEND names (`api` unless said otherwise)."""
    if env.get("LLM_BACKEND", "api") == "claude-cli":
        return ClaudeCLI(env.get("LLM_CLI_MODEL", "opus"))
    return AnthropicAPI(env.get("LLM_MODEL", "claude-opus-5-5"))


@functools.cache
def default() -> LLM:
    """The process-wide adapter, chosen once from the environment."""
    return from_env()
