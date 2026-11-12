"""One MCP server for the whole portal (streamable HTTP at /mcp), read-only. Each section
supplies its tools and instructions; the instructions tell a model what exists and how to read it."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .sections import REGISTRY

_parts = [s.mcp() for s in REGISTRY if s.mcp]

INSTRUCTIONS = (
    "Otevřená Pětka – otevřená data městského obvodu Pardubice V. K dispozici jsou sekce "
    "Usnesení (zastupitelstvo a rada od 2018), Úřední deska a Podněty (hlášení z aplikace "
    "Dej Tip); rozpočet a smlouvy se připravují.\n\n" + "\n".join(instructions for instructions, _ in _parts)
)

mcp = FastMCP(
    "otevrena-petka", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
READ_ONLY = ToolAnnotations(readOnlyHint=True)   # every tool only reads
for _, tools in _parts:
    for fn in tools:
        mcp.tool(annotations=READ_ONLY)(fn)
