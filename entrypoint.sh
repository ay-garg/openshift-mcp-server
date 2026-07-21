#!/usr/bin/env bash
# OCP MCP Server — container entrypoint
#
# Environment variables
# ─────────────────────
#   OCP_MODE       server (default) | ui
#   MCP_TRANSPORT  stdio (default)  | streamable-http
#
# In Kubernetes/OpenShift always set MCP_TRANSPORT=streamable-http — stdio has
# no network exposure and is only useful when the container's stdin/stdout is
# piped by the MCP client process (e.g. Claude Desktop on localhost).
set -euo pipefail

OCP_MODE="${OCP_MODE:-server}"

case "$OCP_MODE" in
  server)
    exec ocp-mcp-server "$@"
    ;;
  ui)
    exec ocp-mcp-ui "$@"
    ;;
  *)
    echo "ERROR: Unknown OCP_MODE='${OCP_MODE}'. Valid values: server, ui" >&2
    exit 1
    ;;
esac
