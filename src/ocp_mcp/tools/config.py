"""Config tools: ConfigMaps, Secrets, ServiceAccounts."""

from __future__ import annotations

from kubernetes import client as k8s_client

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc


def _parse_kv_pairs(raw: str) -> dict:
    """Parse KEY=VALUE pairs separated by newlines or commas into a dict."""
    result: dict[str, str] = {}
    # Prefer newline splitting; fall back to comma when no newlines present
    separator = "\n" if "\n" in raw else ","
    for token in raw.split(separator):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, _, v = token.partition("=")
            result[k.strip()] = v
    return result


@mcp.tool()
def list_configmaps(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List ConfigMaps with namespace, name, key count, and age."""
    c = get_client(cluster)
    try:
        if namespace:
            cms = c.core_v1.list_namespaced_config_map(namespace, label_selector=label_selector)
        else:
            cms = c.core_v1.list_config_map_for_all_namespaces(label_selector=label_selector)
        rows = []
        for cm in cms.items:
            key_count = len(cm.data or {}) + len(cm.binary_data or {})
            rows.append([
                cm.metadata.namespace,
                cm.metadata.name,
                str(key_count),
                age_string(cm.metadata.creation_timestamp),
            ])
        return format_table(["NAMESPACE", "NAME", "KEYS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_configmap(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Get ConfigMap keys and values. Values longer than 200 characters are truncated."""
    c = get_client(cluster)
    try:
        cm = c.core_v1.read_namespaced_config_map(name, namespace)
        lines = [
            f"ConfigMap: {namespace}/{name}",
            f"Age: {age_string(cm.metadata.creation_timestamp)}",
            "",
        ]
        data = cm.data or {}
        binary = cm.binary_data or {}
        if not data and not binary:
            lines.append("(empty — no data keys)")
        else:
            if data:
                lines.append("Data:")
                for k in sorted(data):
                    v = data[k]
                    if len(v) > 200:
                        v = v[:200] + "... [truncated]"
                    lines.append(f"  {k}: {v}")
            if binary:
                lines.append("BinaryData:")
                for k in sorted(binary):
                    lines.append(f"  {k}: <binary>")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_configmap(name: str, namespace: str, data: str, cluster: str = "") -> str:
    """Create a ConfigMap. data is KEY=VALUE pairs separated by newlines or commas.
    Example: KEY1=value1\\nKEY2=value2"""
    c = get_client(cluster)
    try:
        data_dict = _parse_kv_pairs(data)
        if not data_dict:
            return "Error: no valid KEY=VALUE pairs parsed from 'data'."
        body = k8s_client.V1ConfigMap(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            data=data_dict,
        )
        c.core_v1.create_namespaced_config_map(namespace, body)
        return (f"ConfigMap '{namespace}/{name}' created with {len(data_dict)} key(s): "
                + ", ".join(sorted(data_dict)))
    except Exception as e:
        return format_error(e)


@mcp.tool()
def update_configmap(name: str, namespace: str, key: str, value: str, cluster: str = "") -> str:
    """Set or update a single key in a ConfigMap using strategic merge patch."""
    c = get_client(cluster)
    try:
        c.core_v1.patch_namespaced_config_map(name, namespace, {"data": {key: value}})
        return f"ConfigMap '{namespace}/{name}': key '{key}' updated."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_configmap(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Delete a ConfigMap."""
    c = get_client(cluster)
    try:
        c.core_v1.delete_namespaced_config_map(name, namespace)
        return f"ConfigMap '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_secrets(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List Secrets showing type and key count only — secret values are never displayed."""
    c = get_client(cluster)
    try:
        if namespace:
            secrets = c.core_v1.list_namespaced_secret(namespace, label_selector=label_selector)
        else:
            secrets = c.core_v1.list_secret_for_all_namespaces(label_selector=label_selector)
        rows = []
        for sec in secrets.items:
            key_count = len(sec.data or {})
            rows.append([
                sec.metadata.namespace,
                sec.metadata.name,
                sec.type or "",
                str(key_count),
                age_string(sec.metadata.creation_timestamp),
            ])
        return format_table(["NAMESPACE", "NAME", "TYPE", "KEYS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_secret_keys(name: str, namespace: str = "default", cluster: str = "") -> str:
    """List the key names of a Secret. Values are never shown for security."""
    c = get_client(cluster)
    try:
        sec = c.core_v1.read_namespaced_secret(name, namespace)
        keys = sorted((sec.data or {}).keys())
        lines = [
            f"Secret: {namespace}/{name}",
            f"Type:   {sec.type}",
            f"Age:    {age_string(sec.metadata.creation_timestamp)}",
            f"Keys ({len(keys)}):",
        ]
        for k in keys:
            lines.append(f"  - {k}")
        if not keys:
            lines.append("  (no keys)")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_service_accounts(namespace: str = "", cluster: str = "") -> str:
    """List ServiceAccounts with number of secrets and image pull secrets."""
    c = get_client(cluster)
    try:
        if namespace:
            sas = c.core_v1.list_namespaced_service_account(namespace)
        else:
            sas = c.core_v1.list_service_account_for_all_namespaces()
        rows = []
        for sa in sas.items:
            rows.append([
                sa.metadata.namespace,
                sa.metadata.name,
                str(len(sa.secrets or [])),
                str(len(sa.image_pull_secrets or [])),
                age_string(sa.metadata.creation_timestamp),
            ])
        return format_table(["NAMESPACE", "NAME", "SECRETS", "IMAGE-PULL-SECRETS", "AGE"], rows)
    except Exception as e:
        return format_error(e)
