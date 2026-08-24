"""Development entry point for the MCP Inspector / `mcp dev` workflow.

The MCP CLI (`mcp dev` / `mcp run`) loads a server file directly as a
standalone module named "server_module" (see `mcp.cli.cli._import_server`),
so package-relative imports inside `mcquest_mcp.server` cannot be used in
that file. This thin launcher re-exports the real `MCPServer` instance from
the installed `mcquest_mcp` package, preserving the src-layout and the
package-relative imports in the actual server implementation.
"""

from mcquest_mcp.server import mcp

__all__ = ["mcp"]