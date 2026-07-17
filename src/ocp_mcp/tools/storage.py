"""Storage tools: PVs, PVCs, StorageClasses, VolumeSnapshots."""

from __future__ import annotations

from kubernetes import client as k8s_client

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_VS = ("snapshot.storage.k8s.io", "v1", "volumesnapshots")


@mcp.tool()
def list_pvs(label_selector: str = "", cluster: str = "") -> str:
    """List PersistentVolumes with capacity, access modes, storage class, reclaim policy, status, and claim."""
    c = get_client(cluster)
    try:
        pvs = c.core_v1.list_persistent_volume(label_selector=label_selector)
        rows = []
        for pv in pvs.items:
            claim_ref = pv.spec.claim_ref
            claim = f"{claim_ref.namespace}/{claim_ref.name}" if claim_ref else ""
            rows.append([
                pv.metadata.name,
                (pv.spec.capacity or {}).get("storage", "?"),
                ",".join(pv.spec.access_modes or []),
                pv.spec.storage_class_name or "",
                pv.spec.persistent_volume_reclaim_policy or "",
                pv.status.phase or "?",
                claim,
                age_string(pv.metadata.creation_timestamp),
            ])
        return format_table(
            ["NAME", "CAPACITY", "ACCESS", "STORAGECLASS", "RECLAIM", "STATUS", "CLAIM", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_pv(name: str, cluster: str = "") -> str:
    """Get detailed PersistentVolume info including CSI, NFS, HostPath, or EBS source."""
    c = get_client(cluster)
    try:
        pv = c.core_v1.read_persistent_volume(name)
        spec = pv.spec
        lines = [
            f"PersistentVolume: {name}",
            f"  Status:          {pv.status.phase}",
            f"  Capacity:        {(spec.capacity or {}).get('storage', '?')}",
            f"  AccessModes:     {','.join(spec.access_modes or [])}",
            f"  StorageClass:    {spec.storage_class_name or ''}",
            f"  ReclaimPolicy:   {spec.persistent_volume_reclaim_policy or ''}",
            f"  VolumeMode:      {spec.volume_mode or ''}",
        ]
        if spec.claim_ref:
            lines.append(f"  Claim:           {spec.claim_ref.namespace}/{spec.claim_ref.name}")
        lines.append("\nSource:")
        if spec.csi:
            lines += [
                "  Type:            CSI",
                f"  Driver:          {spec.csi.driver}",
                f"  VolumeHandle:    {spec.csi.volume_handle}",
                f"  FSType:          {spec.csi.fs_type or ''}",
            ]
            if spec.csi.volume_attributes:
                for k, v in spec.csi.volume_attributes.items():
                    lines.append(f"  {k}: {v}")
        elif spec.nfs:
            lines += [
                "  Type:            NFS",
                f"  Server:          {spec.nfs.server}",
                f"  Path:            {spec.nfs.path}",
                f"  ReadOnly:        {spec.nfs.read_only or False}",
            ]
        elif spec.host_path:
            lines += [
                "  Type:            HostPath",
                f"  Path:            {spec.host_path.path}",
                f"  HostPathType:    {spec.host_path.type or ''}",
            ]
        elif spec.aws_elastic_block_store:
            lines += [
                "  Type:            EBS",
                f"  VolumeID:        {spec.aws_elastic_block_store.volume_id}",
                f"  FSType:          {spec.aws_elastic_block_store.fs_type or ''}",
                f"  Partition:       {spec.aws_elastic_block_store.partition or 0}",
            ]
        elif spec.iscsi:
            lines += [
                "  Type:            iSCSI",
                f"  TargetPortal:    {spec.iscsi.target_portal}",
                f"  IQN:             {spec.iscsi.iqn}",
                f"  Lun:             {spec.iscsi.lun}",
            ]
        elif spec.fc:
            lines += [
                "  Type:            FC",
                f"  TargetWWNs:      {','.join(spec.fc.target_wwns or [])}",
                f"  Lun:             {spec.fc.lun}",
            ]
        else:
            lines.append("  Type:            (other/unknown)")
        lines.append(f"\nAge: {age_string(pv.metadata.creation_timestamp)}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_pv(name: str, cluster: str = "") -> str:
    """Delete a PersistentVolume. WARNING: ensure no PVC is bound before deleting."""
    c = get_client(cluster)
    try:
        c.core_v1.delete_persistent_volume(name)
        return f"PersistentVolume '{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_pvcs(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List PersistentVolumeClaims with status, volume, capacity, access modes, and storage class."""
    c = get_client(cluster)
    try:
        if namespace:
            pvcs = c.core_v1.list_namespaced_persistent_volume_claim(
                namespace, label_selector=label_selector)
        else:
            pvcs = c.core_v1.list_persistent_volume_claim_for_all_namespaces(
                label_selector=label_selector)
        rows = []
        for pvc in pvcs.items:
            cap = (pvc.status.capacity or {}).get("storage", "?")
            rows.append([
                pvc.metadata.namespace,
                pvc.metadata.name,
                pvc.status.phase or "?",
                pvc.spec.volume_name or "",
                cap,
                ",".join(pvc.spec.access_modes or []),
                pvc.spec.storage_class_name or "",
                age_string(pvc.metadata.creation_timestamp),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "STATUS", "VOLUME", "CAPACITY", "ACCESS", "STORAGECLASS", "AGE"],
            rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_pvc(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Get detailed PersistentVolumeClaim info including conditions."""
    c = get_client(cluster)
    try:
        pvc = c.core_v1.read_namespaced_persistent_volume_claim(name, namespace)
        spec = pvc.spec
        status = pvc.status
        cap = (status.capacity or {}).get("storage", "?")
        req = "?"
        if spec.resources and spec.resources.requests:
            req = spec.resources.requests.get("storage", "?")
        lines = [
            f"PersistentVolumeClaim: {namespace}/{name}",
            f"  Status:        {status.phase}",
            f"  Volume:        {spec.volume_name or ''}",
            f"  Capacity:      {cap}",
            f"  Requested:     {req}",
            f"  AccessModes:   {','.join(spec.access_modes or [])}",
            f"  StorageClass:  {spec.storage_class_name or ''}",
            f"  VolumeMode:    {spec.volume_mode or ''}",
            f"  Age:           {age_string(pvc.metadata.creation_timestamp)}",
        ]
        conditions = status.conditions or []
        if conditions:
            lines.append("\nConditions:")
            for cond in conditions:
                lines.append(f"  {cond.type:35s} {cond.status:8s} {cond.message or ''}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_pvc(
    name: str,
    namespace: str,
    storage_request: str,
    storage_class: str = "",
    access_mode: str = "ReadWriteOnce",
    cluster: str = "",
) -> str:
    """Create a PersistentVolumeClaim.
    storage_request example: 10Gi
    access_mode: ReadWriteOnce, ReadOnlyMany, ReadWriteMany, ReadWriteOncePod."""
    c = get_client(cluster)
    try:
        spec = k8s_client.V1PersistentVolumeClaimSpec(
            access_modes=[access_mode],
            resources=k8s_client.V1ResourceRequirements(
                requests={"storage": storage_request}),
        )
        if storage_class:
            spec.storage_class_name = storage_class
        body = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=spec,
        )
        c.core_v1.create_namespaced_persistent_volume_claim(namespace, body)
        parts = [f"PersistentVolumeClaim '{namespace}/{name}' created ({storage_request}, {access_mode}"]
        if storage_class:
            parts.append(f", storageClass={storage_class}")
        parts.append(").")
        return "".join(parts)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_pvc(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Delete a PersistentVolumeClaim. WARNING: data loss may occur if PVC is in use."""
    c = get_client(cluster)
    try:
        c.core_v1.delete_namespaced_persistent_volume_claim(name, namespace)
        return f"PersistentVolumeClaim '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_storage_classes(cluster: str = "") -> str:
    """List StorageClasses. The cluster default is marked with (default)."""
    c = get_client(cluster)
    try:
        scs = c.storage_v1.list_storage_class()
        rows = []
        for sc in scs.items:
            annotations = sc.metadata.annotations or {}
            is_default = (
                annotations.get("storageclass.kubernetes.io/is-default-class") == "true"
                or annotations.get("storageclass.beta.kubernetes.io/is-default-class") == "true"
            )
            display_name = sc.metadata.name + (" (default)" if is_default else "")
            rows.append([
                display_name,
                sc.provisioner or "",
                sc.reclaim_policy or "",
                sc.volume_binding_mode or "",
                str(sc.allow_volume_expansion or False),
                age_string(sc.metadata.creation_timestamp),
            ])
        return format_table(
            ["NAME", "PROVISIONER", "RECLAIM", "BIND-MODE", "EXPANDABLE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_volume_snapshots(namespace: str = "", cluster: str = "") -> str:
    """List VolumeSnapshots (snapshot.storage.k8s.io/v1) with source PVC, class, and ready status."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_VS, namespace=namespace)
        rows = []
        for snap in items:
            meta = snap.get("metadata", {})
            spec = snap.get("spec", {})
            status = snap.get("status", {})
            source = spec.get("source", {})
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                source.get("persistentVolumeClaimName", ""),
                spec.get("volumeSnapshotClassName", ""),
                str(status.get("readyToUse", False)),
                status.get("restoreSize", "?"),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(
            ["NAMESPACE", "NAME", "SOURCE-PVC", "SNAPSHOT-CLASS", "READY", "RESTORE-SIZE", "AGE"],
            rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_volume_snapshot(
    name: str,
    namespace: str,
    pvc_name: str,
    snapshot_class: str = "",
    cluster: str = "",
) -> str:
    """Create a VolumeSnapshot from a PersistentVolumeClaim."""
    c = get_client(cluster)
    try:
        body: dict = {
            "apiVersion": "snapshot.storage.k8s.io/v1",
            "kind": "VolumeSnapshot",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "source": {"persistentVolumeClaimName": pvc_name},
            },
        }
        if snapshot_class:
            body["spec"]["volumeSnapshotClassName"] = snapshot_class
        c.create_custom(*_VS, body, namespace)
        suffix = f" using class '{snapshot_class}'" if snapshot_class else ""
        return f"VolumeSnapshot '{namespace}/{name}' created from PVC '{pvc_name}'{suffix}."
    except Exception as e:
        return format_error(e)
