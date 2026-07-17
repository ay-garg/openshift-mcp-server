"""OpenShift security tools: SCCs, OAuth config, pod security violations."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_SCC   = ("security.openshift.io", "v1", "securitycontextconstraints")
_OAUTH = ("config.openshift.io", "v1", "oauths")


@mcp.tool()
def list_sccs(cluster: str = "") -> str:
    """List all SecurityContextConstraints sorted by priority descending."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_SCC)
        rows = []
        for scc in items:
            priority = scc.get("priority")
            rows.append([
                scc.get("metadata", {}).get("name", ""),
                str(priority) if priority is not None else "",
                scc.get("fsGroup", {}).get("type", "?"),
                scc.get("seLinuxContext", {}).get("type", "?"),
                scc.get("runAsUser", {}).get("type", "?"),
                str(scc.get("allowPrivilegedContainer", False)),
                age_string(scc.get("metadata", {}).get("creationTimestamp")),
            ])

        def _priority_key(row):
            val = row[1]
            return -(int(val) if val.lstrip("-").isdigit() else -999)

        rows.sort(key=_priority_key)
        return format_table(
            ["NAME", "PRIORITY", "FSGROUP", "SELINUX", "RUNASUSER", "PRIVILEGED", "AGE"], rows
        )
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_scc(name: str, cluster: str = "") -> str:
    """Get full SCC detail: volumes, capabilities, allowedCapabilities, users, and groups."""
    c = get_client(cluster)
    try:
        scc = c.get_custom(*_SCC, name)
        lines = [
            f"SCC: {name}",
            f"  Priority:             {scc.get('priority', '')}",
            f"  AllowPrivileged:      {scc.get('allowPrivilegedContainer', False)}",
            f"  AllowHostNetwork:     {scc.get('allowHostNetwork', False)}",
            f"  AllowHostPID:         {scc.get('allowHostPID', False)}",
            f"  AllowHostIPC:         {scc.get('allowHostIPC', False)}",
            f"  AllowHostDirPlugin:   {scc.get('allowHostDirVolumePlugin', False)}",
            f"  ReadOnlyRootFS:       {scc.get('readOnlyRootFilesystem', False)}",
            f"  AllowPrivEscalation:  {scc.get('allowPrivilegeEscalation', '')}",
            f"  FSGroup:              {scc.get('fsGroup', {}).get('type', '?')}",
            f"  RunAsUser:            {scc.get('runAsUser', {}).get('type', '?')}",
            f"  SELinuxContext:       {scc.get('seLinuxContext', {}).get('type', '?')}",
            f"  SupplementalGroups:   {scc.get('supplementalGroups', {}).get('type', '?')}",
            "\nVolumes:",
        ]
        for v in scc.get("volumes", []):
            lines.append(f"  - {v}")
        allowed_caps = scc.get("allowedCapabilities") or []
        default_caps = scc.get("defaultAddCapabilities") or []
        required_drop = scc.get("requiredDropCapabilities") or []
        if allowed_caps:
            lines.append(f"\nAllowedCapabilities:      {', '.join(allowed_caps)}")
        if default_caps:
            lines.append(f"DefaultAddCapabilities:   {', '.join(default_caps)}")
        if required_drop:
            lines.append(f"RequiredDropCapabilities: {', '.join(required_drop)}")
        users = scc.get("users", [])
        groups = scc.get("groups", [])
        if users:
            lines.append(f"\nUsers:  {', '.join(users)}")
        if groups:
            lines.append(f"Groups: {', '.join(groups)}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_scc(
    name: str,
    privileged: bool = False,
    host_network: bool = False,
    host_pid: bool = False,
    run_as_any: bool = False,
    allow_privilege_escalation: bool = False,
    cluster: str = "",
) -> str:
    """Create a custom SecurityContextConstraint CR.
    run_as_any: if True, sets RunAsAny for runAsUser and fsGroup.
    allow_privilege_escalation: if True, allows processes to gain more privileges than their parent (required for setuid binaries)."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "security.openshift.io/v1",
            "kind": "SecurityContextConstraints",
            "metadata": {"name": name},
            "allowPrivilegedContainer": privileged,
            "allowHostNetwork": host_network,
            "allowHostPID": host_pid,
            "allowHostIPC": False,
            "allowHostDirVolumePlugin": False,
            "allowPrivilegeEscalation": allow_privilege_escalation,
            "allowedCapabilities": [],
            "defaultAddCapabilities": [],
            "requiredDropCapabilities": ["KILL", "MKNOD", "SETUID", "SETGID"],
            "fsGroup": {"type": "RunAsAny" if run_as_any else "MustRunAs"},
            "runAsUser": {"type": "RunAsAny" if run_as_any else "MustRunAsRange"},
            "seLinuxContext": {"type": "MustRunAs"},
            "supplementalGroups": {"type": "RunAsAny"},
            "seccompProfiles": ["*"],
            "volumes": [
                "configMap", "downwardAPI", "emptyDir",
                "persistentVolumeClaim", "projected", "secret",
            ],
            "users": [],
            "groups": [],
        }
        c.create_custom(*_SCC, body)
        return (
            f"SCC '{name}' created (privileged={privileged}, hostNetwork={host_network}, "
            f"hostPID={host_pid}, runAsAny={run_as_any}, allowPrivilegeEscalation={allow_privilege_escalation})."
        )
    except Exception as e:
        return format_error(e)


@mcp.tool()
def add_scc_to_service_account(
    scc_name: str, service_account: str, namespace: str, cluster: str = ""
) -> str:
    """Grant an SCC to a ServiceAccount via 'oc adm policy add-scc-to-user'.
    Equivalent to: oc adm policy add-scc-to-user <scc> system:serviceaccount:<ns>:<sa>"""
    try:
        c = get_client(cluster)
        subject = f"system:serviceaccount:{namespace}:{service_account}"
        ok, out = run_oc(c.oc_args() + ["adm", "policy", "add-scc-to-user", scc_name, subject])
        return out if ok else f"Error:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def remove_scc_from_service_account(
    scc_name: str, service_account: str, namespace: str, cluster: str = ""
) -> str:
    """Revoke an SCC from a ServiceAccount via 'oc adm policy remove-scc-from-user'."""
    try:
        c = get_client(cluster)
        subject = f"system:serviceaccount:{namespace}:{service_account}"
        ok, out = run_oc(c.oc_args() + ["adm", "policy", "remove-scc-from-user", scc_name, subject])
        return out if ok else f"Error:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def add_cluster_role_to_user(role: str, username: str, cluster: str = "") -> str:
    """Grant a ClusterRole to a user via 'oc adm policy add-cluster-role-to-user'."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "policy", "add-cluster-role-to-user", role, username])
        return out if ok else f"Error:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def add_cluster_role_to_group(role: str, group: str, cluster: str = "") -> str:
    """Grant a ClusterRole to a group via 'oc adm policy add-cluster-role-to-group'."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "policy", "add-cluster-role-to-group", role, group])
        return out if ok else f"Error:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_oauth_config(cluster: str = "") -> str:
    """Get the cluster OAuth configuration and identity providers from config.openshift.io/v1."""
    c = get_client(cluster)
    try:
        oauth = c.get_custom(*_OAUTH, "cluster")
        spec = oauth.get("spec", {})
        token_cfg = spec.get("tokenConfig", {})
        idps = spec.get("identityProviders", [])
        lines = [
            "OAuth Config: cluster",
            f"  AccessTokenMaxAge:             {token_cfg.get('accessTokenMaxAgeSeconds', '')}s",
            f"  AccessTokenInactivityTimeout:  {token_cfg.get('accessTokenInactivityTimeout', '')}",
            f"\nIdentity Providers ({len(idps)}):",
        ]
        for idp in idps:
            idp_type = idp.get("type", "")
            # Fall back to first non-standard key
            if not idp_type:
                idp_type = next(
                    (k for k in idp if k not in ("name", "mappingMethod", "type")), "?"
                )
            lines.append(
                f"  - {idp.get('name', '')}: type={idp_type}  "
                f"mappingMethod={idp.get('mappingMethod', 'claim')}"
            )
            provider_cfg = idp.get(idp_type.lower(), idp.get(idp_type, {}))
            if isinstance(provider_cfg, dict):
                for k, v in provider_cfg.items():
                    if k not in ("clientSecret",) and isinstance(v, str):
                        lines.append(f"      {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_pod_security_violations(namespace: str = "", cluster: str = "") -> str:
    """List events that indicate pod security or SCC violations (FailedCreate + security keywords)."""
    try:
        c = get_client(cluster)
        oc_prefix = c.oc_args()
    except Exception as e:
        return format_error(e)
    args = oc_prefix + ["get", "events", "--field-selector=reason=FailedCreate", "--sort-by=.lastTimestamp"]
    if namespace:
        args += ["-n", namespace]
    else:
        args += ["--all-namespaces"]
    ok, out = run_oc(args)
    if not ok:
        return f"Error fetching events:\n{out}"

    security_keywords = (
        "security", "scc", "forbidden", "privileged", "runasuser",
        "selinux", "capability", "seccomp", "podsecurity",
    )
    header_lines = []
    violation_lines = []
    for line in out.splitlines():
        low = line.lower()
        if line.startswith("NAMESPACE") or line.startswith("LAST") or line.startswith("NAME"):
            header_lines.append(line)
        elif any(kw in low for kw in security_keywords):
            violation_lines.append(line)

    if not violation_lines:
        scope = f"namespace '{namespace}'" if namespace else "all namespaces"
        return (
            f"No pod security violation events found in {scope}.\n\n"
            f"All FailedCreate events:\n{out}"
        )
    return "\n".join(header_lines + violation_lines)
