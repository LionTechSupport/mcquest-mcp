"""``mcquest-mcp`` package.

The 16-tool MCP surface is registered in :mod:`mcquest_mcp.server` via the
``@mcp.tool()`` decorators, not re-exported here. This package intentionally
does **no** eager imports so that the ``mcquest-mcp --project`` bootstrap in
:mod:`mcquest_mcp.cli` can decide the target project root and set the
``MCQUEST_PROJECT_ROOT`` environment variable *before* the server -- and the
root-freezing ``mcquest_mcp.config`` it imports -- is loaded.
"""
