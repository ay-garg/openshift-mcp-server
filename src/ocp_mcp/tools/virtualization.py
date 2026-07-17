"""OpenShift Virtualization (KubeVirt) tools: VMs, VMIs, DataVolumes, Snapshots, Migration."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_VM = ("kubevirt.io", "v1", "virtualmachines")
_VMI = ("kubevirt.io", "v1", "virtualmachineinstances")
_VMIM = ("kubevirt.io", "v1", "virtualmachineinstancemigrations")
_DV = ("cdi.kubevirt.io", "v1beta1", "datavolumes")
_SNAP = ("snapshot.kubevirt.io", "v1alpha1", "virtualmachinesnapshots")
_RESTORE = ("snapshot.kubevirt.io", "v1alpha1", "virtualmachinerestores")


def _vm_status(vm: dict) -> str:
    return vm.get("status", {}).get("printableStatus", "Unknown")


def _vm_cpu(vm: dict) -> str:
    cpu = vm.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}).get("cpu", {})
    cores = cpu.get("cores", cpu.get("sockets", 1))
    return str(cores)


def _vm_memory(vm: dict) -> str:
    resources = (vm.get("spec", {}).get("template", {}).get("spec", {})
                 .get("domain", {}).get("resources", {}))
    return resources.get("requests", {}).get("memory", "?")


@mcp.tool()
def list_virtual_machines(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List VirtualMachines with status, vCPU, memory, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_VM, namespace=namespace, label_selector=label_selector)
        rows = []
        for vm in items:
            status = vm.get("status", {})
            rows.append([vm.get("metadata", {}).get("namespace", ""),
                         vm.get("metadata", {}).get("name", ""),
                         _vm_status(vm),
                         str(status.get("ready", False)),
                         _vm_cpu(vm), _vm_memory(vm),
                         age_string(vm.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "STATUS", "READY", "vCPU", "MEMORY", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Get detailed VM info: running state, resources, interfaces, disks, conditions."""
    c = get_client(cluster)
    try:
        vm = c.get_custom(*_VM, name, namespace)
        spec = vm.get("spec", {})
        domain = spec.get("template", {}).get("spec", {}).get("domain", {})
        status = vm.get("status", {})
        lines = [f"VirtualMachine: {namespace}/{name}",
                 f"  Status:   {_vm_status(vm)}",
                 f"  Running:  {spec.get('running', False)}",
                 f"  Ready:    {status.get('ready', False)}",
                 f"  vCPU:     {_vm_cpu(vm)}",
                 f"  Memory:   {_vm_memory(vm)}",
                 "\nInterfaces:"]
        for iface in domain.get("devices", {}).get("interfaces", []):
            lines.append(f"  {iface.get('name','')}: model={iface.get('model','?')} "
                         f"{'masquerade' if iface.get('masquerade') is not None else 'bridge' if iface.get('bridge') is not None else ''}")
        lines.append("\nDisks:")
        for disk in domain.get("devices", {}).get("disks", []):
            lines.append(f"  {disk.get('name','')}: {next((k for k in disk if k != 'name'), '?')}")
        lines.append("\nVolumes:")
        for vol in spec.get("template", {}).get("spec", {}).get("volumes", []):
            src = next((k for k in vol if k != "name"), "?")
            lines.append(f"  {vol.get('name','')}: {src}")
        lines.append("\nConditions:")
        for cond in status.get("conditions", []):
            lines.append(f"  {cond.get('type',''):30s} {cond.get('status','?')}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def start_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Start a VirtualMachine by setting spec.running=true."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_VM, name, {"spec": {"running": True}}, namespace)
        return f"VirtualMachine '{namespace}/{name}' start requested."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def stop_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Stop a VirtualMachine by setting spec.running=false."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_VM, name, {"spec": {"running": False}}, namespace)
        return f"VirtualMachine '{namespace}/{name}' stop requested."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def restart_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Restart a VirtualMachine using virtctl."""
    ok, out = run_oc(["virtctl", "restart", name, "-n", namespace])
    if ok:
        return out
    # Fallback: stop then start
    c = get_client(cluster)
    try:
        c.patch_custom(*_VM, name, {"spec": {"running": False}}, namespace)
        import time; time.sleep(2)
        c.patch_custom(*_VM, name, {"spec": {"running": True}}, namespace)
        return f"VirtualMachine '{namespace}/{name}' restart initiated (stop+start)."
    except Exception as e:
        return f"virtctl failed: {out}\nFallback failed: {format_error(e)}"


@mcp.tool()
def pause_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Pause a running VirtualMachine using virtctl."""
    ok, out = run_oc(["virtctl", "pause", "vm", name, "-n", namespace])
    return out if ok else f"Error (virtctl not available): {out}"


@mcp.tool()
def unpause_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Unpause a paused VirtualMachine using virtctl."""
    ok, out = run_oc(["virtctl", "unpause", "vm", name, "-n", namespace])
    return out if ok else f"Error (virtctl not available): {out}"


@mcp.tool()
def create_virtual_machine(name: str, namespace: str, cpu_cores: int, memory: str, image_url: str = "", pvc_name: str = "", cloud_init_userdata: str = "", cluster: str = "") -> str:
    """Create a VirtualMachine. Provide image_url (HTTP) or pvc_name (existing PVC)."""
    c = get_client(cluster)
    try:
        volumes = [{"name": "cloudinit", "cloudInitNoCloud": {
            "userData": cloud_init_userdata or "#cloud-config\npassword: redhat\nchpasswd: {expire: false}"
        }}]
        disks = [{"name": "cloudinit", "disk": {"bus": "virtio"}}]

        if image_url:
            # Create DataVolume first
            dv_body = {
                "apiVersion": "cdi.kubevirt.io/v1beta1", "kind": "DataVolume",
                "metadata": {"name": f"{name}-dv", "namespace": namespace},
                "spec": {
                    "source": {"http": {"url": image_url}},
                    "pvc": {"accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": "30Gi"}}},
                },
            }
            c.create_custom(*_DV, dv_body, namespace)
            volumes.append({"name": "disk0", "dataVolume": {"name": f"{name}-dv"}})
        elif pvc_name:
            volumes.append({"name": "disk0", "persistentVolumeClaim": {"claimName": pvc_name}})
        else:
            volumes.append({"name": "disk0", "containerDisk": {
                "image": "quay.io/containerdisks/fedora:latest"
            }})
        disks.insert(0, {"name": "disk0", "disk": {"bus": "virtio"}, "bootOrder": 1})

        vm_body = {
            "apiVersion": "kubevirt.io/v1", "kind": "VirtualMachine",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "running": False,
                "template": {
                    "metadata": {"labels": {"kubevirt.io/vm": name}},
                    "spec": {
                        "domain": {
                            "cpu": {"cores": cpu_cores},
                            "resources": {"requests": {"memory": memory}},
                            "devices": {
                                "disks": disks,
                                "interfaces": [{"name": "default", "masquerade": {}}],
                            },
                        },
                        "networks": [{"name": "default", "pod": {}}],
                        "volumes": volumes,
                    },
                },
            },
        }
        c.create_custom(*_VM, vm_body, namespace)
        return (f"VirtualMachine '{namespace}/{name}' created (CPU={cpu_cores}, Memory={memory}).\n"
                f"Start it with: start_virtual_machine('{name}', '{namespace}')")
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_virtual_machine(name: str, namespace: str, cluster: str = "") -> str:
    """Delete a VirtualMachine (stop it first if running)."""
    c = get_client(cluster)
    try:
        c.delete_custom(*_VM, name, namespace)
        return f"VirtualMachine '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_virtual_machine_instances(namespace: str = "", cluster: str = "") -> str:
    """List running VirtualMachineInstances with node, IP, and phase."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_VMI, namespace=namespace)
        rows = []
        for vmi in items:
            status = vmi.get("status", {})
            interfaces = status.get("interfaces", [{}])
            ip = interfaces[0].get("ipAddress", "") if interfaces else ""
            rows.append([vmi.get("metadata", {}).get("namespace", ""),
                         vmi.get("metadata", {}).get("name", ""),
                         status.get("phase", "?"), status.get("nodeName", ""), ip,
                         age_string(vmi.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "PHASE", "NODE", "IP", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def live_migrate_vm(name: str, namespace: str, cluster: str = "") -> str:
    """Live migrate a VirtualMachineInstance to another node."""
    c = get_client(cluster)
    try:
        import time
        migration_name = f"{name}-migration-{int(time.time())}"
        body = {
            "apiVersion": "kubevirt.io/v1",
            "kind": "VirtualMachineInstanceMigration",
            "metadata": {"name": migration_name, "namespace": namespace},
            "spec": {"vmiName": name},
        }
        c.create_custom(*_VMIM, body, namespace)
        return f"Live migration '{migration_name}' started for VMI '{namespace}/{name}'."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_data_volumes(namespace: str = "", cluster: str = "") -> str:
    """List DataVolumes with phase, progress, capacity, and source type."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_DV, namespace=namespace)
        rows = []
        for dv in items:
            status = dv.get("status", {})
            spec = dv.get("spec", {})
            source = spec.get("source", {})
            src_type = next(iter(source.keys()), "?") if source else "?"
            cap = spec.get("pvc", {}).get("resources", {}).get("requests", {}).get("storage", "?")
            rows.append([dv.get("metadata", {}).get("namespace", ""),
                         dv.get("metadata", {}).get("name", ""),
                         status.get("phase", "?"),
                         status.get("progress", "?"), cap, src_type,
                         age_string(dv.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "PHASE", "PROGRESS", "CAPACITY", "SOURCE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_vm_snapshots(namespace: str = "", cluster: str = "") -> str:
    """List VirtualMachineSnapshots with phase, source VM, and ready status."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SNAP, namespace=namespace)
        rows = []
        for snap in items:
            status = snap.get("status", {})
            spec = snap.get("spec", {})
            rows.append([snap.get("metadata", {}).get("namespace", ""),
                         snap.get("metadata", {}).get("name", ""),
                         spec.get("source", {}).get("name", ""),
                         str(status.get("readyToUse", False)),
                         status.get("phase", "?"),
                         age_string(snap.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAMESPACE", "NAME", "SOURCE-VM", "READY", "PHASE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_vm_snapshot(name: str, namespace: str, vm_name: str, cluster: str = "") -> str:
    """Create a VirtualMachineSnapshot of a VM."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "snapshot.kubevirt.io/v1alpha1",
            "kind": "VirtualMachineSnapshot",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {"source": {
                "apiGroup": "kubevirt.io",
                "kind": "VirtualMachine",
                "name": vm_name,
            }},
        }
        c.create_custom(*_SNAP, body, namespace)
        return f"VirtualMachineSnapshot '{namespace}/{name}' created from VM '{vm_name}'."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def restore_vm_snapshot(restore_name: str, namespace: str, snapshot_name: str, vm_name: str, cluster: str = "") -> str:
    """Restore a VM from a VirtualMachineSnapshot."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "snapshot.kubevirt.io/v1alpha1",
            "kind": "VirtualMachineRestore",
            "metadata": {"name": restore_name, "namespace": namespace},
            "spec": {
                "target": {
                    "apiGroup": "kubevirt.io",
                    "kind": "VirtualMachine",
                    "name": vm_name,
                },
                "virtualMachineSnapshotName": snapshot_name,
            },
        }
        c.create_custom(*_RESTORE, body, namespace)
        return f"VirtualMachineRestore '{namespace}/{restore_name}' created from snapshot '{snapshot_name}'."
    except Exception as e:
        return format_error(e)
