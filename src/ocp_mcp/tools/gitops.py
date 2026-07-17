"""ArgoCD / OpenShift GitOps tools: Applications, AppProjects, Clusters."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_APP = ("argoproj.io", "v1alpha1", "applications")
_PROJ = ("argoproj.io", "v1alpha1", "appprojects")


@mcp.tool()
def list_gitops_applications(namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """List ArgoCD Applications with sync/health status, repo, revision, destination, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_APP, namespace=namespace)
        rows = []
        for app in items:
            spec = app.get("spec", {})
            status = app.get("status", {})
            src = spec.get("source", {})
            dest = spec.get("destination", {})
            repo = src.get("repoURL", "")
            dest_str = f"{dest.get('server', '')}/{dest.get('namespace', '')}"
            rows.append([
                app.get("metadata", {}).get("name", ""),
                status.get("sync", {}).get("status", "?"),
                status.get("health", {}).get("status", "?"),
                repo[-40:] if repo else "",
                src.get("targetRevision", "HEAD"),
                dest_str[-40:],
                age_string(app.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "SYNC", "HEALTH", "REPO", "REVISION", "DESTINATION", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_gitops_application(name: str, namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """Get ArgoCD Application details: sync/health/repo/path/destination + resources table."""
    c = get_client(cluster)
    try:
        app = c.get_custom(*_APP, name, namespace)
        spec = app.get("spec", {})
        status = app.get("status", {})
        src = spec.get("source", {})
        dest = spec.get("destination", {})
        sync = status.get("sync", {})
        health = status.get("health", {})
        lines = [
            f"Application: {namespace}/{name}",
            f"  Sync:        {sync.get('status', '?')} (revision={sync.get('revision', '')})",
            f"  Health:      {health.get('status', '?')} {health.get('message', '')}".rstrip(),
            f"  Repo:        {src.get('repoURL', '')}",
            f"  Path:        {src.get('path', '')}",
            f"  Target Rev:  {src.get('targetRevision', 'HEAD')}",
            f"  Destination: server={dest.get('server', '')} namespace={dest.get('namespace', '')}",
            f"  Project:     {spec.get('project', 'default')}",
            f"  Age:         {age_string(app.get('metadata', {}).get('creationTimestamp'))}",
        ]
        resources = status.get("resources", [])
        if resources:
            lines.append("\nResources:")
            rows = []
            for res in resources:
                h = res.get("health") or {}
                rows.append([
                    res.get("group", ""),
                    res.get("kind", ""),
                    res.get("namespace", ""),
                    res.get("name", ""),
                    res.get("syncStatus", "?"),
                    h.get("status", "") if isinstance(h, dict) else "",
                ])
            lines.append(format_table(["GROUP", "KIND", "NAMESPACE", "NAME", "SYNC", "HEALTH"], rows))
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def sync_gitops_application(
    name: str,
    namespace: str = "openshift-gitops",
    prune: bool = False,
    dry_run: bool = False,
    cluster: str = "",
) -> str:
    """Trigger a sync on an ArgoCD Application by patching the operation field."""
    c = get_client(cluster)
    try:
        operation = {
            "initiatedBy": {"username": "ocp-mcp"},
            "sync": {
                "prune": prune,
                "dryRun": dry_run,
                "syncStrategy": {"hook": {"force": False}},
            },
        }
        c.patch_custom(*_APP, name, {"operation": operation}, namespace)
        flags = []
        if prune:
            flags.append("prune=true")
        if dry_run:
            flags.append("dry-run=true")
        flag_str = f" ({', '.join(flags)})" if flags else ""
        return f"Sync triggered for Application '{namespace}/{name}'{flag_str}."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_gitops_application_health(name: str, namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """Get per-resource health status for an ArgoCD Application."""
    c = get_client(cluster)
    try:
        app = c.get_custom(*_APP, name, namespace)
        status = app.get("status", {})
        overall_health = status.get("health", {})
        lines = [
            f"Application: {namespace}/{name}",
            f"Overall Health: {overall_health.get('status', '?')}",
        ]
        if overall_health.get("message"):
            lines.append(f"Message: {overall_health['message']}")
        resources = status.get("resources", [])
        if resources:
            lines.append("")
            rows = []
            for res in resources:
                h = res.get("health") or {}
                rows.append([
                    res.get("group", ""),
                    res.get("kind", ""),
                    res.get("namespace", ""),
                    res.get("name", ""),
                    h.get("status", "?") if isinstance(h, dict) else "?",
                    (h.get("message", "")[:60] if isinstance(h, dict) else ""),
                ])
            lines.append(format_table(["GROUP", "KIND", "NAMESPACE", "NAME", "HEALTH", "MESSAGE"], rows))
        else:
            lines.append("No resources found.")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def refresh_gitops_application(name: str, namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """Force-refresh an ArgoCD Application by patching the argocd.argoproj.io/refresh annotation."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_APP, name, {
            "metadata": {"annotations": {"argocd.argoproj.io/refresh": "hard"}}
        }, namespace)
        return f"Hard refresh triggered for Application '{namespace}/{name}'."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_app_projects(namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """List ArgoCD AppProjects with source repos, destinations, and cluster resource access."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PROJ, namespace=namespace)
        rows = []
        for proj in items:
            spec = proj.get("spec", {})
            source_repos = spec.get("sourceRepos", [])
            destinations = spec.get("destinations", [])
            cluster_resources = spec.get("clusterResourceWhitelist", [])
            repos_str = str(len(source_repos)) + (" (*)" if "*" in source_repos else "")
            dests_str = str(len(destinations))
            cr_str = str(len(cluster_resources)) + (
                " (*)" if any(r.get("group") == "*" for r in cluster_resources) else ""
            )
            rows.append([
                proj.get("metadata", {}).get("name", ""),
                repos_str,
                dests_str,
                cr_str,
                age_string(proj.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "SOURCE-REPOS", "DESTINATIONS", "CLUSTER-RESOURCES", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_gitops_clusters(namespace: str = "openshift-gitops", cluster: str = "") -> str:
    """List ArgoCD registered clusters from Secrets with label argocd.argoproj.io/secret-type=cluster."""
    import base64
    import json

    ok, out = run_oc([
        "get", "secrets", "-n", namespace,
        "-l", "argocd.argoproj.io/secret-type=cluster",
        "-o", "json",
    ])
    if not ok:
        return f"Error listing ArgoCD cluster secrets: {out}"
    try:
        obj = json.loads(out)
        items = obj.get("items", [])
        if not items:
            return f"No ArgoCD cluster secrets found in namespace '{namespace}'."
        rows = []
        for secret in items:
            data = secret.get("data", {})

            def _b64(key: str) -> str:
                raw = data.get(key, "")
                if not raw:
                    return ""
                try:
                    return base64.b64decode(raw).decode("utf-8")
                except Exception:
                    return raw

            cluster_name = _b64("name")
            server_url = _b64("server")
            config_str = _b64("config")
            tls_insecure = "?"
            try:
                config = json.loads(config_str) if config_str else {}
                tls_insecure = str(config.get("tlsClientConfig", {}).get("insecure", False))
            except Exception:
                pass
            rows.append([
                cluster_name or secret.get("metadata", {}).get("name", ""),
                server_url,
                tls_insecure,
                age_string(secret.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "SERVER", "TLS-INSECURE", "AGE"], rows)
    except Exception as e:
        return format_error(e)
