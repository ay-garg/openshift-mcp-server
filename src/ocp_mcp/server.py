"""OpenShift 4 MCP Server — entry point."""

from __future__ import annotations

import os

from ocp_mcp.app import _DEFAULT_MCP_PORT, _parse_port, mcp

import ocp_mcp.tools.cluster        # noqa: F401
import ocp_mcp.tools.workloads      # noqa: F401
import ocp_mcp.tools.networking     # noqa: F401
import ocp_mcp.tools.storage        # noqa: F401
import ocp_mcp.tools.config         # noqa: F401
import ocp_mcp.tools.rbac           # noqa: F401
import ocp_mcp.tools.builds         # noqa: F401
import ocp_mcp.tools.operators      # noqa: F401
import ocp_mcp.tools.machines       # noqa: F401
import ocp_mcp.tools.monitoring     # noqa: F401
import ocp_mcp.tools.security       # noqa: F401
import ocp_mcp.tools.autoscaling    # noqa: F401
import ocp_mcp.tools.gitops         # noqa: F401
import ocp_mcp.tools.pipelines      # noqa: F401
import ocp_mcp.tools.service_mesh   # noqa: F401
import ocp_mcp.tools.ocp_ai         # noqa: F401
import ocp_mcp.tools.virtualization # noqa: F401
import ocp_mcp.tools.konflux        # noqa: F401
import ocp_mcp.tools.acm            # noqa: F401
import ocp_mcp.tools.generic        # noqa: F401

import ocp_mcp.resources            # noqa: F401
import ocp_mcp.prompts              # noqa: F401


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if transport == "sse":
        # Validate MCP_PORT for SSE only — stdio uses stdin/stdout, not the port.
        # _parse_port gives a clear error (with range) and warns on whitespace.
        # Writing back to mcp.settings.port ensures the server binds on the
        # validated port even if app.py fell back to 8080 at import time.
        mcp.settings.port = _parse_port(
            os.environ.get("MCP_PORT", str(_DEFAULT_MCP_PORT)), "MCP_PORT"
        )
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
