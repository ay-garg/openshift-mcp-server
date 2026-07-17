"""
OpenShift cluster-level MCP tools.

Covers: ClusterVersion, ClusterOperators, Infrastructure, Network config,
Nodes, Namespaces, Events, ETCD status, and cluster context management.
"""

from __future__ import annotations

from datetime import datetime, timezone

from kubernetes import client as k8s_client

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, list_clusters, run_oc


# ---------------------------------------------------------------------------
# Cluster info / version
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cluster_info(cluster: str = "") -> str:
    """Get high-level cluster information: name, API URL, version, channel, and platform type."""
    try:
        c = get_client(cluster)

        # ClusterVersion (cluster-scoped, singleton named "version")
        cv = c.get_custom("config.openshift.io", "v1", "clusterversions", "version")
        cv_spec = cv.get("spec", {})
        cv_status = cv.get("status", {})
        desired = cv_status.get("desired", {})
        conditions = cv_status.get("conditions", [])

        def _cond(ctype: str) -> dict:
            return next((x for x in conditions if x.get("type") == ctype), {})

        available = _cond("Available")
        progressing = _cond("Progressing")
        degraded = _cond("Degraded")

        # Infrastructure (cluster-scoped, singleton named "cluster")
        infra = c.get_custom("config.openshift.io", "v1", "infrastructures", "cluster")
        infra_status = infra.get("status", {})
        infra_spec = infra.get("spec", {})

        platform_type = infra_status.get(
            "platformStatus", {}
        ).get("type") or infra_spec.get("platformSpec", {}).get("type", "unknown")

        lines = [
            "=== Cluster Information ===",
            f"  Cluster Name    : {infra_status.get('infrastructureName', 'unknown')}",
            f"  Cluster ID      : {cv_spec.get('clusterID', cv_status.get('clusterID', 'unknown'))}",
            f"  API Server URL  : {infra_status.get('apiServerURL', 'unknown')}",
            f"  Platform        : {platform_type}",
            f"  OCP Version     : {desired.get('version', 'unknown')}",
            f"  Channel         : {cv_spec.get('channel', 'unknown')}",
        ]
        console_url = infra_status.get("consoleURL", "")
        if console_url:
            lines.append(f"  Console URL     : {console_url}")

        lines += [
            "",
            "=== Cluster Health ===",
            f"  Available   : {available.get('status', 'Unknown')} — {available.get('message', '')}",
            f"  Progressing : {progressing.get('status', 'Unknown')} — {progressing.get('message', '')}",
            f"  Degraded    : {degraded.get('status', 'Unknown')} — {degraded.get('message', '')}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting cluster info: {format_error(exc)}"


@mcp.tool()
def get_cluster_version(cluster: str = "") -> str:
    """Show ClusterVersion history, conditions (Available/Progressing/Degraded), and available updates."""
    try:
        c = get_client(cluster)
        cv = c.get_custom("config.openshift.io", "v1", "clusterversions", "version")
        cv_spec = cv.get("spec", {})
        cv_status = cv.get("status", {})
        desired = cv_status.get("desired", {})

        lines = [
            "=== Cluster Version ===",
            f"  Desired Version : {desired.get('version', 'unknown')}",
            f"  Channel         : {cv_spec.get('channel', 'unknown')}",
            f"  Image           : {desired.get('image', 'unknown')}",
            "",
            "=== Conditions ===",
        ]

        conditions = cv_status.get("conditions", [])
        for ctype in ("Available", "Progressing", "Degraded", "RetrievedUpdates", "Invalid"):
            cond = next((x for x in conditions if x.get("type") == ctype), None)
            if cond:
                status_val = cond.get("status", "Unknown")
                since = age_string(cond.get("lastTransitionTime"))
                lines.append(f"  {ctype:<22} {status_val:<8} (since {since})")
                msg = cond.get("message", "").strip()
                for part in msg.split("\n")[:3]:
                    if part.strip():
                        lines.append(f"    {part.strip()[:120]}")

        lines += ["", "=== Update History (most recent 5) ==="]
        history = cv_status.get("history", [])
        h_rows = []
        for entry in history[:5]:
            comp = entry.get("completionTime", "")
            h_rows.append([
                entry.get("version", ""),
                entry.get("state", ""),
                str(entry.get("verified", False)),
                age_string(comp) if comp else "in progress",
            ])
        lines.append(format_table(["VERSION", "STATE", "VERIFIED", "COMPLETED"], h_rows))

        lines += ["", "=== Available Updates ==="]
        updates = cv_status.get("availableUpdates") or []
        if updates:
            for u in updates:
                lines.append(f"  {u.get('version', 'unknown')}  (channel: {u.get('channel', '')})")
        else:
            lines.append("  None available (or not yet retrieved).")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting cluster version: {format_error(exc)}"


# ---------------------------------------------------------------------------
# ClusterOperators
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cluster_operators(cluster: str = "") -> str:
    """List all ClusterOperators with Available/Progressing/Degraded/Version columns; degraded operators are listed first."""
    try:
        c = get_client(cluster)
        items = c.list_custom("config.openshift.io", "v1", "clusteroperators")

        def _cond_status(conditions: list, ctype: str) -> str:
            for cond in conditions:
                if cond.get("type") == ctype:
                    return cond.get("status", "Unknown")
            return "Unknown"

        def _operator_version(versions: list) -> str:
            for v in versions:
                if v.get("name") == "operator":
                    return v.get("version", "")
            return versions[0].get("version", "") if versions else ""

        rows = []
        for item in items:
            name = item.get("metadata", {}).get("name", "")
            conditions = item.get("status", {}).get("conditions", [])
            versions = item.get("status", {}).get("versions", [])
            available = _cond_status(conditions, "Available")
            progressing = _cond_status(conditions, "Progressing")
            degraded = _cond_status(conditions, "Degraded")
            version = _operator_version(versions)
            rows.append((name, available, progressing, degraded, version))

        # Degraded=True first, then alphabetical
        rows.sort(key=lambda r: (0 if r[3] == "True" else 1, r[0]))

        headers = ["NAME", "AVAILABLE", "PROGRESSING", "DEGRADED", "VERSION"]
        table = format_table(headers, rows, max_col=50)

        degraded_count = sum(1 for r in rows if r[3] == "True")
        progressing_count = sum(1 for r in rows if r[2] == "True")
        unavailable_count = sum(1 for r in rows if r[1] != "True")
        summary = (
            f"\nTotal: {len(rows)}  |  Degraded: {degraded_count}  |  "
            f"Progressing: {progressing_count}  |  Unavailable: {unavailable_count}"
        )
        return table + summary
    except Exception as exc:
        return f"Error listing cluster operators: {format_error(exc)}"


@mcp.tool()
def get_cluster_operator_details(name: str, cluster: str = "") -> str:
    """Get detailed conditions, versions, and related objects for a single ClusterOperator."""
    try:
        c = get_client(cluster)
        co = c.get_custom("config.openshift.io", "v1", "clusteroperators", name)
        status = co.get("status", {})

        lines = [f"=== ClusterOperator: {name} ===", "", "=== Versions ==="]
        versions = status.get("versions", [])
        if versions:
            for v in versions:
                lines.append(f"  {v.get('name', ''):<24} {v.get('version', '')}")
        else:
            lines.append("  (no version info)")

        lines += ["", "=== Conditions ==="]
        conditions = status.get("conditions", [])
        for cond in conditions:
            ctype = cond.get("type", "")
            cstatus = cond.get("status", "")
            reason = cond.get("reason", "")
            msg = cond.get("message", "").strip()
            since = age_string(cond.get("lastTransitionTime"))
            lines.append(f"  Type     : {ctype}")
            lines.append(f"  Status   : {cstatus}  (since {since})")
            if reason:
                lines.append(f"  Reason   : {reason}")
            if msg:
                for part in msg.split("\n")[:5]:
                    if part.strip():
                        lines.append(f"  Message  : {part.strip()[:160]}")
            lines.append("")

        related = status.get("relatedObjects", [])
        if related:
            lines.append("=== Related Objects ===")
            rel_rows = [
                [
                    obj.get("group", ""),
                    obj.get("resource", ""),
                    obj.get("namespace", ""),
                    obj.get("name", ""),
                ]
                for obj in related
            ]
            lines.append(format_table(["GROUP", "RESOURCE", "NAMESPACE", "NAME"], rel_rows, max_col=40))

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting cluster operator '{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Infrastructure / Network
# ---------------------------------------------------------------------------

@mcp.tool()
def get_infrastructure_config(cluster: str = "") -> str:
    """Get Infrastructure and Network configuration CRDs from config.openshift.io/v1."""
    try:
        c = get_client(cluster)
        lines: list[str] = []

        # --- Infrastructure ---
        try:
            infra = c.get_custom("config.openshift.io", "v1", "infrastructures", "cluster")
            infra_status = infra.get("status", {})
            infra_spec = infra.get("spec", {})
            platform_status = infra_status.get("platformStatus", {})
            platform_type = platform_status.get("type") or infra_spec.get("platformSpec", {}).get("type", "unknown")

            lines += [
                "=== Infrastructure ===",
                f"  Infrastructure Name    : {infra_status.get('infrastructureName', 'unknown')}",
                f"  Platform Type          : {platform_type}",
                f"  API Server URL         : {infra_status.get('apiServerURL', 'unknown')}",
                f"  API Server Internal URL: {infra_status.get('apiServerInternalURL', 'unknown')}",
                f"  Control Plane Topology : {infra_status.get('controlPlaneTopology', 'unknown')}",
                f"  Infra Topology         : {infra_status.get('infrastructureTopology', 'unknown')}",
            ]

            # Platform-specific details
            if platform_type == "AWS":
                aws = platform_status.get("aws", {})
                lines.append(f"  AWS Region             : {aws.get('region', 'unknown')}")
            elif platform_type == "GCP":
                gcp = platform_status.get("gcp", {})
                lines.append(f"  GCP Region             : {gcp.get('region', 'unknown')}")
                lines.append(f"  GCP Project            : {gcp.get('projectID', 'unknown')}")
            elif platform_type == "Azure":
                azure = platform_status.get("azure", {})
                lines.append(f"  Azure Cloud Name       : {azure.get('cloudName', 'unknown')}")
                lines.append(f"  Azure Resource Group   : {azure.get('resourceGroupName', 'unknown')}")
            elif platform_type == "vSphere":
                vsphere = platform_status.get("vsphere", {})
                api_vips = vsphere.get("apiServerInternalIPs", [])
                lines.append(f"  vSphere API VIPs       : {', '.join(api_vips)}")
            elif platform_type == "BareMetal":
                bm = platform_status.get("baremetal", {})
                api_vips = bm.get("apiServerInternalIPs", [])
                lines.append(f"  BareMetal API VIPs     : {', '.join(api_vips)}")
            lines.append("")
        except Exception as exc:
            lines += [f"Infrastructure: {format_error(exc)}", ""]

        # --- Network ---
        try:
            network = c.get_custom("config.openshift.io", "v1", "networks", "cluster")
            net_spec = network.get("spec", {})
            net_status = network.get("status", {})

            lines += [
                "=== Network Configuration ===",
                f"  Network Type           : {net_status.get('networkType') or net_spec.get('networkType', 'unknown')}",
            ]
            for cn in net_status.get("clusterNetwork") or net_spec.get("clusterNetwork", []):
                lines.append(
                    f"  Cluster Network        : {cn.get('cidr', '')}  (hostPrefix /{cn.get('hostPrefix', '')})"
                )
            for sn in net_status.get("serviceNetwork") or net_spec.get("serviceNetwork", []):
                lines.append(f"  Service Network        : {sn}")
            for mc in net_spec.get("machineNetwork", []):
                lines.append(f"  Machine Network        : {mc.get('cidr', '')}")
        except Exception as exc:
            lines += [f"Network config: {format_error(exc)}"]

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting infrastructure config: {format_error(exc)}"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@mcp.tool()
def list_nodes(label_selector: str = "", cluster: str = "") -> str:
    """List all nodes with ROLES, STATUS, OS image, KUBELET version, and AGE."""
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector
        nodes = c.core_v1.list_node(**kwargs)

        headers = ["NAME", "ROLES", "STATUS", "OS", "KUBELET", "AGE"]
        rows = []
        for node in nodes.items:
            labels = node.metadata.labels or {}
            roles = sorted(
                k.split("/", 1)[1]
                for k in labels
                if k.startswith("node-role.kubernetes.io/")
            )
            roles_str = ",".join(roles) or "<none>"

            conditions = node.status.conditions or []
            ready = next((cd for cd in conditions if cd.type == "Ready"), None)
            if ready:
                status_str = "Ready" if ready.status == "True" else "NotReady"
            else:
                status_str = "Unknown"
            if node.spec.unschedulable:
                status_str += ",SchedulingDisabled"

            ni = node.status.node_info
            os_image = ni.os_image if ni else "unknown"
            kubelet = ni.kubelet_version if ni else "unknown"
            age = age_string(node.metadata.creation_timestamp)

            rows.append([node.metadata.name, roles_str, status_str, os_image, kubelet, age])

        if not rows:
            return "No nodes found."
        return format_table(headers, rows, max_col=45)
    except Exception as exc:
        return f"Error listing nodes: {format_error(exc)}"


@mcp.tool()
def get_node(name: str, cluster: str = "") -> str:
    """Get capacity, allocatable resources, conditions, and taints for a node."""
    try:
        c = get_client(cluster)
        node = c.core_v1.read_node(name)

        metadata = node.metadata
        spec = node.spec
        status = node.status
        labels = metadata.labels or {}
        ni = status.node_info

        roles = sorted(
            k.split("/", 1)[1]
            for k in labels
            if k.startswith("node-role.kubernetes.io/")
        )

        lines = [
            f"=== Node: {name} ===",
            f"  Roles     : {', '.join(roles) or '<none>'}",
            f"  Age       : {age_string(metadata.creation_timestamp)}",
        ]

        if ni:
            lines += [
                "",
                "=== Node Info ===",
                f"  OS Image            : {ni.os_image}",
                f"  OS                  : {ni.operating_system}",
                f"  Architecture        : {ni.architecture}",
                f"  Kernel Version      : {ni.kernel_version}",
                f"  Container Runtime   : {ni.container_runtime_version}",
                f"  Kubelet Version     : {ni.kubelet_version}",
                f"  Kube-Proxy Version  : {ni.kube_proxy_version}",
            ]

        # Addresses
        addresses = status.addresses or []
        if addresses:
            lines += ["", "=== Addresses ==="]
            for addr in addresses:
                lines.append(f"  {addr.type:<20} {addr.address}")

        # Resources
        capacity = status.capacity or {}
        allocatable = status.allocatable or {}
        all_resources = sorted(set(list(capacity.keys()) + list(allocatable.keys())))
        res_rows = [
            [res, capacity.get(res, "-"), allocatable.get(res, "-")]
            for res in all_resources
        ]
        lines += ["", "=== Resources ==="]
        lines.append(format_table(["RESOURCE", "CAPACITY", "ALLOCATABLE"], res_rows))

        # Conditions
        conditions = status.conditions or []
        cond_rows = [
            [cd.type, cd.status, cd.reason or "", age_string(cd.last_transition_time)]
            for cd in conditions
        ]
        lines += ["", "=== Conditions ==="]
        lines.append(format_table(["TYPE", "STATUS", "REASON", "AGE"], cond_rows))

        # Taints
        taints = spec.taints or []
        if taints:
            lines += ["", "=== Taints ==="]
            for t in taints:
                val_part = f"={t.value}" if t.value else ""
                lines.append(f"  {t.key}{val_part}:{t.effect}")

        # Key labels
        key_labels = {
            k: v for k, v in labels.items()
            if any(x in k for x in ("node-role", "topology", "node.kubernetes.io", "kubernetes.io/hostname"))
        }
        if key_labels:
            lines += ["", "=== Key Labels ==="]
            for k, v in sorted(key_labels.items()):
                lines.append(f"  {k}={v}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting node '{name}': {format_error(exc)}"


@mcp.tool()
def cordon_node(name: str, cluster: str = "") -> str:
    """Cordon a node so that no new pods are scheduled on it."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "cordon", name])
        if ok:
            return f"Node '{name}' cordoned successfully.\n{out.strip()}"
        return f"Failed to cordon node '{name}':\n{out}"
    except Exception as exc:
        return f"Error cordoning node '{name}': {format_error(exc)}"


@mcp.tool()
def uncordon_node(name: str, cluster: str = "") -> str:
    """Uncordon a node to allow new pods to be scheduled on it again."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "uncordon", name])
        if ok:
            return f"Node '{name}' uncordoned successfully.\n{out.strip()}"
        return f"Failed to uncordon node '{name}':\n{out}"
    except Exception as exc:
        return f"Error uncordoning node '{name}': {format_error(exc)}"


@mcp.tool()
def drain_node(
    name: str,
    ignore_daemonsets: bool = True,
    delete_emptydir_data: bool = False,
    force: bool = False,
    grace_period: int = -1,
    cluster: str = "",
) -> str:
    """
    Drain a node by evicting all evictable pods (cordons the node first).

    Args:
        name: Name of the node to drain.
        ignore_daemonsets: Ignore DaemonSet-managed pods (default True).
        delete_emptydir_data: Allow deletion of pods with emptyDir volumes (default False).
        force: Force eviction of pods not managed by a controller (default False).
        grace_period: Seconds for graceful termination; -1 uses pod default.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        args = c.oc_args() + ["adm", "drain", name]

        if ignore_daemonsets:
            args.append("--ignore-daemonsets=true")
        if delete_emptydir_data:
            args.append("--delete-emptydir-data=true")
        if force:
            args.append("--force=true")
        if grace_period >= 0:
            args += ["--grace-period", str(grace_period)]

        ok, out = run_oc(args, timeout=300)
        if ok:
            return f"Node '{name}' drained successfully.\n{out.strip()}"
        return f"Failed to drain node '{name}':\n{out}"
    except Exception as exc:
        return f"Error draining node '{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------

@mcp.tool()
def list_namespaces(label_selector: str = "", cluster: str = "") -> str:
    """List all namespaces with STATUS, LABELS, and AGE."""
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector
        namespaces = c.core_v1.list_namespace(**kwargs)

        headers = ["NAME", "STATUS", "LABELS", "AGE"]
        rows = []
        for ns in namespaces.items:
            labels = ns.metadata.labels or {}
            # Exclude the default kubernetes.io/metadata.name label from the display
            display_labels = {k: v for k, v in labels.items() if k != "kubernetes.io/metadata.name"}
            labels_str = ",".join(f"{k}={v}" for k, v in list(display_labels.items())[:3])
            phase = ns.status.phase if ns.status else "Unknown"
            age = age_string(ns.metadata.creation_timestamp)
            rows.append([ns.metadata.name, phase, labels_str, age])

        if not rows:
            return "No namespaces found."
        return format_table(headers, rows, max_col=60)
    except Exception as exc:
        return f"Error listing namespaces: {format_error(exc)}"


@mcp.tool()
def create_namespace(name: str, labels: str = "", cluster: str = "") -> str:
    """
    Create a new namespace, optionally with labels.

    Args:
        name: Namespace name.
        labels: Comma-separated KEY=VALUE pairs (e.g. "env=prod,team=platform").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)

        label_dict: dict = {}
        if labels:
            for pair in labels.split(","):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    label_dict[k.strip()] = v.strip()

        ns_body = k8s_client.V1Namespace(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels=label_dict or None,
            )
        )
        c.core_v1.create_namespace(ns_body)
        if label_dict:
            return f"Namespace '{name}' created with labels: {label_dict}"
        return f"Namespace '{name}' created successfully."
    except Exception as exc:
        return f"Error creating namespace '{name}': {format_error(exc)}"


@mcp.tool()
def delete_namespace(name: str, cluster: str = "") -> str:
    """
    DESTRUCTIVE: Delete a namespace and ALL resources within it.

    This action is irreversible. All pods, services, persistent volume claims,
    and other objects in the namespace will be permanently deleted.

    Args:
        name: Namespace to delete.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        c.core_v1.delete_namespace(name)
        return (
            f"Namespace '{name}' deletion initiated. "
            "It will be fully removed once all resources inside it are cleaned up."
        )
    except Exception as exc:
        return f"Error deleting namespace '{name}': {format_error(exc)}"


@mcp.tool()
def get_namespace_resource_quota(namespace: str, cluster: str = "") -> str:
    """List ResourceQuotas and LimitRanges in a namespace."""
    try:
        c = get_client(cluster)
        lines: list[str] = [f"=== Resource Quotas in '{namespace}' ===", ""]

        # ResourceQuotas
        quotas = c.core_v1.list_namespaced_resource_quota(namespace)
        if quotas.items:
            for rq in quotas.items:
                lines.append(f"  ResourceQuota: {rq.metadata.name}")
                status = rq.status or k8s_client.V1ResourceQuotaStatus()
                hard = status.hard or {}
                used = status.used or {}
                all_resources = sorted(set(list(hard.keys()) + list(used.keys())))
                rq_rows = [
                    [res, used.get(res, "0"), hard.get(res, "—")]
                    for res in all_resources
                ]
                lines.append(format_table(["RESOURCE", "USED", "HARD"], rq_rows))
                lines.append("")
        else:
            lines.append("  No ResourceQuotas found.")
            lines.append("")

        # LimitRanges
        lines.append(f"=== Limit Ranges in '{namespace}' ===")
        lines.append("")
        limit_ranges = c.core_v1.list_namespaced_limit_range(namespace)
        if limit_ranges.items:
            for lr in limit_ranges.items:
                lines.append(f"  LimitRange: {lr.metadata.name}")
                for item in lr.spec.limits or []:
                    lines.append(f"    Type: {item.type}")
                    lr_rows: list = []
                    all_res = sorted(
                        set(
                            list((item.default or {}).keys())
                            + list((item.default_request or {}).keys())
                            + list((item.max or {}).keys())
                            + list((item.min or {}).keys())
                        )
                    )
                    for res in all_res:
                        lr_rows.append([
                            res,
                            (item.default or {}).get(res, "—"),
                            (item.default_request or {}).get(res, "—"),
                            (item.max or {}).get(res, "—"),
                            (item.min or {}).get(res, "—"),
                        ])
                    lines.append(
                        format_table(
                            ["RESOURCE", "DEFAULT", "DEFAULT REQUEST", "MAX", "MIN"],
                            lr_rows,
                        )
                    )
                lines.append("")
        else:
            lines.append("  No LimitRanges found.")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting resource quotas for '{namespace}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@mcp.tool()
def list_events(
    namespace: str = "",
    field_selector: str = "",
    involved_object: str = "",
    cluster: str = "",
) -> str:
    """
    List the most recent 50 events, optionally filtered by namespace, field selector,
    or involved object name.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        field_selector: Kubernetes field selector (e.g. "reason=BackOff").
        involved_object: Filter by involvedObject.name (appended to field_selector).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)

        fs_parts = []
        if field_selector:
            fs_parts.append(field_selector)
        if involved_object:
            fs_parts.append(f"involvedObject.name={involved_object}")
        fs = ",".join(fs_parts) if fs_parts else None

        kwargs: dict = {}
        if fs:
            kwargs["field_selector"] = fs

        if namespace:
            events = c.core_v1.list_namespaced_event(namespace, **kwargs)
        else:
            events = c.core_v1.list_event_for_all_namespaces(**kwargs)

        items = events.items or []
        # Sort by last timestamp descending, take last 50
        _epoch = datetime.min.replace(tzinfo=timezone.utc)

        def _sort_ts(e):
            ts = e.last_timestamp or e.event_time or e.metadata.creation_timestamp
            if ts is None:
                return _epoch
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts

        items.sort(key=_sort_ts, reverse=True)
        items = items[:50]

        if not items:
            return "No events found."

        headers = ["NAMESPACE", "LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"]
        rows = []
        for ev in items:
            ns = ev.metadata.namespace or ""
            last_seen = age_string(ev.last_timestamp or ev.event_time or ev.metadata.creation_timestamp)
            ev_type = ev.type or ""
            reason = ev.reason or ""
            obj = f"{ev.involved_object.kind}/{ev.involved_object.name}" if ev.involved_object else ""
            msg = (ev.message or "").replace("\n", " ")
            rows.append([ns, last_seen, ev_type, reason, obj, msg])

        return format_table(headers, rows, max_col=60)
    except Exception as exc:
        return f"Error listing events: {format_error(exc)}"


# ---------------------------------------------------------------------------
# ETCD
# ---------------------------------------------------------------------------

@mcp.tool()
def get_etcd_status(cluster: str = "") -> str:
    """Get ETCD cluster status from operator.openshift.io/v1 etcds/cluster."""
    try:
        c = get_client(cluster)
        etcd = c.get_custom("operator.openshift.io", "v1", "etcds", "cluster")
        status = etcd.get("status", {})
        spec = etcd.get("spec", {})

        lines = [
            "=== ETCD Cluster Status ===",
            f"  Management State : {spec.get('managementState', 'unknown')}",
            f"  Observer Nodes   : {len(status.get('nodeStatuses', []))}",
            "",
            "=== Conditions ===",
        ]

        conditions = status.get("conditions", [])
        for cond in conditions:
            ctype = cond.get("type", "")
            cstatus = cond.get("status", "Unknown")
            reason = cond.get("reason", "")
            msg = cond.get("message", "").strip()
            since = age_string(cond.get("lastTransitionTime"))
            lines.append(f"  {ctype:<30} {cstatus:<8} (since {since})")
            if reason:
                lines.append(f"    Reason  : {reason}")
            if msg:
                lines.append(f"    Message : {msg[:160]}")

        # Node statuses
        node_statuses = status.get("nodeStatuses", [])
        if node_statuses:
            lines += ["", "=== Node Statuses ==="]
            ns_rows = [
                [
                    ns.get("nodeName", ""),
                    ns.get("currentRevision", ""),
                    ns.get("targetRevision", ""),
                    ns.get("lastFailedRevision", ""),
                ]
                for ns in node_statuses
            ]
            lines.append(
                format_table(
                    ["NODE", "CURRENT REVISION", "TARGET REVISION", "LAST FAILED"],
                    ns_rows,
                )
            )

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting ETCD status: {format_error(exc)}"


# ---------------------------------------------------------------------------
# Cluster contexts
# ---------------------------------------------------------------------------

@mcp.tool()
def list_cluster_contexts(cluster: str = "") -> str:
    """Show all configured MCP clusters and the active oc kubeconfig contexts."""
    lines: list[str] = []

    # Registered MCP clusters
    clusters = list_clusters()
    lines.append("=== MCP Configured Clusters ===")
    if clusters:
        for name in clusters:
            marker = "* " if (not cluster and name == clusters[0]) or name == cluster else "  "
            lines.append(f"  {marker}{name}")
    else:
        lines.append("  (none — check OCP_API_URL, OCP_CLUSTERS, or kubeconfig)")

    lines.append("")

    # oc kubeconfig contexts
    lines.append("=== oc Kubeconfig Contexts ===")
    ok, out = run_oc(["config", "get-contexts"])
    if ok:
        lines.append(out.rstrip())
    else:
        lines.append(f"  (could not retrieve contexts: {out.strip()})")

    return "\n".join(lines)
