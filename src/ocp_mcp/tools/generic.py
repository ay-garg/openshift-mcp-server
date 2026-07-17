"""Generic/escape-hatch tools: apply manifests, generic get/delete, run oc, list CRDs."""

from __future__ import annotations

import shlex

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

# Verbs blocked because typed tools (delete_resource, exec_in_pod) exist for these
# and include confirmation prompts. Checked case-insensitively against the parsed
# first token so "Delete", "DELETE", "delete\t..." all match.
_BLOCKED_VERBS = frozenset({
    "delete",   # use delete_resource tool
    "rm",       # alias for delete on some plugins
    "exec",     # use exec_in_pod tool; enables arbitrary code execution in pods
    "replace",  # full resource overwrite with no typed tool and no confirmation
})
# Note: shell metacharacter patterns (| > eval) are NOT checked here because
# run_oc uses subprocess with shell=False — they are harmless literal argv tokens.


@mcp.tool()
def apply_manifest(yaml_content: str, namespace: str = "", cluster: str = "") -> str:
    """Apply a YAML or JSON manifest to the cluster via 'oc apply -f -'.
    WARNING: This applies resources directly. Review manifests before applying."""
    try:
        c = get_client(cluster)
        args = c.oc_args() + ["apply", "-f", "-"]
        if namespace:
            args += ["-n", namespace]
        ok, out = run_oc(args, stdin=yaml_content, timeout=60)
        return out if ok else f"Apply failed:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_resource(resource_type: str, name: str, namespace: str = "", force: bool = False, cluster: str = "") -> str:
    """Delete any Kubernetes/OpenShift resource by type and name.
    WARNING: Destructive operation. Confirm the resource name before proceeding."""
    try:
        c = get_client(cluster)
        args = c.oc_args() + ["delete", resource_type, name]
        if namespace:
            args += ["-n", namespace]
        if force:
            args += ["--grace-period=0", "--force"]
        ok, out = run_oc(args, timeout=60)
        return out if ok else f"Delete failed:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_resource(resource_type: str, name: str, namespace: str = "", output: str = "yaml", cluster: str = "") -> str:
    """Get any resource in YAML, JSON, or wide format. Use output='describe' for oc describe."""
    try:
        c = get_client(cluster)
        oc_prefix = c.oc_args()
        if output == "describe":
            args = oc_prefix + ["describe", resource_type, name]
        else:
            args = oc_prefix + ["get", resource_type, name, f"-o={output}"]
        if namespace:
            args += ["-n", namespace]
        ok, out = run_oc(args, timeout=30)
        return out if ok else f"Error:\n{out}"
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_custom_resources(group: str, version: str, plural: str, namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List any custom resource by group/version/plural — works for any CRD."""
    c = get_client(cluster)
    try:
        items = c.list_custom(group, version, plural, namespace=namespace, label_selector=label_selector)
        if not items:
            return f"No {plural}.{group}/{version} resources found."
        rows = []
        for item in items:
            meta = item.get("metadata", {})
            rows.append([meta.get("namespace", ""), meta.get("name", ""),
                         age_string(meta.get("creationTimestamp"))])
        return (f"Resource: {plural}.{group}/{version}\n"
                + format_table(["NAMESPACE", "NAME", "AGE"], rows))
    except Exception as e:
        return format_error(e)


@mcp.tool()
def run_oc_command(args: str, cluster: str = "") -> str:
    """Escape hatch: run any oc command. args is a space-separated string of arguments.
    WARNING: Use carefully. Destructive commands should be confirmed first."""
    try:
        parsed_args = shlex.split(args)
    except ValueError as e:
        return f"Failed to parse args: {e}"
    if not parsed_args:
        return "Error: no command provided."
    if parsed_args[0].lower() in _BLOCKED_VERBS:
        return (f"Blocked: '{parsed_args[0]}' is not allowed in run_oc_command. "
                f"Use the typed tool (delete_resource, exec_in_pod) instead.")
    try:
        c = get_client(cluster)
    except Exception as e:
        return format_error(e)
    ok, out = run_oc(c.oc_args() + parsed_args, timeout=120)
    return out if ok else f"Error:\n{out}"


@mcp.tool()
def list_crds(label_selector: str = "", cluster: str = "") -> str:
    """List all CustomResourceDefinitions with group, stored versions, and scope."""
    c = get_client(cluster)
    try:
        items = c.list_custom("apiextensions.k8s.io", "v1", "customresourcedefinitions",
                              label_selector=label_selector)
        rows = []
        for crd in items:
            spec = crd.get("spec", {})
            versions = ",".join(v.get("name","") for v in spec.get("versions",[]) if v.get("storage"))
            rows.append([crd.get("metadata", {}).get("name", ""),
                         spec.get("group", ""),
                         spec.get("names", {}).get("kind", ""),
                         versions,
                         spec.get("scope", "?"),
                         age_string(crd.get("metadata", {}).get("creationTimestamp"))])
        rows.sort(key=lambda r: r[0])
        return format_table(["NAME", "GROUP", "KIND", "VERSIONS", "SCOPE", "AGE"], rows)
    except Exception as e:
        return format_error(e)
