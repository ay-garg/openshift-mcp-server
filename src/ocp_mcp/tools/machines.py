"""Machine API and MachineConfig tools for OpenShift 4."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_MS   = ("machine.openshift.io", "v1beta1", "machinesets")
_MACH = ("machine.openshift.io", "v1beta1", "machines")
_MCP  = ("machineconfiguration.openshift.io", "v1", "machineconfigpools")
_MC   = ("machineconfiguration.openshift.io", "v1", "machineconfigs")

_MA_NS = "openshift-machine-api"


@mcp.tool()
def list_machine_sets(cluster: str = "") -> str:
    """List MachineSets with desired/ready/available replica counts, instance type, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MS, namespace=_MA_NS)
        rows = []
        for ms in items:
            spec = ms.get("spec", {})
            status = ms.get("status", {})
            # Try common provider fields for instance type
            pspec = (spec.get("template", {}).get("spec", {})
                     .get("providerSpec", {}).get("value", {}))
            itype = pspec.get("instanceType",
                    pspec.get("vmSize",
                    pspec.get("machineType", "?")))
            rows.append([
                ms.get("metadata", {}).get("name", ""),
                str(spec.get("replicas", 0)),
                str(status.get("readyReplicas", 0)),
                str(status.get("availableReplicas", 0)),
                itype,
                age_string(ms.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "DESIRED", "READY", "AVAILABLE", "INSTANCE-TYPE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_machine_set(name: str, cluster: str = "") -> str:
    """Describe a MachineSet showing all spec and status details."""
    ok, out = run_oc(["describe", "machineset", name, "-n", _MA_NS])
    return out if ok else f"Error:\n{out}"


@mcp.tool()
def scale_machine_set(name: str, replicas: int, cluster: str = "") -> str:
    """Scale a MachineSet to the given number of replicas by patching spec.replicas.
    WARNING: Scaling down will cause machines (and their nodes) to be deleted."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_MS, name, {"spec": {"replicas": replicas}}, _MA_NS)
        return f"MachineSet '{name}' scaled to {replicas} replica(s)."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_machines(label_selector: str = "", cluster: str = "") -> str:
    """List Machines with phase, node ref, provider ID, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MACH, namespace=_MA_NS, label_selector=label_selector)
        rows = []
        for m in items:
            status = m.get("status", {})
            node_ref = status.get("nodeRef", {}).get("name", "")
            provider_id = status.get("providerID", "")
            if provider_id and len(provider_id) > 42:
                provider_id = "..." + provider_id[-39:]
            rows.append([
                m.get("metadata", {}).get("name", ""),
                status.get("phase", "?"),
                node_ref,
                provider_id,
                age_string(m.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAME", "PHASE", "NODE", "PROVIDER-ID", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_machine(name: str, cluster: str = "") -> str:
    """Get detailed Machine info: phase, nodeRef, providerID, addresses, conditions."""
    c = get_client(cluster)
    try:
        m = c.get_custom(*_MACH, name, _MA_NS)
        status = m.get("status", {})
        node_ref = status.get("nodeRef", {})
        lines = [
            f"Machine: {name}",
            f"  Phase:      {status.get('phase', '?')}",
            f"  Node:       {node_ref.get('name', '')}",
            f"  ProviderID: {status.get('providerID', '')}",
            "\nAddresses:",
        ]
        for addr in status.get("addresses", []):
            lines.append(f"  {addr.get('type', ''):15s} {addr.get('address', '')}")
        lines.append("\nConditions:")
        for cond in status.get("conditions", []):
            lines.append(
                f"  {cond.get('type', ''):40s} {cond.get('status', '?'):8s} "
                f"[{age_string(cond.get('lastTransitionTime'))}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_machine(name: str, cluster: str = "") -> str:
    """Delete a Machine — the Machine controller will drain and terminate the underlying node.
    WARNING: Destructive. The node will be cordoned, drained, and terminated."""
    c = get_client(cluster)
    try:
        c.delete_custom(*_MACH, name, _MA_NS)
        return f"Machine '{name}' deletion requested."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_machine_config_pools(cluster: str = "") -> str:
    """List MachineConfigPools with rendered config, machine counts, and status flags."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MCP)
        rows = []
        for pool in items:
            spec = pool.get("spec", {})
            status = pool.get("status", {})
            config_name = spec.get("configuration", {}).get("name", "")
            rows.append([
                pool.get("metadata", {}).get("name", ""),
                config_name,
                str(status.get("machineCount", 0)),
                str(status.get("readyMachineCount", 0)),
                str(status.get("updatedMachineCount", 0)),
                str(status.get("degradedMachineCount", 0)),
                str(spec.get("paused", False)),
                age_string(pool.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(
            ["NAME", "CONFIG", "MACHINES", "READY", "UPDATED", "DEGRADED", "PAUSED", "AGE"], rows
        )
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_machine_config_pool(name: str, cluster: str = "") -> str:
    """Get MachineConfigPool detail: conditions and machine counts."""
    c = get_client(cluster)
    try:
        pool = c.get_custom(*_MCP, name)
        spec = pool.get("spec", {})
        status = pool.get("status", {})
        lines = [
            f"MachineConfigPool: {name}",
            f"  Paused:           {spec.get('paused', False)}",
            f"  Config:           {spec.get('configuration', {}).get('name', '')}",
            f"  MachineCount:     {status.get('machineCount', 0)}",
            f"  ReadyCount:       {status.get('readyMachineCount', 0)}",
            f"  UpdatedCount:     {status.get('updatedMachineCount', 0)}",
            f"  DegradedCount:    {status.get('degradedMachineCount', 0)}",
            f"  UnavailableCount: {status.get('unavailableMachineCount', 0)}",
            "\nConditions:",
        ]
        for cond in status.get("conditions", []):
            msg = cond.get("message", "")[:80]
            lines.append(
                f"  {cond.get('type', ''):35s} {cond.get('status', '?'):8s} "
                f"[{age_string(cond.get('lastTransitionTime'))}] {msg}"
            )
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def pause_machine_config_pool(name: str, cluster: str = "") -> str:
    """Pause a MachineConfigPool — prevents config updates from rolling out to nodes."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_MCP, name, {"spec": {"paused": True}})
        return f"MachineConfigPool '{name}' paused."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def unpause_machine_config_pool(name: str, cluster: str = "") -> str:
    """Unpause a MachineConfigPool — allows pending config updates to roll out to nodes."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_MCP, name, {"spec": {"paused": False}})
        return f"MachineConfigPool '{name}' unpaused."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_machine_configs(label_selector: str = "", cluster: str = "") -> str:
    """List MachineConfigs with role label (machineconfiguration.openshift.io/role), generation, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MC, label_selector=label_selector)
        rows = []
        for mc in items:
            meta = mc.get("metadata", {})
            role = meta.get("labels", {}).get("machineconfiguration.openshift.io/role", "")
            generation = meta.get("generation", mc.get("generation", 0))
            rows.append([
                meta.get("name", ""),
                role,
                str(generation),
                age_string(meta.get("creationTimestamp")),
            ])
        rows.sort(key=lambda r: (r[1], r[0]))
        return format_table(["NAME", "ROLE", "GENERATION", "AGE"], rows)
    except Exception as e:
        return format_error(e)
