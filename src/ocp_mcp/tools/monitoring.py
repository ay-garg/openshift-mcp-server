"""Monitoring tools: Alerts, PrometheusRules, Silences, and PromQL queries."""

from __future__ import annotations

import os

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_PRULE = ("monitoring.coreos.com", "v1", "prometheusrules")


# Env helpers — read at call time so token rotation and late env injection take effect.
def _prom_url() -> str:
    return os.environ.get("OCP_PROMETHEUS_URL", "https://thanos-querier.openshift-monitoring.svc:9091")


def _token() -> str:
    return os.environ.get("OCP_PROMETHEUS_TOKEN") or os.environ.get("OCP_TOKEN", "")


def _verify_ssl() -> bool:
    return os.environ.get("OCP_VERIFY_SSL", "true").lower() != "false"


def _alertmanager_url() -> str:
    am_url = os.environ.get("OCP_ALERTMANAGER_URL", "")
    if am_url:
        return am_url
    url = _prom_url()
    if "thanos-querier" in url:
        return url.replace("thanos-querier", "alertmanager-main").replace("9091", "9093")
    return url.replace(":9091", ":9093").replace(":9090", ":9093")


def _headers() -> dict:
    tok = _token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _http_get(url: str, params: dict | None = None):
    """GET url, return parsed JSON. Closes the client on exit."""
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("httpx is required. pip install httpx") from exc
    with httpx.Client(headers=_headers(), verify=_verify_ssl(), timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _http_post(url: str, json_body: dict):
    """POST url with JSON body, return parsed JSON. Closes the client on exit."""
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("httpx is required. pip install httpx") from exc
    with httpx.Client(headers=_headers(), verify=_verify_ssl(), timeout=30) as client:
        resp = client.post(url, json=json_body)
        resp.raise_for_status()
        return resp.json()


def _http_delete(url: str) -> None:
    """DELETE url. Closes the client on exit."""
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("httpx is required. pip install httpx") from exc
    with httpx.Client(headers=_headers(), verify=_verify_ssl(), timeout=30) as client:
        resp = client.delete(url)
        resp.raise_for_status()


@mcp.tool()
def list_alerts(severity: str = "", state: str = "", cluster: str = "") -> str:
    """List active alerts from Alertmanager, optionally filtered by severity and/or state.
    severity: critical | warning | info   state: active | suppressed | unprocessed"""
    try:
        alerts = _http_get(f"{_alertmanager_url()}/api/v2/alerts")
    except Exception as exc:
        # Fallback: oc exec into alertmanager pod
        ok, out = run_oc([
            "exec", "-n", "openshift-monitoring",
            "alertmanager-main-0", "--",
            "wget", "-qO-", "http://localhost:9093/api/v2/alerts",
        ])
        if not ok:
            return f"Failed to reach Alertmanager: {exc}\nFallback also failed:\n{out}"
        try:
            import json
            alerts = json.loads(out)
        except Exception:
            return out

    rows = []
    for alert in alerts:
        labels = alert.get("labels", {})
        sev = labels.get("severity", "")
        st = alert.get("status", {}).get("state", "")
        if severity and sev != severity:
            continue
        if state and st != state:
            continue
        started = alert.get("startsAt", "")
        rows.append([
            labels.get("alertname", ""),
            sev,
            st,
            labels.get("namespace", ""),
            labels.get("pod", ""),
            started[:19].replace("T", " ") if started else "",
        ])
    rows.sort(key=lambda r: (r[1] != "critical", r[1] != "warning", r[0]))
    return format_table(["ALERT", "SEVERITY", "STATE", "NAMESPACE", "POD", "STARTED"], rows)


@mcp.tool()
def get_alert_details(alert_name: str, cluster: str = "") -> str:
    """Get full labels, annotations, status, and silence info for all instances of a named alert."""
    try:
        alerts = _http_get(f"{_alertmanager_url()}/api/v2/alerts")
    except Exception as exc:
        return f"Failed to reach Alertmanager: {exc}"

    matching = [a for a in alerts if a.get("labels", {}).get("alertname") == alert_name]
    if not matching:
        return f"No alerts found with name '{alert_name}'."

    lines = [f"Alert: {alert_name}  ({len(matching)} instance(s))\n"]
    for i, alert in enumerate(matching, 1):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status = alert.get("status", {})
        lines.append(f"--- Instance {i} ---")
        lines.append(f"  State:    {status.get('state', '?')}")
        lines.append(f"  StartsAt: {alert.get('startsAt', '')[:19]}")
        lines.append(f"  EndsAt:   {alert.get('endsAt', '')[:19]}")
        lines.append("  Labels:")
        for k, v in sorted(labels.items()):
            lines.append(f"    {k}: {v}")
        lines.append("  Annotations:")
        for k, v in sorted(annotations.items()):
            lines.append(f"    {k}: {v}")
        silenced_by = status.get("silencedBy", [])
        if silenced_by:
            lines.append(f"  SilencedBy: {', '.join(silenced_by)}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def list_alerting_rules(namespace: str = "", cluster: str = "") -> str:
    """List PrometheusRules (monitoring.coreos.com/v1) with rule group count."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PRULE, namespace=namespace)
        rows = []
        for rule in items:
            groups = rule.get("spec", {}).get("groups", [])
            rows.append([
                rule.get("metadata", {}).get("namespace", ""),
                rule.get("metadata", {}).get("name", ""),
                str(len(groups)),
                age_string(rule.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "GROUPS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_prometheus_rules(namespace: str = "", cluster: str = "") -> str:
    """List PrometheusRules with counts of alerting rules and recording rules per resource."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PRULE, namespace=namespace)
        rows = []
        for rule in items:
            groups = rule.get("spec", {}).get("groups", [])
            alerting = sum(1 for g in groups for r in g.get("rules", []) if "alert" in r)
            recording = sum(1 for g in groups for r in g.get("rules", []) if "record" in r)
            rows.append([
                rule.get("metadata", {}).get("namespace", ""),
                rule.get("metadata", {}).get("name", ""),
                str(len(groups)),
                str(alerting),
                str(recording),
                age_string(rule.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "GROUPS", "ALERTING", "RECORDING", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def query_prometheus(expr: str, cluster: str = "") -> str:
    """Execute a PromQL instant query against Thanos Querier and return results as a table."""
    try:
        data = _http_get(f"{_prom_url()}/api/v1/query", params={"query": expr})
    except Exception as exc:
        return f"Prometheus query failed: {exc}"

    result_type = data.get("data", {}).get("resultType", "")
    results = data.get("data", {}).get("result", [])
    if not results:
        return f"Query returned no results.\nExpr: {expr}"

    if result_type == "vector":
        rows = []
        for item in results:
            metric = item.get("metric", {})
            value = item.get("value", [None, "?"])[1]
            label_str = ", ".join(f"{k}={v}" for k, v in sorted(metric.items()))
            rows.append([label_str, str(value)])
        return f"Query: {expr}\nType: {result_type}\n\n" + format_table(["LABELS", "VALUE"], rows)
    elif result_type == "scalar":
        val = results[1] if isinstance(results, list) and len(results) > 1 else str(results)
        return f"Query: {expr}\nScalar: {val}"
    else:
        return f"Query: {expr}\nType: {result_type}\nResults:\n{results}"


@mcp.tool()
def query_prometheus_range(expr: str, start: str, end: str, step: str = "5m", cluster: str = "") -> str:
    """Execute a PromQL range query. start/end in ISO8601 or Unix timestamp; step e.g. '5m'."""
    import datetime

    try:
        data = _http_get(
            f"{_prom_url()}/api/v1/query_range",
            params={"query": expr, "start": start, "end": end, "step": step},
        )
    except Exception as exc:
        return f"Prometheus range query failed: {exc}"

    results = data.get("data", {}).get("result", [])
    if not results:
        return f"Range query returned no results.\nExpr: {expr}"

    lines = [f"Query: {expr}", f"Range: {start} -> {end}  step={step}", ""]
    for item in results:
        metric = item.get("metric", {})
        label_str = (", ".join(f"{k}={v}" for k, v in sorted(metric.items())) or "(scalar)")
        values = item.get("values", [])
        lines.append(f"Series: {label_str}  ({len(values)} points)")
        display = values if len(values) <= 10 else values[:5] + [["...", "..."]] + values[-5:]
        for ts, val in display:
            if ts != "...":
                dt = datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"  {dt}  {val}")
            else:
                lines.append("  ...")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def list_silences(cluster: str = "") -> str:
    """List Alertmanager silences with ID, state, matchers, comment, creator, and end time."""
    try:
        silences = _http_get(f"{_alertmanager_url()}/api/v2/silences")
    except Exception as exc:
        return f"Failed to reach Alertmanager: {exc}"

    rows = []
    for s in silences:
        matchers = s.get("matchers", [])
        matcher_str = ", ".join(
            f"{m.get('name', '')}{'=~' if m.get('isRegex') else '='}{m.get('value', '')}"
            for m in matchers
        )
        ends_at = s.get("endsAt", "")[:19].replace("T", " ")
        rows.append([
            s.get("id", "")[:12],
            s.get("status", {}).get("state", ""),
            matcher_str[:50],
            s.get("comment", "")[:40],
            s.get("createdBy", ""),
            ends_at,
        ])
    rows.sort(key=lambda r: r[1])
    return format_table(["ID", "STATE", "MATCHERS", "COMMENT", "CREATED-BY", "ENDS-AT"], rows)


@mcp.tool()
def create_silence(matchers: str, comment: str, duration_hours: float = 4, cluster: str = "") -> str:
    """Create an Alertmanager silence.
    matchers: comma-separated key=value or key=~regex pairs.
    Example: 'alertname=Watchdog,severity=~warning|critical'
    duration_hours: silence duration in hours (default 4)."""
    import datetime

    matcher_list = []
    for part in matchers.split(","):
        part = part.strip()
        if "=~" in part:
            k, v = part.split("=~", 1)
            matcher_list.append({"name": k.strip(), "value": v.strip(), "isRegex": True, "isEqual": True})
        elif "=" in part:
            k, v = part.split("=", 1)
            matcher_list.append({"name": k.strip(), "value": v.strip(), "isRegex": False, "isEqual": True})
        else:
            return f"Invalid matcher format: '{part}'. Expected key=value or key=~regex."

    now = datetime.datetime.utcnow()
    ends_at = now + datetime.timedelta(hours=duration_hours)
    body = {
        "matchers": matcher_list,
        "startsAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "endsAt": ends_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "createdBy": "ocp-mcp-server",
        "comment": comment,
    }

    try:
        result = _http_post(f"{_alertmanager_url()}/api/v2/silences", body)
        silence_id = result.get("silenceID", result.get("id", "?"))
        return (
            f"Silence created.\n"
            f"  ID:       {silence_id}\n"
            f"  Matchers: {matchers}\n"
            f"  Duration: {duration_hours}h\n"
            f"  Ends at:  {ends_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
    except Exception as exc:
        return f"Failed to create silence: {exc}"


@mcp.tool()
def delete_silence(silence_id: str, cluster: str = "") -> str:
    """Delete an Alertmanager silence by its ID."""
    try:
        _http_delete(f"{_alertmanager_url()}/api/v2/silence/{silence_id}")
        return f"Silence '{silence_id}' deleted."
    except Exception as exc:
        return f"Failed to delete silence '{silence_id}': {exc}"


@mcp.tool()
def get_monitoring_config(cluster: str = "") -> str:
    """Read the cluster-monitoring-config ConfigMap from the openshift-monitoring namespace."""
    ok, out = run_oc([
        "get", "configmap", "cluster-monitoring-config",
        "-n", "openshift-monitoring", "-o", "yaml",
    ])
    if ok:
        return out
    ok2, out2 = run_oc([
        "describe", "configmap", "cluster-monitoring-config",
        "-n", "openshift-monitoring",
    ])
    return out2 if ok2 else f"Error:\n{out}"
