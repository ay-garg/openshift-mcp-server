"""
Kubernetes/OpenShift client management module.

Handles multi-cluster authentication, API client construction, and shared utilities
used throughout the MCP tool modules.

Auth priority (first match wins):
  1. OCP_CLUSTERS — JSON array of cluster config dicts
  2. OCP_API_URL + OCP_TOKEN — Bearer-token auth
  3. OCP_API_URL + OCP_USERNAME + OCP_PASSWORD — oc login, then extract token
  4. kubeconfig file/context (OCP_KUBECONFIG, OCP_KUBECONFIG_CONTEXT)
  5. In-cluster ServiceAccount token
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def format_error(e: Exception) -> str:
    """Format an exception as a human-readable string.

    ApiException bodies are JSON-decoded so the Kubernetes message field is
    surfaced directly instead of the raw HTTP payload.
    """
    if isinstance(e, ApiException):
        try:
            body = json.loads(e.body)
            return f"API Error {e.status}: {body.get('message', e.reason)}"
        except Exception:
            return f"API Error {e.status}: {e.reason}"
    return f"{type(e).__name__}: {e}"


def age_string(timestamp) -> str:
    """Return a compact human-readable age string from a datetime or ISO-8601 str.

    Examples: "3d", "5h", "12m", "30s".
    Accepts datetime objects (with or without tzinfo) and ISO-8601 strings
    (with or without trailing Z).
    """
    if timestamp is None:
        return "unknown"

    if isinstance(timestamp, str):
        ts = timestamp.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return "unknown"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    elif isinstance(timestamp, datetime):
        dt = timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        return "unknown"

    total_seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if total_seconds < 0:
        return "0s"

    days = total_seconds // 86400
    if days > 0:
        return f"{days}d"
    hours = (total_seconds % 86400) // 3600
    if hours > 0:
        return f"{hours}h"
    minutes = (total_seconds % 3600) // 60
    if minutes > 0:
        return f"{minutes}m"
    return f"{total_seconds % 60}s"


def format_table(headers: list, rows: list, max_col: int = 40) -> str:
    """Render a left-aligned plain-text table.

    Column widths are derived from the widest value in each column, capped at
    *max_col* characters (values are truncated with "…" if necessary).
    """
    if not headers:
        return ""

    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], min(len(str(cell)), max_col))

    def _truncate(s: str) -> str:
        if len(s) > max_col:
            return s[: max_col - 3] + "..."
        return s

    def _fmt(row) -> str:
        cells = []
        for i, cell in enumerate(row):
            s = _truncate(str(cell))
            cells.append(s.ljust(col_widths[i]) if i < len(col_widths) else s)
        return "  ".join(cells).rstrip()

    lines = [_fmt(headers), "  ".join("-" * w for w in col_widths)]
    lines.extend(_fmt(row) for row in rows)
    return "\n".join(lines)


def run_oc(args: list, stdin: str = "", timeout: int = 60) -> tuple[bool, str]:
    """Execute an ``oc`` CLI command.

    Returns ``(success, output)`` where *output* is stdout on success or the
    combined stdout+stderr on failure.
    """
    cmd = ["oc"] + [str(a) for a in args]
    try:
        result = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            out = result.stdout
            if not out and result.stderr:
                out = result.stderr
            return True, out
        else:
            out = (result.stdout + "\n" + result.stderr).strip()
            return False, out
    except subprocess.TimeoutExpired:
        safe = []
        skip_next = False
        for tok in cmd:
            if skip_next:
                safe.append("<redacted>")
                skip_next = False
            elif tok == "--token":
                safe.append(tok)
                skip_next = True
            else:
                safe.append(tok)
        return False, f"Command timed out after {timeout}s: {' '.join(safe)}"
    except FileNotFoundError:
        return False, "oc CLI not found. Install the OpenShift CLI (oc) and ensure it is on PATH."
    except Exception as exc:
        return False, f"Error running oc: {exc}"


# ---------------------------------------------------------------------------
# ClusterClient
# ---------------------------------------------------------------------------

class ClusterClient:
    """Thin wrapper around a ``kubernetes.client.ApiClient`` for one cluster.

    Lazy properties create API group clients on demand so no unnecessary
    connections are made.
    """

    def __init__(self, configuration: client.Configuration, name: str = "default"):
        self._configuration = configuration
        self._name = name
        self._api_client = client.ApiClient(configuration)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Logical name of this cluster (used for display / selection)."""
        return self._name

    # ------------------------------------------------------------------
    # Standard API groups
    # ------------------------------------------------------------------

    @property
    def core_v1(self) -> client.CoreV1Api:
        return client.CoreV1Api(self._api_client)

    @property
    def apps_v1(self) -> client.AppsV1Api:
        return client.AppsV1Api(self._api_client)

    @property
    def batch_v1(self) -> client.BatchV1Api:
        return client.BatchV1Api(self._api_client)

    @property
    def rbac_v1(self) -> client.RbacAuthorizationV1Api:
        return client.RbacAuthorizationV1Api(self._api_client)

    @property
    def autoscaling_v2(self) -> client.AutoscalingV2Api:
        return client.AutoscalingV2Api(self._api_client)

    @property
    def networking_v1(self) -> client.NetworkingV1Api:
        return client.NetworkingV1Api(self._api_client)

    @property
    def storage_v1(self) -> client.StorageV1Api:
        return client.StorageV1Api(self._api_client)

    @property
    def custom(self) -> client.CustomObjectsApi:
        return client.CustomObjectsApi(self._api_client)

    @property
    def dynamic(self) -> DynamicClient:
        return DynamicClient(self._api_client)

    # ------------------------------------------------------------------
    # oc CLI helpers
    # ------------------------------------------------------------------

    def oc_args(self) -> list:
        """Return ``oc`` flags that authenticate against this cluster.

        Suitable for prepending to any ``run_oc`` call so the correct cluster
        is targeted regardless of the active kubeconfig context.
        """
        args: list = []
        cfg = self._configuration
        host = getattr(cfg, "host", "") or ""
        # Only inject --server when we have a real URL (not localhost default)
        if host and host not in ("https://localhost", "http://localhost"):
            args += ["--server", host]
        api_key: dict = getattr(cfg, "api_key", {}) or {}
        token = api_key.get("authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        if token:
            args += ["--token", token]
        if not getattr(cfg, "verify_ssl", True):
            args.append("--insecure-skip-tls-verify=true")
        return args

    # ------------------------------------------------------------------
    # Custom-resource helpers
    # ------------------------------------------------------------------

    def list_custom(
        self,
        group: str,
        version: str,
        plural: str,
        namespace: str = "",
        label_selector: str = "",
        field_selector: str = "",
    ) -> list:
        """List custom resources, cluster-scoped or namespaced."""
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector
        if field_selector:
            kwargs["field_selector"] = field_selector
        if namespace:
            result = self.custom.list_namespaced_custom_object(
                group, version, namespace, plural, **kwargs
            )
        else:
            result = self.custom.list_cluster_custom_object(group, version, plural, **kwargs)
        return result.get("items", [])

    def get_custom(
        self,
        group: str,
        version: str,
        plural: str,
        name: str,
        namespace: str = "",
    ) -> dict:
        """Get a single custom resource by name."""
        if namespace:
            return self.custom.get_namespaced_custom_object(
                group, version, namespace, plural, name
            )
        return self.custom.get_cluster_custom_object(group, version, plural, name)

    def patch_custom(
        self,
        group: str,
        version: str,
        plural: str,
        name: str,
        body: dict,
        namespace: str = "",
    ) -> dict:
        """Strategic-merge-patch a custom resource."""
        if namespace:
            return self.custom.patch_namespaced_custom_object(
                group, version, namespace, plural, name, body
            )
        return self.custom.patch_cluster_custom_object(
            group, version, plural, name, body
        )

    def create_custom(
        self,
        group: str,
        version: str,
        plural: str,
        body: dict,
        namespace: str = "",
    ) -> dict:
        """Create a custom resource."""
        if namespace:
            return self.custom.create_namespaced_custom_object(
                group, version, namespace, plural, body
            )
        return self.custom.create_cluster_custom_object(group, version, plural, body)

    def delete_custom(
        self,
        group: str,
        version: str,
        plural: str,
        name: str,
        namespace: str = "",
    ) -> dict:
        """Delete a custom resource by name."""
        if namespace:
            return self.custom.delete_namespaced_custom_object(
                group, version, namespace, plural, name
            )
        return self.custom.delete_cluster_custom_object(group, version, plural, name)


# ---------------------------------------------------------------------------
# ClusterRegistry
# ---------------------------------------------------------------------------

class ClusterRegistry:
    """
    Discovers and holds all configured cluster connections.

    Environment variables
    ---------------------
    OCP_CLUSTERS
        JSON string.  Either an array of cluster-config objects or a single
        object.  Each object supports the keys:
          name, api_url, token, username, password, skip_tls_verify.

    OCP_API_URL
        Base URL of the API server (e.g. ``https://api.cluster.example.com:6443``).

    OCP_TOKEN
        Bearer token for the service account or user.

    OCP_USERNAME / OCP_PASSWORD
        Credentials for ``oc login`` when a token is not available.

    OCP_SKIP_TLS_VERIFY
        Set to ``true`` / ``1`` / ``yes`` to disable TLS verification.

    OCP_KUBECONFIG
        Path to a kubeconfig file (defaults to ``~/.kube/config``).

    OCP_KUBECONFIG_CONTEXT
        Named context inside the kubeconfig to activate.
    """

    def __init__(self) -> None:
        self._clients: dict[str, ClusterClient] = {}
        self._default: str = ""
        self._load()

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _token_client(
        self, api_url: str, token: str, skip_tls: bool = False, name: str = "default"
    ) -> ClusterClient:
        cfg = client.Configuration()
        cfg.host = api_url
        cfg.api_key = {"authorization": f"Bearer {token}"}
        cfg.verify_ssl = not skip_tls
        return ClusterClient(cfg, name=name)

    def _build_from_dict(self, cluster_def: dict) -> Optional[ClusterClient]:
        """Build a ClusterClient from a cluster config dict."""
        cname = cluster_def.get("name", "unknown")
        api_url = cluster_def.get("api_url", "").strip()
        token = cluster_def.get("token", "").strip()
        skip_tls = bool(cluster_def.get("skip_tls_verify", False))

        if api_url and token:
            return self._token_client(api_url, token, skip_tls, name=cname)

        username = cluster_def.get("username", "").strip()
        password = cluster_def.get("password", "").strip()
        if api_url and username and password:
            login_args = ["login", api_url, "-u", username, "-p", password]
            if skip_tls:
                login_args.append("--insecure-skip-tls-verify=true")
            ok, _ = run_oc(login_args)
            if ok:
                ok2, tok_out = run_oc(["whoami", "-t"])
                if ok2:
                    return self._token_client(api_url, tok_out.strip(), skip_tls, name=cname)

        return None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        # ----------------------------------------------------------------
        # 1. OCP_CLUSTERS JSON
        # ----------------------------------------------------------------
        clusters_json = os.environ.get("OCP_CLUSTERS", "").strip()
        if clusters_json:
            try:
                parsed = json.loads(clusters_json)
                cluster_list = parsed if isinstance(parsed, list) else [parsed]
                for cdef in cluster_list:
                    c = self._build_from_dict(cdef)
                    if c:
                        cname = cdef.get("name", f"cluster-{len(self._clients)}")
                        self._clients[cname] = c
                        if not self._default:
                            self._default = cname
                if self._clients:
                    return
            except (json.JSONDecodeError, Exception):
                pass  # fall through to next strategy

        # ----------------------------------------------------------------
        # 2. OCP_API_URL + OCP_TOKEN
        # ----------------------------------------------------------------
        api_url = os.environ.get("OCP_API_URL", "").strip()
        token = os.environ.get("OCP_TOKEN", "").strip()
        skip_tls = os.environ.get("OCP_SKIP_TLS_VERIFY", "false").lower() in (
            "true", "1", "yes",
        )

        if api_url and token:
            self._clients["default"] = self._token_client(api_url, token, skip_tls)
            self._default = "default"
            return

        # ----------------------------------------------------------------
        # 3. OCP_API_URL + OCP_USERNAME + OCP_PASSWORD
        # ----------------------------------------------------------------
        username = os.environ.get("OCP_USERNAME", "").strip()
        password = os.environ.get("OCP_PASSWORD", "").strip()
        if api_url and username and password:
            login_args = ["login", api_url, "-u", username, "-p", password]
            if skip_tls:
                login_args.append("--insecure-skip-tls-verify=true")
            ok, _ = run_oc(login_args)
            if ok:
                ok2, tok_out = run_oc(["whoami", "-t"])
                if ok2:
                    self._clients["default"] = self._token_client(
                        api_url, tok_out.strip(), skip_tls
                    )
                    self._default = "default"
                    return

        # ----------------------------------------------------------------
        # 4. kubeconfig
        # ----------------------------------------------------------------
        kubeconfig_path = os.environ.get("OCP_KUBECONFIG", "").strip()
        context_name = os.environ.get("OCP_KUBECONFIG_CONTEXT", "").strip()
        try:
            cfg = client.Configuration()
            load_kwargs: dict = {"client_configuration": cfg}
            if kubeconfig_path:
                load_kwargs["config_file"] = kubeconfig_path
            if context_name:
                load_kwargs["context"] = context_name
            config.load_kube_config(**load_kwargs)
            logical_name = context_name or "default"
            self._clients[logical_name] = ClusterClient(cfg, name=logical_name)
            self._default = logical_name
            return
        except Exception:
            pass

        # ----------------------------------------------------------------
        # 5. In-cluster ServiceAccount
        # ----------------------------------------------------------------
        try:
            cfg = client.Configuration()
            config.load_incluster_config(client_configuration=cfg)
            self._clients["in-cluster"] = ClusterClient(cfg, name="in-cluster")
            self._default = "in-cluster"
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str = "") -> ClusterClient:
        """Return the named ClusterClient, or the default when *name* is empty."""
        resolved = name or self._default
        if not resolved:
            raise RuntimeError(
                "No cluster configured. "
                "Set OCP_API_URL+OCP_TOKEN, OCP_CLUSTERS, or provide a kubeconfig."
            )
        if resolved not in self._clients:
            available = list(self._clients.keys())
            raise ValueError(
                f"Cluster '{resolved}' not found. Available clusters: {available}"
            )
        return self._clients[resolved]

    def list(self) -> list[str]:
        """Return the names of all registered clusters."""
        return list(self._clients.keys())


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_registry: Optional[ClusterRegistry] = None


def _get_registry() -> ClusterRegistry:
    global _registry
    if _registry is None:
        _registry = ClusterRegistry()
    return _registry


def get_client(cluster: str = "") -> ClusterClient:
    """Return a :class:`ClusterClient` for *cluster*, or the default cluster."""
    return _get_registry().get(cluster)


def list_clusters() -> list[str]:
    """Return the names of all configured clusters."""
    return _get_registry().list()
