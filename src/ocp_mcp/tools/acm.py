"""ACM / Multi-cluster Management tools: ManagedClusters, Policies, Placements, ManifestWorks."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client

_MC = ("cluster.open-cluster-management.io", "v1", "managedclusters")
_MCS = ("cluster.open-cluster-management.io", "v1beta2", "managedclustersets")
_PLACE = ("cluster.open-cluster-management.io", "v1beta1", "placements")
_PLACED = ("cluster.open-cluster-management.io", "v1beta1", "placementdecisions")
_MW = ("work.open-cluster-management.io", "v1", "manifestworks")
_POL = ("policy.open-cluster-management.io", "v1", "policies")
_CC = ("cluster.open-cluster-management.io", "v1alpha1", "clusterclaims")
_ADDON = ("addon.open-cluster-management.io", "v1alpha1", "managedclusteraddons")


@mcp.tool()
def list_managed_clusters(cluster: str = "") -> str:
    """List ACM ManagedClusters with status, OCP version, cloud provider, and region."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MC)
        rows = []
        for mc in items:
            labels = mc.get("metadata", {}).get("labels", {})
            conditions = mc.get("status", {}).get("conditions", [])
            available = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "ManagedClusterConditionAvailable"), "?")
            rows.append([mc.get("metadata", {}).get("name", ""),
                         available,
                         labels.get("openshiftVersion", labels.get("open-cluster-management.io/version", "")),
                         labels.get("cloud", ""),
                         labels.get("region", ""),
                         labels.get("clusterID", "")[:12],
                         age_string(mc.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "AVAILABLE", "OCP-VERSION", "CLOUD", "REGION", "CLUSTER-ID", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_managed_cluster(name: str, cluster: str = "") -> str:
    """Get detailed ManagedCluster info: capacity, conditions, labels."""
    c = get_client(cluster)
    try:
        mc = c.get_custom(*_MC, name)
        status = mc.get("status", {})
        labels = mc.get("metadata", {}).get("labels", {})
        cap = status.get("capacity", {})
        alloc = status.get("allocatable", {})
        lines = [f"ManagedCluster: {name}",
                 f"  CPU:        cap={cap.get('cpu','?')}  alloc={alloc.get('cpu','?')}",
                 f"  Memory:     cap={cap.get('memory','?')}  alloc={alloc.get('memory','?')}",
                 f"  OCP:        {labels.get('openshiftVersion','')}",
                 f"  Cloud:      {labels.get('cloud','')}  Region={labels.get('region','')}",
                 f"  ClusterSet: {labels.get('cluster.open-cluster-management.io/clusterset','')}",
                 "\nConditions:"]
        for cond in status.get("conditions", []):
            lines.append(f"  {cond.get('type',''):45s} {cond.get('status','?'):8s} "
                         f"[{age_string(cond.get('lastTransitionTime'))}]")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_cluster_sets(cluster: str = "") -> str:
    """List ACM ManagedClusterSets."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MCS)
        rows = []
        for mcs in items:
            status = mcs.get("status", {})
            conditions = status.get("conditions", [])
            empty = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "ManagedClusterSetEmpty"), "?")
            rows.append([mcs.get("metadata", {}).get("name", ""),
                         empty, age_string(mcs.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "EMPTY", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_cluster_claims(cluster: str = "") -> str:
    """List ACM ClusterClaims with pool and resolved cluster."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_CC)
        rows = []
        for cc in items:
            spec = cc.get("spec", {})
            status = cc.get("status", {})
            rows.append([cc.get("metadata", {}).get("name", ""),
                         spec.get("clusterPoolName", ""),
                         status.get("conditions", [{}])[0].get("type", "?") if status.get("conditions") else "?",
                         age_string(cc.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "POOL", "CONDITION", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_placements(namespace: str = "", cluster: str = "") -> str:
    """List ACM Placements with predicates and satisfaction status."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PLACE, namespace=namespace)
        rows = []
        for p in items:
            spec = p.get("spec", {})
            status = p.get("status", {})
            desired = spec.get("numberOfClusters", "?")
            selected = status.get("numberOfSelectedClusters", 0)
            satisfied = next((c2.get("status","?") for c2 in status.get("conditions",[])
                              if c2.get("type") == "PlacementSatisfied"), "?")
            rows.append([p.get("metadata", {}).get("namespace", ""),
                         p.get("metadata", {}).get("name", ""),
                         str(desired), str(selected), satisfied,
                         age_string(p.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "DESIRED", "SELECTED", "SATISFIED", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_placement_decisions(placement_name: str, namespace: str, cluster: str = "") -> str:
    """List PlacementDecisions for a Placement showing selected clusters."""
    c = get_client(cluster)
    try:
        label = f"cluster.open-cluster-management.io/placement={placement_name}"
        items = c.list_custom(*_PLACED, namespace=namespace, label_selector=label)
        all_clusters = []
        for pd in items:
            for decision in pd.get("status", {}).get("decisions", []):
                all_clusters.append(decision.get("clusterName", ""))
        if not all_clusters:
            return f"No PlacementDecisions found for Placement '{placement_name}'."
        return (f"Placement '{namespace}/{placement_name}' selected {len(all_clusters)} cluster(s):\n"
                + "\n".join(f"  - {c2}" for c2 in sorted(all_clusters)))
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_policies(namespace: str = "", cluster: str = "") -> str:
    """List ACM Policies with remediation action and compliance status."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_POL, namespace=namespace)
        rows = []
        for pol in items:
            spec = pol.get("spec", {})
            status = pol.get("status", {})
            rows.append([pol.get("metadata", {}).get("namespace", ""),
                         pol.get("metadata", {}).get("name", ""),
                         spec.get("remediationAction", "?"),
                         str(spec.get("disabled", False)),
                         status.get("compliantStatus", "?"),
                         age_string(pol.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "REMEDIATION", "DISABLED", "COMPLIANCE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_policy_compliance(name: str, namespace: str, cluster: str = "") -> str:
    """Show per-cluster compliance status for an ACM Policy."""
    c = get_client(cluster)
    try:
        pol = c.get_custom(*_POL, name, namespace)
        status = pol.get("status", {})
        cluster_compliance = status.get("status", [])
        rows = []
        for cc in cluster_compliance:
            rows.append([cc.get("clustername", ""),
                         cc.get("clusternamespace", ""),
                         cc.get("compliant", "?")])
        return (f"Policy: {namespace}/{name}\n"
                f"Overall: {status.get('compliantStatus','?')}\n\n"
                + format_table(["CLUSTER", "NAMESPACE", "COMPLIANT"], rows))
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_manifest_works(cluster_name: str, cluster: str = "") -> str:
    """List ManifestWorks deployed to a ManagedCluster (namespace=cluster_name)."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MW, namespace=cluster_name)
        rows = []
        for mw in items:
            manifests = mw.get("spec", {}).get("workload", {}).get("manifests", [])
            status = mw.get("status", {})
            conditions = status.get("conditions", [])
            applied = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Applied"), "?")
            rows.append([mw.get("metadata", {}).get("name", ""),
                         str(len(manifests)), applied,
                         age_string(mw.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "MANIFESTS", "APPLIED", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_manifest_work(name: str, cluster_name: str, manifests_yaml: str, cluster: str = "") -> str:
    """Create a ManifestWork to deploy resources to a ManagedCluster."""
    c = get_client(cluster)
    try:
        import yaml
        raw_manifests = [m for m in yaml.safe_load_all(manifests_yaml) if m is not None]
        if not raw_manifests:
            return "Error: manifests_yaml contains no valid YAML documents. ManifestWork not created."
        body = {
            "apiVersion": "work.open-cluster-management.io/v1",
            "kind": "ManifestWork",
            "metadata": {"name": name, "namespace": cluster_name},
            "spec": {"workload": {"manifests": raw_manifests}},
        }
        c.create_custom(*_MW, body, cluster_name)
        return f"ManifestWork '{cluster_name}/{name}' created with {len(raw_manifests)} manifest(s)."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_managed_cluster_addons(cluster_name: str, cluster: str = "") -> str:
    """List ManagedClusterAddons on a specific managed cluster."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_ADDON, namespace=cluster_name)
        rows = []
        for addon in items:
            conditions = addon.get("status", {}).get("conditions", [])
            available = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Available"), "?")
            degraded = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Degraded"), "False")
            rows.append([addon.get("metadata", {}).get("name", ""),
                         available, degraded,
                         age_string(addon.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "AVAILABLE", "DEGRADED", "AGE"], rows)
    except Exception as e:
        return format_error(e)
