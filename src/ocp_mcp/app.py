"""Shared MCP server instance — imported by every tool module."""

import ipaddress
import logging
import os

from mcp.server.fastmcp import FastMCP


_PORT_MIN, _PORT_MAX = 1, 65535
_DEFAULT_MCP_PORT = 8080


class _PortError(SystemExit):
    """SystemExit subclass raised exclusively by port-validation helpers.

    Using a dedicated subclass rather than `isinstance(e.code, str)` makes the
    dispatch in `_parse_port_or_default` explicit and immune to future changes
    in `_check_port`: only `_PortError` instances are swallowed as fallbacks;
    other `SystemExit`s (e.g. `sys.exit(0)`) propagate normally.
    Because `_PortError` is a `SystemExit` subclass, callers in `server.py` and
    `ui.py` that let it propagate still terminate the process cleanly.
    """


def _check_port(port: int, name: str) -> None:
    """Raise _PortError when port is outside _PORT_MIN–_PORT_MAX."""
    if not (_PORT_MIN <= port <= _PORT_MAX):
        raise _PortError(
            f"Invalid {name} value {port}: out of range, must be {_PORT_MIN}-{_PORT_MAX}"
        )


def _parse_port(raw: str, name: str) -> int:
    """Parse and validate a port env var; raises _PortError (a SystemExit) on any error.

    Warns when the value has leading/trailing whitespace — int() silently
    accepts ' 8080 ', masking shell-quoting mistakes in .env files.
    The warning fires only after both the int-parse AND the range check succeed,
    so it is never emitted for a value that ultimately fails either check.
    Used by server.py and ui.py for strict startup validation.
    """
    if raw is None:
        raise _PortError(f"Invalid {name} value: received None, expected a string")
    stripped = raw.strip()
    try:
        port = int(stripped)
    except ValueError:
        raise _PortError(
            f"Invalid {name} value {raw!r}: not an integer, must be {_PORT_MIN}-{_PORT_MAX}"
        ) from None
    _check_port(port, name)  # raises _PortError if out of range
    # Warn about whitespace only after full validation passes — never for values
    # that fail either the int-parse or the range check.
    if stripped != raw:
        logging.warning(
            "%s value %r has leading/trailing whitespace; using stripped value %r.",
            name, raw, stripped,
        )
    return port


def _parse_port_or_default(raw: str, name: str, default: int) -> int:
    """Like `_parse_port` but warns and returns `default` instead of raising.

    Used at module import time (where SystemExit would kill the Gradio UI
    process) to construct the FastMCP singleton with a safe fallback port.
    All validation logic lives in `_parse_port`/`_check_port`, so any new
    policy applied there automatically covers singleton construction too.

    Raises _PortError (a SystemExit) immediately if `default` is out of range —
    a programming error that is always fatal regardless of call context.
    Other SystemExits (e.g. sys.exit(0)) also propagate; only _PortError from
    the raw-value parse is swallowed and replaced by the default.
    """
    _check_port(default, f"{name} default")  # always fatal if default is bad
    try:
        return _parse_port(raw, name)
    except _PortError as e:
        # Catch only port-validation exits — sys.exit(0) and other non-_PortError
        # SystemExits propagate normally.
        logging.warning(
            "Invalid %s value %r; defaulting to %d for singleton construction. "
            "The SSE server will refuse to start if %s remains invalid. Reason: %s",
            name, raw, default, name, e.code,
        )
        return default


# Read bind address at construction time so FastMCP derives transport_security
# from the actual host. FastMCP only enables DNS-rebinding protection when host
# is a loopback address (127.0.0.1 / ::1 / localhost); for all other hosts
# transport_security is None. Default to 127.0.0.1 — operators who need
# external SSE access should set MCP_HOST=0.0.0.0 explicitly.
# NOTE: these values are frozen at first import of any ocp_mcp module;
# set env vars before importing ocp_mcp (e.g., at process start).
_host = os.environ.get("MCP_HOST", "127.0.0.1")
if not _host or _host.isspace():
    # Warn rather than raise SystemExit: app.py is evaluated at import time by
    # every tool module and by the Gradio UI. A hard exit here would kill the
    # UI process even though GRADIO_HOST, not MCP_HOST, governs its bind address.
    logging.warning("Empty MCP_HOST; defaulting to '127.0.0.1'.")
    _host = "127.0.0.1"
else:
    try:
        # Validates IP literals instantly (no DNS I/O). ipaddress raises
        # ValueError for non-IP strings such as 'localhost' or 'my-host.internal';
        # those are accepted as-is and deferred to uvicorn for resolution at bind
        # time. Note: IP typos like '127.0.0.l' also raise ValueError and are
        # therefore accepted as hostnames rather than caught here.
        ipaddress.ip_address(_host)
    except ValueError:
        pass  # Accept as a hostname — defer to bind time

# MCP_PORT: warn+fallback via _parse_port_or_default so that importing ocp_mcp
# (e.g. by the Gradio UI) does not crash the UI process. server.main() calls
# _parse_port() for strict validation before actually starting the SSE server.
_port = _parse_port_or_default(
    os.environ.get("MCP_PORT", str(_DEFAULT_MCP_PORT)), "MCP_PORT", _DEFAULT_MCP_PORT
)

mcp = FastMCP(
    name="ocp-mcp-server",
    host=_host,
    port=_port,
    instructions=(
        "You are connected to a comprehensive OpenShift 4 MCP server. "
        "You can perform any cluster operation: manage workloads, networking, storage, "
        "RBAC, builds, operators, machine management, monitoring, security, autoscaling, "
        "GitOps (ArgoCD), Tekton Pipelines, Service Mesh, OpenShift AI/RHOAI, "
        "OpenShift Virtualization (KubeVirt), Konflux/RHTAP, and ACM multi-cluster. "
        "Always confirm destructive operations (delete, drain, patch) with the user before proceeding. "
        "Use the 'cluster' parameter to target a named cluster when multi-cluster is configured."
    ),
)
