"""OpenShift Service Mesh tools: SMCPs, VirtualServices, DestinationRules, PeerAuthentications, etc."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_SMCP = ("maistra.io", "v2", "servicemeshcontrolplanes")
_SMMR = ("maistra.io", "v1", "servicemeshmemberrolls")
_VS = ("networking.istio.io", "v1beta1", "virtualservices")
_DR = ("networking.istio.io", "v1beta1", "destinationrules")
_PA = ("security.istio.io", "v1beta1", "peerauthentications")
_SE = ("networking.istio.io", "v1beta1", "serviceentries")
_GW = ("networking.istio.io", "v1beta1", "gateways")


@mcp.tool()
def list_service_mesh_control_planes(namespace: str = "", cluster: str = "") -> str:
    """List ServiceMeshControlPlanes with generation, version, readiness, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SMCP, namespace=namespace)
        rows = []
        for smcp in items:
            meta = smcp.get("metadata", {})
            spec = smcp.get("spec", {})
            status = smcp.get("status", {})
            version = spec.get("version", status.get("chartVersion", "?"))
            ready_comps = status.get("readiness", {}).get("components", {})
            total = sum(len(v) for v in ready_comps.values()) if ready_comps else 0
            ready = sum(
                1 for comps in ready_comps.values() for comp in comps
                if comp in (status.get("readiness", {}).get("components", {}).get("ready", []))
            ) if ready_comps else 0
            # Simpler: use conditions for ready count
            conditions = status.get("conditions", [])
            ready_str = next(
                (cond.get("status", "?") for cond in conditions if cond.get("type") == "Ready"),
                "?",
            )
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                str(meta.get("generation", "")),
                version,
                ready_str,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "GENERATION", "VERSION", "READY", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_smcp_status(name: str, namespace: str, cluster: str = "") -> str:
    """Get ServiceMeshControlPlane status: conditions and component readiness breakdown."""
    c = get_client(cluster)
    try:
        smcp = c.get_custom(*_SMCP, name, namespace)
        meta = smcp.get("metadata", {})
        spec = smcp.get("spec", {})
        status = smcp.get("status", {})
        lines = [
            f"ServiceMeshControlPlane: {namespace}/{name}",
            f"  Version:    {spec.get('version', status.get('chartVersion', '?'))}",
            f"  Generation: {meta.get('generation', '')}",
            f"  Age:        {age_string(meta.get('creationTimestamp'))}",
            "\nConditions:",
        ]
        for cond in status.get("conditions", []):
            lines.append(
                f"  {cond.get('type', ''):30s} {cond.get('status', '?'):8s} "
                f"[{age_string(cond.get('lastTransitionTime'))}] {cond.get('message', '')[:80]}"
            )
        readiness = status.get("readiness", {})
        components = readiness.get("components", {})
        if components:
            lines.append("\nComponent Readiness:")
            for category, comp_list in components.items():
                lines.append(f"  [{category}]")
                if isinstance(comp_list, list):
                    for comp in comp_list:
                        lines.append(f"    - {comp}")
                elif isinstance(comp_list, dict):
                    for comp_name, comp_status in comp_list.items():
                        lines.append(f"    {comp_name}: {comp_status}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_virtual_services(namespace: str = "", cluster: str = "") -> str:
    """List Istio VirtualServices with hosts, gateways, HTTP/TCP route counts, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_VS, namespace=namespace)
        rows = []
        for vs in items:
            meta = vs.get("metadata", {})
            spec = vs.get("spec", {})
            hosts = ",".join(spec.get("hosts", []))
            gateways = ",".join(spec.get("gateways", []))
            http_count = len(spec.get("http", []))
            tcp_count = len(spec.get("tcp", []))
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                hosts[:40],
                gateways[:30],
                str(http_count),
                str(tcp_count),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "HOSTS", "GATEWAYS", "HTTP", "TCP", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_destination_rules(namespace: str = "", cluster: str = "") -> str:
    """List Istio DestinationRules with host, subsets, TLS mode, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_DR, namespace=namespace)
        rows = []
        for dr in items:
            meta = dr.get("metadata", {})
            spec = dr.get("spec", {})
            host = spec.get("host", "")
            subsets = spec.get("subsets", [])
            subset_names = ",".join(s.get("name", "") for s in subsets)
            tls_mode = spec.get("trafficPolicy", {}).get("tls", {}).get("mode", "")
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                host[:40],
                subset_names[:30],
                tls_mode,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "HOST", "SUBSETS", "TLS-MODE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_peer_authentications(namespace: str = "", cluster: str = "") -> str:
    """List Istio PeerAuthentications with mTLS mode, selector, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PA, namespace=namespace)
        rows = []
        for pa in items:
            meta = pa.get("metadata", {})
            spec = pa.get("spec", {})
            mtls_mode = spec.get("mtls", {}).get("mode", "UNSET")
            selector = spec.get("selector", {}).get("matchLabels", {})
            sel_str = ",".join(f"{k}={v}" for k, v in selector.items()) if selector else "(mesh-wide)"
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                mtls_mode,
                sel_str[:40],
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "MTLS-MODE", "SELECTOR", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_service_entries(namespace: str = "", cluster: str = "") -> str:
    """List Istio ServiceEntries with hosts, location, ports, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SE, namespace=namespace)
        rows = []
        for se in items:
            meta = se.get("metadata", {})
            spec = se.get("spec", {})
            hosts = ",".join(spec.get("hosts", []))
            location = spec.get("location", "")
            ports = spec.get("ports", [])
            ports_str = ",".join(
                f"{p.get('number', '')}:{p.get('protocol', '')}" for p in ports
            )
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                hosts[:40],
                location,
                ports_str[:30],
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "HOSTS", "LOCATION", "PORTS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_gateways(namespace: str = "", cluster: str = "") -> str:
    """List Istio Gateways with selector, ports, servers count, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_GW, namespace=namespace)
        rows = []
        for gw in items:
            meta = gw.get("metadata", {})
            spec = gw.get("spec", {})
            selector = spec.get("selector", {})
            sel_str = ",".join(f"{k}={v}" for k, v in selector.items())
            servers = spec.get("servers", [])
            ports_str = ",".join(
                str(s.get("port", {}).get("number", "")) for s in servers
            )
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                sel_str[:30],
                ports_str[:20],
                str(len(servers)),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "SELECTOR", "PORTS", "SERVERS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_service_mesh_members(namespace: str = "", cluster: str = "") -> str:
    """List ServiceMeshMemberRolls and the namespaces enrolled in each mesh."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SMMR, namespace=namespace)
        rows = []
        enrolled_sections = []
        for smmr in items:
            meta = smmr.get("metadata", {})
            spec = smmr.get("spec", {})
            status = smmr.get("status", {})
            members = spec.get("members", [])
            configured = status.get("configuredMembers", [])
            conditions = status.get("conditions", [])
            ready = next(
                (cond.get("status", "?") for cond in conditions if cond.get("type") == "Ready"),
                "?",
            )
            ns_name = meta.get("namespace", "")
            name = meta.get("name", "")
            rows.append([
                ns_name,
                name,
                str(len(members)),
                str(len(configured)),
                ready,
                age_string(meta.get("creationTimestamp")),
            ])
            if members:
                enrolled_sections.append(
                    f"\nEnrolled namespaces for {ns_name}/{name}:\n"
                    + "\n".join(f"  - {m}" for m in sorted(members))
                )
        table = format_table(
            ["NAMESPACE", "NAME", "MEMBERS", "CONFIGURED", "READY", "AGE"], rows
        )
        if enrolled_sections:
            return table + "\n" + "\n".join(enrolled_sections)
        return table
    except Exception as e:
        return format_error(e)
