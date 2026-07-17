"""Resource handlers — readable snapshots of cluster state exposed as MCP resources."""

from __future__ import annotations

import json
import os

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _condition(conditions: list[dict], ctype: str) -> str:
    return next((c.get("status", "?") for c in conditions if c.get("type") == ctype), "?")


# ---------------------------------------------------------------------------
# Cluster-scoped resources
# ---------------------------------------------------------------------------

@mcp.resource("ocp://cluster/info")
def cluster_info() -> str:
    """Current cluster version and infrastructure summary."""
    c = get_client()
    try:
        versions = c.list_custom("config.openshift.io", "v1", "clusterversions")
        cv = versions[0] if versions else {}

        infras = c.list_custom("config.openshift.io", "v1", "infrastructures")
        infra = infras[0] if infras else {}

        cv_status = cv.get("status", {})
        cv_spec = cv.get("spec", {})
        desired = cv_status.get("desired", {})
        history = cv_status.get("history", [])
        completed = next((h for h in history if h.get("state") == "Completed"), {})
        cv_conditions = cv_status.get("conditions", [])

        infra_status = infra.get("status", {})
        platform_type = infra_status.get("platformStatus", {}).get("type", "?")

        lines = [
            "=== Cluster Information ===",
            f"  Name:            {infra_status.get('infrastructureName', '?')}",
            f"  API URL:         {infra_status.get('apiServerURL', '?')}",
            f"  Platform:        {platform_type}",
            f"  Control Plane:   {infra_status.get('controlPlaneTopology', '?')}",
            f"  Infra Topology:  {infra_status.get('infrastructureTopology', '?')}",
            "",
            "=== Cluster Version ===",
            f"  Current Version: {completed.get('version', desired.get('version', '?'))}",
            f"  Desired Version: {desired.get('version', '?')}",
            f"  Channel:         {cv_spec.get('channel', desired.get('channel', '?'))}",
            f"  Available:       {_condition(cv_conditions, 'Available')}",
            f"  Progressing:     {_condition(cv_conditions, 'Progressing')}",
            f"  Upgradeable:     {_condition(cv_conditions, 'Upgradeable')}",
            "",
            "=== Version History (last 5) ===",
        ]
        for entry in history[:5]:
            ts = entry.get("completionTime") or entry.get("startedTime")
            lines.append(
                f"  {entry.get('version', '?'):30s}  {entry.get('state', '?'):12s}"
                f"  {age_string(ts)} ago"
            )

        available_updates = cv_status.get("availableUpdates", [])
        if available_updates:
            lines += ["", f"=== Available Updates ({len(available_updates)}) ==="]
            for upd in available_updates[:5]:
                lines.append(f"  {upd.get('version', '?')}")

        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.resource("ocp://cluster/nodes")
def cluster_nodes() -> str:
    """List all cluster nodes with role, ready status, OS image, kubelet version, and age."""
    ok, out = run_oc(["get", "nodes", "-o", "json"])
    if not ok:
        return f"Error listing nodes:\n{out}"
    try:
        items = json.loads(out).get("items", [])
        rows = []
        for node in items:
            meta = node.get("metadata", {})
            labels = meta.get("labels", {})
            status = node.get("status", {})

            role_labels = sorted(
                k.replace("node-role.kubernetes.io/", "")
                for k in labels
                if k.startswith("node-role.kubernetes.io/")
            )
            role = ",".join(role_labels) or "worker"

            conditions = status.get("conditions", [])
            ready = _condition(conditions, "Ready")
            node_info = status.get("nodeInfo", {})

            rows.append([
                meta.get("name", ""),
                role,
                ready,
                node_info.get("osImage", "")[:35],
                node_info.get("kubeletVersion", ""),
                age_string(meta.get("creationTimestamp")),
            ])

        rows.sort(key=lambda r: (r[1], r[0]))
        return format_table(["NAME", "ROLE", "READY", "OS", "KUBELET", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.resource("ocp://cluster/operators")
def cluster_operators() -> str:
    """List all cluster operators sorted degraded-first, with available/progressing/degraded status."""
    c = get_client()
    try:
        items = c.list_custom("config.openshift.io", "v1", "clusteroperators")
        rows = []
        for co in items:
            meta = co.get("metadata", {})
            conditions = co.get("status", {}).get("conditions", [])
            available = _condition(conditions, "Available")
            progressing = _condition(conditions, "Progressing")
            degraded = _condition(conditions, "Degraded")
            version = next(
                (v.get("version", "") for v in co.get("status", {}).get("versions", [])
                 if v.get("name") == "operator"),
                "",
            )
            rows.append([
                meta.get("name", ""),
                available,
                progressing,
                degraded,
                version,
                age_string(meta.get("creationTimestamp")),
            ])

        # Degraded=True first, then not-Available, then alphabetical
        rows.sort(key=lambda r: (r[3] != "True", r[0] != "False", r[0]))
        return format_table(["NAME", "AVAILABLE", "PROGRESSING", "DEGRADED", "VERSION", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.resource("ocp://cluster/alerts")
def cluster_alerts() -> str:
    """List currently firing alerts from Alertmanager."""
    try:
        import httpx  # optional dependency
    except ImportError:
        return "httpx is not installed. Add it to dependencies: pip install httpx"

    base_url = os.environ.get(
        "OCP_PROMETHEUS_URL",
        "https://thanos-querier.openshift-monitoring.svc:9091",
    )
    # Derive Alertmanager URL from Prometheus/Thanos URL
    alertmanager_url = (
        base_url
        .replace("thanos-querier.openshift-monitoring.svc", "alertmanager-main.openshift-monitoring.svc")
        .replace(":9091", ":9093")
    )

    token = os.environ.get("OCP_TOKEN") or os.environ.get("OCP_PROMETHEUS_TOKEN", "")
    verify_ssl = os.environ.get("OCP_VERIFY_SSL", "true").lower() not in ("false", "0", "no")

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            f"{alertmanager_url}/api/v2/alerts",
            headers=headers,
            verify=verify_ssl,
            timeout=15.0,
        )
        resp.raise_for_status()
        all_alerts: list[dict] = resp.json()
    except Exception as e:
        return f"Could not reach Alertmanager at {alertmanager_url}:\n{e}"

    if not all_alerts:
        return "No alerts found."

    # "active" state = firing and not silenced; filter out suppressed/inhibited
    firing = [
        a for a in all_alerts
        if a.get("status", {}).get("state") == "active"
        and not a.get("status", {}).get("silencedBy")
        and not a.get("status", {}).get("inhibitedBy")
    ]
    if not firing:
        firing = all_alerts  # fall back to all if state field absent

    rows = []
    for alert in firing:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        rows.append([
            labels.get("alertname", "?"),
            labels.get("severity", "?"),
            labels.get("namespace", ""),
            labels.get("pod", labels.get("instance", labels.get("service", ""))),
            annotations.get("summary", annotations.get("message", ""))[:60],
        ])

    # Sort: critical → warning → other, then alphabetical within severity
    severity_order = {"critical": 0, "warning": 1}
    rows.sort(key=lambda r: (severity_order.get(r[1], 9), r[0]))
    return (f"Firing alerts: {len(rows)}\n"
            + format_table(["ALERT", "SEVERITY", "NAMESPACE", "TARGET", "SUMMARY"], rows))


# ---------------------------------------------------------------------------
# Namespace-scoped resources
# ---------------------------------------------------------------------------

@mcp.resource("ocp://{namespace}/pods")
def namespace_pods(namespace: str) -> str:
    """List pods in a namespace with phase, ready containers, restarts, node, and age."""
    ok, out = run_oc(["get", "pods", "-n", namespace, "-o", "json"])
    if not ok:
        return f"Error listing pods in {namespace}:\n{out}"
    try:
        items = json.loads(out).get("items", [])
        rows = []
        for pod in items:
            meta = pod.get("metadata", {})
            spec = pod.get("spec", {})
            status = pod.get("status", {})

            container_statuses = status.get("containerStatuses", [])
            ready_count = sum(1 for cs in container_statuses if cs.get("ready"))
            total_count = len(spec.get("containers", []))
            restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)

            rows.append([
                meta.get("name", ""),
                status.get("phase", "?"),
                f"{ready_count}/{total_count}",
                str(restarts),
                status.get("podIP", ""),
                spec.get("nodeName", ""),
                age_string(meta.get("creationTimestamp")),
            ])

        rows.sort(key=lambda r: r[0])
        return (f"Pods in namespace '{namespace}' ({len(rows)} total)\n"
                + format_table(["NAME", "PHASE", "READY", "RESTARTS", "IP", "NODE", "AGE"], rows))
    except Exception as e:
        return format_error(e)


@mcp.resource("ocp://{namespace}/events")
def namespace_events(namespace: str) -> str:
    """List the last 50 events in a namespace sorted by most recent first."""
    ok, out = run_oc(
        ["get", "events", "-n", namespace, "--sort-by=.lastTimestamp", "-o", "json"]
    )
    if not ok:
        return f"Error listing events in {namespace}:\n{out}"
    try:
        items = json.loads(out).get("items", [])

        def _ts(e: dict) -> str:
            return e.get("lastTimestamp") or e.get("eventTime") or ""

        items_sorted = sorted(items, key=_ts, reverse=True)[:50]

        rows = []
        for evt in items_sorted:
            involved = evt.get("involvedObject", {})
            obj_ref = f"{involved.get('kind', '')}:{involved.get('name', '')}"
            rows.append([
                evt.get("type", "?"),
                evt.get("reason", "?"),
                obj_ref,
                evt.get("message", "")[:60],
                str(evt.get("count", 1)),
                age_string(_ts(evt)),
            ])

        return (f"Events in namespace '{namespace}' (last 50)\n"
                + format_table(["TYPE", "REASON", "OBJECT", "MESSAGE", "COUNT", "AGE"], rows))
    except Exception as e:
        return format_error(e)


@mcp.resource("ocp://{namespace}/deployments")
def namespace_deployments(namespace: str) -> str:
    """List Deployments in a namespace with desired/ready/available/updated replicas and age."""
    ok, out = run_oc(["get", "deployments", "-n", namespace, "-o", "json"])
    if not ok:
        return f"Error listing deployments in {namespace}:\n{out}"
    try:
        items = json.loads(out).get("items", [])
        rows = []
        for dep in items:
            meta = dep.get("metadata", {})
            spec = dep.get("spec", {})
            status = dep.get("status", {})

            desired = spec.get("replicas", 0)
            ready = status.get("readyReplicas", 0)
            available = status.get("availableReplicas", 0)
            updated = status.get("updatedReplicas", 0)

            # Surface unhealthy deployments
            conditions = status.get("conditions", [])
            available_cond = _condition(conditions, "Available")
            progressing_cond = _condition(conditions, "Progressing")

            rows.append([
                meta.get("name", ""),
                str(desired),
                str(ready),
                str(available),
                str(updated),
                available_cond,
                progressing_cond,
                age_string(meta.get("creationTimestamp")),
            ])

        rows.sort(key=lambda r: r[0])
        return (f"Deployments in namespace '{namespace}' ({len(rows)} total)\n"
                + format_table(
                    ["NAME", "DESIRED", "READY", "AVAILABLE", "UPDATED", "AVAIL-COND", "PROGRESSING", "AGE"],
                    rows,
                ))
    except Exception as e:
        return format_error(e)
