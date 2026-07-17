"""Autoscaling tools: HPA, VPA, ClusterAutoscaler, MachineAutoscaler."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_HPA = ("autoscaling", "v2", "horizontalpodautoscalers")
_VPA = ("autoscaling.k8s.io", "v1", "verticalpodautoscalers")
_CA  = ("autoscaling.openshift.io", "v1", "clusterautoscalers")
_MA  = ("autoscaling.openshift.io", "v1beta1", "machineautoscalers")

_MA_NS = "openshift-machine-api"


def _hpa_metric_summary(metrics: list) -> str:
    """Return a short string summarising HPA metric specs."""
    parts = []
    for m in metrics[:3]:
        mtype = m.get("type", "?")
        if mtype == "Resource":
            res = m.get("resource", {})
            target = res.get("target", {})
            util = target.get("averageUtilization")
            val = target.get("averageValue", target.get("value"))
            desc = f"{res.get('name','?')}:{util}%" if util is not None else f"{res.get('name','?')}:{val}"
        elif mtype == "Pods":
            pods = m.get("pods", {})
            target = pods.get("metric", {}).get("name", "?")
            avg = pods.get("target", {}).get("averageValue", "?")
            desc = f"pods/{target}:{avg}"
        elif mtype == "External":
            ext = m.get("external", {})
            target = ext.get("metric", {}).get("name", "?")
            desc = f"ext/{target}"
        elif mtype == "Object":
            obj = m.get("object", {})
            target = obj.get("metric", {}).get("name", "?")
            desc = f"obj/{target}"
        else:
            desc = mtype
        parts.append(desc)
    return ", ".join(parts) if parts else "?"


@mcp.tool()
def list_hpas(namespace: str = "", cluster: str = "") -> str:
    """List HorizontalPodAutoscalers with min/max/current/desired replicas and metrics."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_HPA, namespace=namespace)
        rows = []
        for hpa in items:
            spec = hpa.get("spec", {})
            status = hpa.get("status", {})
            ref = spec.get("scaleTargetRef", {})
            target_ref = f"{ref.get('kind', '')}/{ref.get('name', '')}"
            metric_str = _hpa_metric_summary(spec.get("metrics", []))
            rows.append([
                hpa.get("metadata", {}).get("namespace", ""),
                hpa.get("metadata", {}).get("name", ""),
                target_ref,
                str(spec.get("minReplicas", 1)),
                str(spec.get("maxReplicas", "?")),
                str(status.get("currentReplicas", 0)),
                str(status.get("desiredReplicas", 0)),
                metric_str,
                age_string(hpa.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "REFERENCE", "MIN", "MAX", "CURRENT", "DESIRED", "METRICS", "AGE"],
            rows,
        )
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_hpa(
    name: str,
    namespace: str,
    target_ref: str,
    min_replicas: int,
    max_replicas: int,
    cpu_percent: int = 80,
    cluster: str = "",
) -> str:
    """Create an HPA using 'oc autoscale'.
    target_ref format: 'Deployment/my-app' or 'DeploymentConfig/my-dc'.
    cpu_percent: target CPU utilisation percentage (default 80)."""
    parts = target_ref.split("/", 1)
    if len(parts) != 2:
        return "target_ref must be in 'Kind/name' format, e.g. 'Deployment/my-app'."
    kind, obj_name = parts
    ok, out = run_oc([
        "autoscale", kind.lower(), obj_name,
        f"--name={name}",
        f"--min={min_replicas}",
        f"--max={max_replicas}",
        f"--cpu-percent={cpu_percent}",
        "-n", namespace,
    ])
    return out if ok else f"Error:\n{out}"


@mcp.tool()
def delete_hpa(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Delete a HorizontalPodAutoscaler."""
    c = get_client(cluster)
    try:
        c.delete_custom(*_HPA, name, namespace)
        return f"HPA '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_vpas(namespace: str = "", cluster: str = "") -> str:
    """List VerticalPodAutoscalers with update mode and target workload."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_VPA, namespace=namespace)
        rows = []
        for vpa in items:
            spec = vpa.get("spec", {})
            ref = spec.get("targetRef", {})
            target = f"{ref.get('kind', '')}/{ref.get('name', '')}"
            update_mode = spec.get("updatePolicy", {}).get("updateMode", "Auto")
            rows.append([
                vpa.get("metadata", {}).get("namespace", ""),
                vpa.get("metadata", {}).get("name", ""),
                update_mode,
                target,
                age_string(vpa.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "UPDATE-MODE", "TARGET", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_vpa_recommendation(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Show VPA recommendations per container: lowerBound/target/upperBound/uncappedTarget."""
    c = get_client(cluster)
    try:
        vpa = c.get_custom(*_VPA, name, namespace)
        spec = vpa.get("spec", {})
        status = vpa.get("status", {})
        ref = spec.get("targetRef", {})
        lines = [
            f"VPA: {namespace}/{name}",
            f"  Target:     {ref.get('kind', '')}/{ref.get('name', '')}",
            f"  UpdateMode: {spec.get('updatePolicy', {}).get('updateMode', 'Auto')}",
            "",
        ]
        recs = status.get("recommendation", {}).get("containerRecommendations", [])
        if not recs:
            lines.append("No recommendations available yet (VPA may still be observing).")
            return "\n".join(lines)
        for rec in recs:
            lines.append(f"Container: {rec.get('containerName', '?')}")
            for bound in ("lowerBound", "target", "upperBound", "uncappedTarget"):
                val = rec.get(bound, {})
                cpu = val.get("cpu", "?")
                mem = val.get("memory", "?")
                lines.append(f"  {bound:18s}: cpu={cpu}  memory={mem}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_cluster_autoscaler(cluster: str = "") -> str:
    """Get the ClusterAutoscaler 'default' resource limits and scale-down configuration."""
    c = get_client(cluster)
    try:
        ca = c.get_custom(*_CA, "default")
        spec = ca.get("spec", {})
        rl = spec.get("resourceLimits", {})
        sd = spec.get("scaleDown", {})
        lines = [
            "ClusterAutoscaler: default",
            "\nResource Limits:",
            f"  MaxNodesTotal: {rl.get('maxNodesTotal', '?')}",
        ]
        for resource_type, resource in rl.items():
            if resource_type == "maxNodesTotal":
                continue
            if isinstance(resource, dict):
                lines.append(
                    f"  {resource_type}: min={resource.get('min', '?')}  max={resource.get('max', '?')}"
                )
            elif isinstance(resource, list):
                for item in resource:
                    rtype = item.get("type", "?")
                    lines.append(
                        f"  {resource_type}/{rtype}: min={item.get('min', '?')}  max={item.get('max', '?')}"
                    )
        lines += [
            "\nScale Down:",
            f"  Enabled:            {sd.get('enabled', True)}",
            f"  DelayAfterAdd:      {sd.get('delayAfterAdd', '')}",
            f"  DelayAfterDelete:   {sd.get('delayAfterDelete', '')}",
            f"  DelayAfterFailure:  {sd.get('delayAfterFailure', '')}",
            f"  UnneededTime:       {sd.get('unneededTime', '')}",
            f"  UtilizationThresh:  {sd.get('utilizationThreshold', '')}",
            "\nOther:",
            f"  BalanceSimilarNodeGroups:  {spec.get('balanceSimilarNodeGroups', False)}",
            f"  SkipNodesWithLocalStorage: {spec.get('skipNodesWithLocalStorage', True)}",
            f"  LogVerbosity:              {spec.get('logVerbosity', 1)}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_machine_autoscalers(cluster: str = "") -> str:
    """List MachineAutoscalers in openshift-machine-api with target MachineSet, min, max, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MA, namespace=_MA_NS)
        rows = []
        for ma in items:
            spec = ma.get("spec", {})
            ref = spec.get("scaleTargetRef", {})
            rows.append([
                ma.get("metadata", {}).get("name", ""),
                ref.get("name", ""),
                str(spec.get("minReplicas", 0)),
                str(spec.get("maxReplicas", 0)),
                age_string(ma.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "TARGET", "MIN", "MAX", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_machine_autoscaler(
    name: str,
    machineset_name: str,
    min_replicas: int,
    max_replicas: int,
    cluster: str = "",
) -> str:
    """Create a MachineAutoscaler CR targeting a MachineSet in openshift-machine-api.
    Requires a ClusterAutoscaler to be configured for this to take effect."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "autoscaling.openshift.io/v1beta1",
            "kind": "MachineAutoscaler",
            "metadata": {"name": name, "namespace": _MA_NS},
            "spec": {
                "minReplicas": min_replicas,
                "maxReplicas": max_replicas,
                "scaleTargetRef": {
                    "apiVersion": "machine.openshift.io/v1beta1",
                    "kind": "MachineSet",
                    "name": machineset_name,
                },
            },
        }
        c.create_custom(*_MA, body, _MA_NS)
        return (
            f"MachineAutoscaler '{name}' created targeting MachineSet '{machineset_name}' "
            f"(min={min_replicas}, max={max_replicas})."
        )
    except Exception as e:
        return format_error(e)
