"""
OpenShift networking MCP tools.

Covers: Services, Routes (OpenShift), Ingresses, NetworkPolicies,
cluster network config, and IngressControllers.
"""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@mcp.tool()
def list_services(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List Services with NAMESPACE, NAME, TYPE, CLUSTER-IP, EXTERNAL-IP, PORT(S), and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter Services.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            services = c.core_v1.list_namespaced_service(namespace, **kwargs)
        else:
            services = c.core_v1.list_service_for_all_namespaces(**kwargs)

        items = services.items or []
        if not items:
            return "No services found."

        headers = ["NAMESPACE", "NAME", "TYPE", "CLUSTER-IP", "EXTERNAL-IP", "PORT(S)", "AGE"]
        rows = []
        for svc in items:
            ns = svc.metadata.namespace or ""
            name = svc.metadata.name or ""
            svc_type = svc.spec.type if svc.spec else "ClusterIP"
            cluster_ip = svc.spec.cluster_ip if svc.spec else "<none>"

            # External IPs / load-balancer ingress
            external_ips: list[str] = []
            if svc.spec and svc.spec.external_i_ps:
                external_ips.extend(svc.spec.external_i_ps)
            if svc.status and svc.status.load_balancer and svc.status.load_balancer.ingress:
                for ing in svc.status.load_balancer.ingress:
                    external_ips.append(ing.hostname or ing.ip or "")
            external_str = ",".join(filter(None, external_ips)) or "<none>"

            # Ports
            ports: list[str] = []
            if svc.spec and svc.spec.ports:
                for p in svc.spec.ports:
                    proto = p.protocol or "TCP"
                    node_port = f":{p.node_port}" if p.node_port else ""
                    ports.append(f"{p.port}{node_port}/{proto}")
            ports_str = ",".join(ports) if ports else "<none>"

            age = age_string(svc.metadata.creation_timestamp)
            rows.append([ns, name, svc_type, cluster_ip, external_str, ports_str, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing services: {format_error(exc)}"


@mcp.tool()
def get_service(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Show detailed info for a Service including selector, ports, and current Endpoints.

    Args:
        name: Service name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        svc = c.core_v1.read_namespaced_service(name, namespace)
        spec = svc.spec or {}

        # Helper: attribute dict for spec object
        def _spec_attr(attr: str, default=None):
            return getattr(svc.spec, attr, default) if svc.spec else default

        svc_type = _spec_attr("type", "ClusterIP")
        cluster_ip = _spec_attr("cluster_ip", "<none>")
        session_affinity = _spec_attr("session_affinity", "None")
        external_traffic_policy = _spec_attr("external_traffic_policy", "")

        lines = [
            f"=== Service: {namespace}/{name} ===",
            f"  Type                   : {svc_type}",
            f"  Cluster IP             : {cluster_ip}",
            f"  Session Affinity       : {session_affinity}",
            f"  Age                    : {age_string(svc.metadata.creation_timestamp)}",
        ]
        if external_traffic_policy:
            lines.append(f"  External Traffic Policy: {external_traffic_policy}")

        # Selector
        selector = _spec_attr("selector") or {}
        lines += ["", "=== Selector ==="]
        if selector:
            for k, v in sorted(selector.items()):
                lines.append(f"  {k}={v}")
        else:
            lines.append("  <none>")

        # Ports
        ports = _spec_attr("ports") or []
        lines += ["", "=== Ports ==="]
        port_rows = []
        for p in ports:
            target = str(p.target_port) if p.target_port else "-"
            node_port = str(p.node_port) if p.node_port else "-"
            port_rows.append([
                p.name or "",
                p.protocol or "TCP",
                str(p.port),
                target,
                node_port,
            ])
        if port_rows:
            lines.append(format_table(["NAME", "PROTOCOL", "PORT", "TARGET PORT", "NODE PORT"], port_rows))
        else:
            lines.append("  <none>")

        # Endpoints
        lines += ["", "=== Endpoints ==="]
        try:
            ep = c.core_v1.read_namespaced_endpoints(name, namespace)
            subsets = ep.subsets or []
            if subsets:
                for subset in subsets:
                    addresses = subset.addresses or []
                    not_ready = subset.not_ready_addresses or []
                    ep_ports = subset.ports or []
                    port_str = ",".join(str(p.port) for p in ep_ports)
                    if addresses:
                        addr_str = ",".join(
                            f"{a.ip}:{port_str}" if port_str else a.ip
                            for a in addresses
                        )
                        lines.append(f"  Ready    : {addr_str}")
                    if not_ready:
                        nr_str = ",".join(a.ip for a in not_ready)
                        lines.append(f"  NotReady : {nr_str}")
            else:
                lines.append("  <none>")
        except Exception:
            lines.append("  (could not retrieve endpoints)")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting service '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def delete_service(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Delete a Service.

    Args:
        name: Service name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        c.core_v1.delete_namespaced_service(name, namespace)
        return f"Service '{namespace}/{name}' deleted successfully."
    except Exception as exc:
        return f"Error deleting service '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Routes (OpenShift-specific)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_routes(
    namespace: str = "",
    cluster: str = "",
) -> str:
    """
    List OpenShift Routes (route.openshift.io/v1) with NAMESPACE, NAME, HOST/PATH, TLS, SERVICE, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        items = c.list_custom(
            "route.openshift.io", "v1", "routes", namespace=namespace
        )
        if not items:
            return "No routes found."

        headers = ["NAMESPACE", "NAME", "HOST/PATH", "TLS", "SERVICE", "PORT", "AGE"]
        rows = []
        for route in items:
            meta = route.get("metadata", {})
            ns = meta.get("namespace", "")
            name = meta.get("name", "")
            spec = route.get("spec", {})
            host = spec.get("host", "")
            path = spec.get("path", "/")
            host_path = f"{host}{path}" if path != "/" else host

            tls = spec.get("tls", {})
            tls_str = tls.get("termination", "none") if tls else "none"

            to = spec.get("to", {})
            service = to.get("name", "")

            port_obj = spec.get("port", {})
            port = port_obj.get("targetPort", "") if port_obj else ""

            age = age_string(meta.get("creationTimestamp"))
            rows.append([ns, name, host_path, tls_str, service, str(port), age])

        return format_table(headers, rows, max_col=55)
    except Exception as exc:
        return f"Error listing routes: {format_error(exc)}"


@mcp.tool()
def get_route(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Get detailed information for an OpenShift Route including admitted status and TLS config.

    Args:
        name: Route name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        route = c.get_custom("route.openshift.io", "v1", "routes", name, namespace=namespace)
        meta = route.get("metadata", {})
        spec = route.get("spec", {})
        status = route.get("status", {})
        tls = spec.get("tls", {})
        to = spec.get("to", {})

        lines = [
            f"=== Route: {namespace}/{name} ===",
            f"  Host             : {spec.get('host', 'unknown')}",
            f"  Path             : {spec.get('path', '/')}",
            f"  Service          : {to.get('name', '')} (weight {to.get('weight', 100)}%)",
            f"  Target Port      : {spec.get('port', {}).get('targetPort', 'unknown') if spec.get('port') else 'unknown'}",
            f"  Wildcard Policy  : {spec.get('wildcardPolicy', 'None')}",
            f"  Age              : {age_string(meta.get('creationTimestamp'))}",
        ]

        # Alternate backends
        alt_backends = spec.get("alternateBackends", [])
        if alt_backends:
            lines += ["", "=== Alternate Backends ==="]
            for ab in alt_backends:
                lines.append(f"  {ab.get('name', '')} (weight {ab.get('weight', 0)}%)")

        # TLS
        lines += ["", "=== TLS Configuration ==="]
        if tls:
            lines.append(f"  Termination      : {tls.get('termination', 'none')}")
            lines.append(f"  Insecure Policy  : {tls.get('insecureEdgeTerminationPolicy', 'None')}")
            if tls.get("certificate"):
                lines.append("  Certificate      : (configured)")
            if tls.get("key"):
                lines.append("  Key              : (configured)")
            if tls.get("caCertificate"):
                lines.append("  CA Certificate   : (configured)")
        else:
            lines.append("  (no TLS configured — plain HTTP)")

        # Ingress (admitted) status
        ingress = status.get("ingress", [])
        lines += ["", "=== Ingress Status ==="]
        if ingress:
            for ing in ingress:
                admitted = next(
                    (c for c in ing.get("conditions", []) if c.get("type") == "Admitted"),
                    {},
                )
                lines.append(f"  Router    : {ing.get('routerName', 'unknown')}")
                lines.append(f"  Host      : {ing.get('host', '')}")
                lines.append(
                    f"  Admitted  : {admitted.get('status', 'Unknown')}  "
                    f"(since {age_string(admitted.get('lastTransitionTime'))})"
                )
                if admitted.get("message"):
                    lines.append(f"  Message   : {admitted.get('message')}")
                lines.append("")
        else:
            lines.append("  (not yet admitted by any router)")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting route '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def create_route(
    name: str,
    namespace: str,
    service: str,
    host: str = "",
    path: str = "/",
    tls_termination: str = "",
    port: str = "",
    cluster: str = "",
) -> str:
    """
    Create an OpenShift Route by exposing a Service.

    Uses 'oc expose' to create a basic route and then patches TLS termination
    and path if required.

    Args:
        name: Route name.
        namespace: Namespace.
        service: Name of the Service to expose.
        host: Hostname for the route (empty = let the router assign one).
        path: URL path prefix (default "/").
        tls_termination: TLS termination type: "edge", "passthrough", "reencrypt", or "" (no TLS).
        port: Target port name or number (empty = first port from Service).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        expose_args = c.oc_args() + [
            "expose", "service", service,
            "--name", name,
            "-n", namespace,
        ]
        if host:
            expose_args += ["--hostname", host]
        if port:
            expose_args += ["--port", port]
        if path and path != "/":
            expose_args += ["--path", path]

        ok, out = run_oc(expose_args)
        if not ok:
            return f"Failed to create route:\n{out}"

        # Patch TLS if requested
        if tls_termination:
            patch = {
                "spec": {
                    "tls": {
                        "termination": tls_termination,
                        "insecureEdgeTerminationPolicy": "Redirect",
                    }
                }
            }
            try:
                c.patch_custom(
                    "route.openshift.io", "v1", "routes", name, patch, namespace=namespace
                )
                return (
                    f"Route '{namespace}/{name}' created for service '{service}' "
                    f"with TLS termination '{tls_termination}'.\n{out.strip()}"
                )
            except Exception as patch_exc:
                return (
                    f"Route created but TLS patch failed: {format_error(patch_exc)}\n"
                    f"Original output: {out.strip()}"
                )

        return f"Route '{namespace}/{name}' created for service '{service}'.\n{out.strip()}"
    except Exception as exc:
        return f"Error creating route '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def delete_route(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Delete an OpenShift Route.

    Args:
        name: Route name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        c.delete_custom("route.openshift.io", "v1", "routes", name, namespace=namespace)
        return f"Route '{namespace}/{name}' deleted successfully."
    except Exception as exc:
        return f"Error deleting route '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Ingresses
# ---------------------------------------------------------------------------

@mcp.tool()
def list_ingresses(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List Kubernetes Ingress objects with NAMESPACE, NAME, CLASS, HOSTS, ADDRESS, PORTS, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter Ingresses.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            ingresses = c.networking_v1.list_namespaced_ingress(namespace, **kwargs)
        else:
            ingresses = c.networking_v1.list_ingress_for_all_namespaces(**kwargs)

        items = ingresses.items or []
        if not items:
            return "No Ingresses found."

        headers = ["NAMESPACE", "NAME", "CLASS", "HOSTS", "ADDRESS", "PORTS", "AGE"]
        rows = []
        for ing in items:
            ns = ing.metadata.namespace or ""
            name = ing.metadata.name or ""
            spec = ing.spec or {}

            ing_class = ""
            if hasattr(spec, "ingress_class_name") and spec.ingress_class_name:
                ing_class = spec.ingress_class_name
            elif ing.metadata.annotations:
                ing_class = ing.metadata.annotations.get("kubernetes.io/ingress.class", "")

            # Collect hosts from rules
            rules = getattr(spec, "rules", None) or []
            hosts = ",".join(r.host or "*" for r in rules) if rules else "*"

            # Load balancer addresses
            lb_addrs: list[str] = []
            if ing.status and ing.status.load_balancer and ing.status.load_balancer.ingress:
                for lb_ing in ing.status.load_balancer.ingress:
                    lb_addrs.append(lb_ing.hostname or lb_ing.ip or "")
            address_str = ",".join(filter(None, lb_addrs)) or "<pending>"

            # Ports from TLS
            tls_list = getattr(spec, "tls", None) or []
            ports_str = "80,443" if tls_list else "80"

            age = age_string(ing.metadata.creation_timestamp)
            rows.append([ns, name, ing_class, hosts, address_str, ports_str, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing ingresses: {format_error(exc)}"


# ---------------------------------------------------------------------------
# NetworkPolicies
# ---------------------------------------------------------------------------

@mcp.tool()
def list_network_policies(
    namespace: str = "",
    cluster: str = "",
) -> str:
    """
    List NetworkPolicies with NAMESPACE, NAME, POD-SELECTOR, POLICY-TYPES, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)

        if namespace:
            policies = c.networking_v1.list_namespaced_network_policy(namespace)
        else:
            policies = c.networking_v1.list_network_policy_for_all_namespaces()

        items = policies.items or []
        if not items:
            return "No NetworkPolicies found."

        headers = ["NAMESPACE", "NAME", "POD-SELECTOR", "POLICY-TYPES", "AGE"]
        rows = []
        for np in items:
            ns = np.metadata.namespace or ""
            name = np.metadata.name or ""
            spec = np.spec

            # Pod selector
            if spec and spec.pod_selector:
                ml = spec.pod_selector.match_labels or {}
                if ml:
                    pod_sel = ",".join(f"{k}={v}" for k, v in ml.items())
                else:
                    pod_sel = "<all pods>"
            else:
                pod_sel = "<all pods>"

            # Policy types
            policy_types = []
            if spec and spec.policy_types:
                policy_types = spec.policy_types
            else:
                # Infer from presence of ingress/egress rules
                if spec:
                    if spec.ingress is not None:
                        policy_types.append("Ingress")
                    if spec.egress is not None:
                        policy_types.append("Egress")
            types_str = ",".join(policy_types) if policy_types else "Ingress"

            age = age_string(np.metadata.creation_timestamp)
            rows.append([ns, name, pod_sel, types_str, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing network policies: {format_error(exc)}"


@mcp.tool()
def delete_network_policy(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Delete a NetworkPolicy.

    Args:
        name: NetworkPolicy name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        c.networking_v1.delete_namespaced_network_policy(name, namespace)
        return f"NetworkPolicy '{namespace}/{name}' deleted successfully."
    except Exception as exc:
        return f"Error deleting network policy '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Cluster-level networking config
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cluster_network_config(cluster: str = "") -> str:
    """
    Get the cluster-wide Network configuration from config.openshift.io/v1 networks/cluster.

    Shows network type, cluster networks, service networks, and machine networks.
    """
    try:
        c = get_client(cluster)
        network = c.get_custom("config.openshift.io", "v1", "networks", "cluster")
        spec = network.get("spec", {})
        status = network.get("status", {})

        network_type = status.get("networkType") or spec.get("networkType", "unknown")

        lines = [
            "=== Cluster Network Configuration ===",
            f"  Network Type    : {network_type}",
            "",
        ]

        # Cluster networks
        cluster_networks = status.get("clusterNetwork") or spec.get("clusterNetwork", [])
        lines.append("  Cluster Networks:")
        if cluster_networks:
            for cn in cluster_networks:
                lines.append(
                    f"    {cn.get('cidr', '')}  (hostPrefix /{cn.get('hostPrefix', '')})"
                )
        else:
            lines.append("    (none)")

        # Service networks
        service_networks = status.get("serviceNetwork") or spec.get("serviceNetwork", [])
        lines.append("")
        lines.append("  Service Networks:")
        if service_networks:
            for sn in service_networks:
                lines.append(f"    {sn}")
        else:
            lines.append("    (none)")

        # Machine networks
        machine_networks = spec.get("machineNetwork", [])
        lines.append("")
        lines.append("  Machine Networks:")
        if machine_networks:
            for mn in machine_networks:
                lines.append(f"    {mn.get('cidr', '')}")
        else:
            lines.append("    (none configured in spec)")

        # Additional status fields
        lines.append("")
        lines.append("=== Additional Status ===")
        for key in (
            "migration",
            "conditions",
        ):
            val = status.get(key)
            if val:
                lines.append(f"  {key}: {val}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting cluster network config: {format_error(exc)}"


@mcp.tool()
def get_ingress_controller(
    name: str = "default",
    cluster: str = "",
) -> str:
    """
    Get an OpenShift IngressController from operator.openshift.io/v1.

    Args:
        name: IngressController name (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ic = c.get_custom(
            "operator.openshift.io", "v1", "ingresscontrollers", name,
            namespace="openshift-ingress-operator",
        )
        meta = ic.get("metadata", {})
        spec = ic.get("spec", {})
        status = ic.get("status", {})

        domain = spec.get("domain", "")
        replicas_spec = spec.get("replicas")
        endpoint_publishing = spec.get("endpointPublishingStrategy", {})

        lines = [
            f"=== IngressController: {name} ===",
            f"  Domain                  : {domain or '(cluster default)'}",
            f"  Replicas (spec)         : {replicas_spec if replicas_spec is not None else 'default (2)'}",
            f"  Available Replicas      : {status.get('availableReplicas', 0)}",
            f"  Selector                : {status.get('selector', '')}",
            "",
            "=== Endpoint Publishing Strategy ===",
            f"  Type                    : {endpoint_publishing.get('type', 'unknown')}",
        ]

        # Load balancer scope
        lb_strat = endpoint_publishing.get("loadBalancer", {})
        if lb_strat:
            lines.append(f"  LB Scope                : {lb_strat.get('scope', 'External')}")
            allowed_src = lb_strat.get("allowedSourceRanges", [])
            if allowed_src:
                lines.append(f"  Allowed Source Ranges   : {', '.join(allowed_src)}")

        # TLS security profile
        tls_profile = spec.get("tlsSecurityProfile", {})
        if tls_profile:
            lines += ["", "=== TLS Security Profile ==="]
            profile_type = tls_profile.get("type", "Intermediate")
            lines.append(f"  Profile Type            : {profile_type}")
            custom = tls_profile.get("custom")
            if custom:
                lines.append(f"  Min TLS Version         : {custom.get('minTLSVersion', '')}")
                lines.append(f"  Ciphers                 : {', '.join(custom.get('ciphers', []))}")

        # Conditions
        conditions = status.get("conditions", [])
        if conditions:
            lines += ["", "=== Conditions ==="]
            cond_rows = []
            for cond in conditions:
                cond_rows.append([
                    cond.get("type", ""),
                    cond.get("status", ""),
                    cond.get("reason", ""),
                    age_string(cond.get("lastTransitionTime")),
                ])
            lines.append(format_table(["TYPE", "STATUS", "REASON", "AGE"], cond_rows))

        # Namespace selector (which namespaces this IC serves)
        ns_selector = spec.get("namespaceSelector")
        if ns_selector:
            lines += ["", "=== Namespace Selector ==="]
            ml = ns_selector.get("matchLabels", {})
            for k, v in ml.items():
                lines.append(f"  {k}={v}")
            me = ns_selector.get("matchExpressions", [])
            for expr in me:
                lines.append(
                    f"  {expr.get('key')} {expr.get('operator')} {expr.get('values', [])}"
                )

        # Route selector
        route_selector = spec.get("routeSelector")
        if route_selector:
            lines += ["", "=== Route Selector ==="]
            ml = route_selector.get("matchLabels", {})
            for k, v in ml.items():
                lines.append(f"  {k}={v}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting IngressController '{name}': {format_error(exc)}"
