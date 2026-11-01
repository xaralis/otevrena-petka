"""One MCP server for the whole portal (streamable HTTP at /mcp), read-only. Each section
registers its tools; the instructions tell a model what exists and how to read it."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .usneseni import mcp_tools as usneseni_tools

INSTRUCTIONS = (
    "Otevřená Pětka – otevřená data městského obvodu Pardubice V. Zatím je k dispozici "
    "sekce Usnesení (zastupitelstvo a rada od 2018); rozpočet, smlouvy a úřední deska "
    "se připravují.\n\n" + usneseni_tools.INSTRUCTIONS
)

mcp = FastMCP(
    "otevrena-petka", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
usneseni_tools.register(mcp)
