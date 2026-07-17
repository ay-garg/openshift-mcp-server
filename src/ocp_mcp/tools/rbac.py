"""RBAC tools: OpenShift Users/Groups, Roles, ClusterRoles, RoleBindings, access review."""

from __future__ import annotations

from kubernetes import client as k8s_client

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_USER = ("user.openshift.io", "v1", "users")
_GROUP = ("user.openshift.io", "v1", "groups")


@mcp.tool()
def list_users(cluster: str = "") -> str:
    """List OpenShift users with their identities and group memberships."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_USER)
        rows = []
        for user in items:
            meta = user.get("metadata", {})
            identities = ",".join(user.get("identities") or [])
            groups = ",".join(user.get("groups") or [])
            rows.append([
                meta.get("name", ""),
                identities[:60],
                groups[:60],
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAME", "IDENTITIES", "GROUPS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_user(name: str, cluster: str = "") -> str:
    """Get OpenShift user details: full name, identities, and group memberships."""
    c = get_client(cluster)
    try:
        user = c.get_custom(*_USER, name)
        meta = user.get("metadata", {})
        lines = [
            f"User: {name}",
            f"  FullName: {user.get('fullName', '')}",
            f"  Age:      {age_string(meta.get('creationTimestamp'))}",
            "\nIdentities:",
        ]
        identities = user.get("identities") or []
        if identities:
            for ident in identities:
                lines.append(f"  - {ident}")
        else:
            lines.append("  (none)")
        lines.append("\nGroups:")
        groups = user.get("groups") or []
        if groups:
            for grp in groups:
                lines.append(f"  - {grp}")
        else:
            lines.append("  (none)")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_groups(cluster: str = "") -> str:
    """List OpenShift Groups with member count and up to 5 member names."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_GROUP)
        rows = []
        for grp in items:
            meta = grp.get("metadata", {})
            users = grp.get("users") or []
            preview = ",".join(users[:5]) + ("..." if len(users) > 5 else "")
            rows.append([
                meta.get("name", ""),
                str(len(users)),
                preview,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAME", "MEMBERS", "USERS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_group(name: str, cluster: str = "") -> str:
    """Create an empty OpenShift Group."""
    c = get_client(cluster)
    try:
        body = {
            "apiVersion": "user.openshift.io/v1",
            "kind": "Group",
            "metadata": {"name": name},
            "users": [],
        }
        c.create_custom(*_GROUP, body)
        return f"Group '{name}' created."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def add_user_to_group(group_name: str, username: str, cluster: str = "") -> str:
    """Add a user to an OpenShift Group (atomic — uses oc adm groups add-users)."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "groups", "add-users", group_name, username])
        return out if ok else f"Error: {out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def remove_user_from_group(group_name: str, username: str, cluster: str = "") -> str:
    """Remove a user from an OpenShift Group (atomic — uses oc adm groups remove-users)."""
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["adm", "groups", "remove-users", group_name, username])
        return out if ok else f"Error: {out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_roles(namespace: str = "default", cluster: str = "") -> str:
    """List Roles in a namespace with the number of policy rules."""
    c = get_client(cluster)
    try:
        roles = c.rbac_v1.list_namespaced_role(namespace)
        rows = []
        for role in roles.items:
            rows.append([
                role.metadata.namespace,
                role.metadata.name,
                str(len(role.rules or [])),
                age_string(role.metadata.creation_timestamp),
            ])
        return format_table(["NAMESPACE", "NAME", "RULES", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_cluster_roles(label_selector: str = "", cluster: str = "") -> str:
    """List ClusterRoles with the number of policy rules."""
    c = get_client(cluster)
    try:
        roles = c.rbac_v1.list_cluster_role(label_selector=label_selector)
        rows = []
        for role in roles.items:
            rows.append([
                role.metadata.name,
                str(len(role.rules or [])),
                age_string(role.metadata.creation_timestamp),
            ])
        return format_table(["NAME", "RULES", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_role_bindings(namespace: str = "default", cluster: str = "") -> str:
    """List RoleBindings in a namespace with role reference and bound subjects."""
    c = get_client(cluster)
    try:
        bindings = c.rbac_v1.list_namespaced_role_binding(namespace)
        rows = []
        for rb in bindings.items:
            role_ref = f"{rb.role_ref.kind}/{rb.role_ref.name}"
            subjects = ", ".join(f"{s.kind}/{s.name}" for s in (rb.subjects or []))
            rows.append([
                rb.metadata.namespace,
                rb.metadata.name,
                role_ref,
                subjects[:80],
                age_string(rb.metadata.creation_timestamp),
            ])
        return format_table(["NAMESPACE", "NAME", "ROLE", "SUBJECTS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_cluster_role_bindings(label_selector: str = "", cluster: str = "") -> str:
    """List ClusterRoleBindings with role reference and bound subjects."""
    c = get_client(cluster)
    try:
        bindings = c.rbac_v1.list_cluster_role_binding(label_selector=label_selector)
        rows = []
        for rb in bindings.items:
            role_ref = f"{rb.role_ref.kind}/{rb.role_ref.name}"
            subjects = ", ".join(f"{s.kind}/{s.name}" for s in (rb.subjects or []))
            rows.append([
                rb.metadata.name,
                role_ref,
                subjects[:80],
                age_string(rb.metadata.creation_timestamp),
            ])
        return format_table(["NAME", "ROLE", "SUBJECTS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_role_binding(
    name: str,
    namespace: str,
    role_name: str,
    subject_kind: str,
    subject_name: str,
    subject_namespace: str = "",
    cluster_role: bool = False,
    cluster: str = "",
) -> str:
    """Create a RoleBinding in a namespace.
    subject_kind: User, Group, or ServiceAccount.
    cluster_role: if True, references a ClusterRole instead of a Role."""
    c = get_client(cluster)
    try:
        role_kind = "ClusterRole" if cluster_role else "Role"
        api_group = "rbac.authorization.k8s.io"
        subject = k8s_client.V1Subject(
            kind=subject_kind,
            name=subject_name,
            api_group=api_group if subject_kind in ("User", "Group") else "",
        )
        if subject_namespace:
            subject.namespace = subject_namespace
        body = k8s_client.V1RoleBinding(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            role_ref=k8s_client.V1RoleRef(
                api_group=api_group,
                kind=role_kind,
                name=role_name,
            ),
            subjects=[subject],
        )
        c.rbac_v1.create_namespaced_role_binding(namespace, body)
        return (f"RoleBinding '{namespace}/{name}' created: "
                f"{role_kind}/{role_name} -> {subject_kind}/{subject_name}.")
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_role_binding(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Delete a RoleBinding."""
    c = get_client(cluster)
    try:
        c.rbac_v1.delete_namespaced_role_binding(name, namespace)
        return f"RoleBinding '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_user_access(username: str, namespace: str = "", cluster: str = "") -> str:
    """List all actions a user can perform using 'oc auth can-i --list --as=<username>'.
    Specify namespace to scope the check; omit for cluster-wide actions."""
    try:
        c = get_client(cluster)
    except Exception as e:
        return format_error(e)
    args = c.oc_args() + ["auth", "can-i", "--list", f"--as={username}"]
    if namespace:
        args += ["-n", namespace]
    ok, out = run_oc(args, timeout=30)
    scope = f"in namespace '{namespace}'" if namespace else "(cluster-wide)"
    if not ok:
        return f"Error checking access for '{username}' {scope}:\n{out}"
    return f"Access for user '{username}' {scope}:\n{out}"
