"""OLM operator tools: CSVs, Subscriptions, CatalogSources, OperatorGroups, InstallPlans."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_CSV = ("operators.coreos.com", "v1alpha1", "clusterserviceversions")
_SUB = ("operators.coreos.com", "v1alpha1", "subscriptions")
_CS  = ("operators.coreos.com", "v1alpha1", "catalogsources")
_OG  = ("operators.coreos.com", "v1",       "operatorgroups")
_IP  = ("operators.coreos.com", "v1alpha1", "installplans")
_OC  = ("operators.coreos.com", "v2",       "operatorconditions")


@mcp.tool()
def list_installed_operators(namespace: str = "", cluster: str = "") -> str:
    """List installed operators (ClusterServiceVersions) with display name, version, and phase."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_CSV, namespace=namespace)
        rows = []
        for csv in items:
            meta = csv.get("metadata", {})
            spec = csv.get("spec", {})
            status = csv.get("status", {})
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                spec.get("displayName", ""),
                spec.get("version", ""),
                status.get("phase", "?"),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "DISPLAY-NAME", "VERSION", "PHASE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_operator_status(name: str, namespace: str = "", cluster: str = "") -> str:
    """Get ClusterServiceVersion status: phase, conditions, and owned CRDs.
    If namespace is empty, all namespaces are searched for a CSV whose name matches."""
    c = get_client(cluster)
    try:
        csv: dict | None = None
        resolved_ns = namespace
        if namespace:
            csv = c.get_custom(*_CSV, name, namespace)
        else:
            all_csvs = c.list_custom(*_CSV, namespace="")
            for item in all_csvs:
                item_name = item.get("metadata", {}).get("name", "")
                if item_name == name or item_name.startswith(name + "."):
                    csv = item
                    resolved_ns = item.get("metadata", {}).get("namespace", "")
                    break
            if csv is None:
                return f"ClusterServiceVersion '{name}' not found in any namespace."

        spec = csv.get("spec", {})
        status = csv.get("status", {})
        actual_name = csv.get("metadata", {}).get("name", name)
        lines = [
            f"CSV: {resolved_ns}/{actual_name}",
            f"  DisplayName: {spec.get('displayName', '')}",
            f"  Version:     {spec.get('version', '')}",
            f"  Phase:       {status.get('phase', '?')}",
            f"  Reason:      {status.get('reason', '')}",
            f"  Message:     {status.get('message', '')}",
            "\nConditions:",
        ]
        for cond in (status.get("conditions") or []):
            cond_status = cond.get("phase") or cond.get("status", "?")
            msg = (cond.get("message") or "")[:60]
            lines.append(f"  {cond.get('type', ''):42s} {cond_status:12s} {msg}")

        owned_crds = spec.get("customresourcedefinitions", {}).get("owned") or []
        if owned_crds:
            lines.append("\nOwned CRDs:")
            for crd in owned_crds:
                lines.append(
                    f"  {crd.get('name', ''):<50s} kind={crd.get('kind', '')} version={crd.get('version', '')}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_subscriptions(namespace: str = "", cluster: str = "") -> str:
    """List OLM Subscriptions with package, channel, source, current CSV, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SUB, namespace=namespace)
        rows = []
        for sub in items:
            meta = sub.get("metadata", {})
            spec = sub.get("spec", {})
            status = sub.get("status", {})
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                spec.get("name", ""),
                spec.get("channel", ""),
                spec.get("source", ""),
                status.get("currentCSV", ""),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "PACKAGE", "CHANNEL", "SOURCE", "CURRENT-CSV", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_subscription(
    name: str,
    namespace: str,
    package: str,
    channel: str,
    source: str,
    source_namespace: str = "openshift-marketplace",
    install_mode: str = "OwnNamespace",
    cluster: str = "",
) -> str:
    """Create an OLM Subscription to install an operator from a CatalogSource.
    install_mode is informational only (set via OperatorGroup, not Subscription spec)."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "operators.coreos.com/v1alpha1",
            "kind": "Subscription",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "name": package,
                "channel": channel,
                "source": source,
                "sourceNamespace": source_namespace,
                "installPlanApproval": "Automatic",
            },
        }
        c.create_custom(*_SUB, body, namespace)
        return (f"Subscription '{namespace}/{name}' created: "
                f"package={package} channel={channel} "
                f"source={source}/{source_namespace}.")
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_subscription(
    name: str,
    namespace: str = "default",
    also_delete_csv: bool = False,
    cluster: str = "",
) -> str:
    """Delete an OLM Subscription.
    Set also_delete_csv=True to also remove the currently installed CSV."""
    c = get_client(cluster)
    try:
        current_csv = ""
        if also_delete_csv:
            try:
                sub = c.get_custom(*_SUB, name, namespace)
                current_csv = sub.get("status", {}).get("currentCSV", "")
            except Exception:
                pass

        c.delete_custom(*_SUB, name, namespace)
        result = f"Subscription '{namespace}/{name}' deleted."

        if also_delete_csv and current_csv:
            try:
                c.delete_custom(*_CSV, current_csv, namespace)
                result += f"\nCSV '{namespace}/{current_csv}' deleted."
            except Exception as csv_err:
                result += f"\nWarning: failed to delete CSV '{current_csv}': {csv_err}"
        return result
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_catalog_sources(namespace: str = "", cluster: str = "") -> str:
    """List CatalogSources with display name, type, publisher, and connection state."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_CS, namespace=namespace)
        rows = []
        for cs in items:
            meta = cs.get("metadata", {})
            spec = cs.get("spec", {})
            status = cs.get("status", {})
            state = status.get("connectionState", {}).get("lastObservedState", "?")
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                spec.get("displayName", ""),
                spec.get("sourceType", ""),
                spec.get("publisher", ""),
                state,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "DISPLAY-NAME", "TYPE", "PUBLISHER", "STATE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_operator_groups(namespace: str = "", cluster: str = "") -> str:
    """List OperatorGroups with their target namespaces and service account."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_OG, namespace=namespace)
        rows = []
        for og in items:
            meta = og.get("metadata", {})
            spec = og.get("spec", {})
            target_ns = spec.get("targetNamespaces") or []
            ns_str = ",".join(target_ns) if target_ns else "(all namespaces)"
            svc_acct = spec.get("serviceAccountName", "")
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                ns_str[:60],
                svc_acct,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "TARGET-NAMESPACES", "SERVICE-ACCOUNT", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_install_plans(namespace: str = "", cluster: str = "") -> str:
    """List InstallPlans with approval mode, approved status, phase, and CSV names."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_IP, namespace=namespace)
        rows = []
        for ip in items:
            meta = ip.get("metadata", {})
            spec = ip.get("spec", {})
            status = ip.get("status", {})
            csvs = ",".join(spec.get("clusterServiceVersionNames") or [])
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                spec.get("approval", "?"),
                str(spec.get("approved", False)),
                status.get("phase", "?"),
                csvs[:60],
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "APPROVAL", "APPROVED", "PHASE", "CSVs", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def approve_install_plan(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Approve a Manual InstallPlan by patching spec.approved=True."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_IP, name, {"spec": {"approved": True}}, namespace)
        return f"InstallPlan '{namespace}/{name}' approved."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_operator_conditions(namespace: str = "", cluster: str = "") -> str:
    """List OperatorConditions (operators.coreos.com/v2) with active condition summary."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_OC, namespace=namespace)
        rows = []
        for oc_item in items:
            meta = oc_item.get("metadata", {})
            conditions = oc_item.get("spec", {}).get("conditions") or []
            # Conditions with status=True are actively triggered
            active = [cond.get("type", "") for cond in conditions
                      if cond.get("status") == "True"]
            summary = ",".join(active[:3]) + ("..." if len(active) > 3 else "") if active else "OK"
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                str(len(conditions)),
                summary,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "CONDITIONS", "ACTIVE", "AGE"], rows)
    except Exception as e:
        return format_error(e)
