"""OpenShift AI / RHOAI tools: DSCI, DSC, Notebooks, InferenceServices, Pipelines, Registries."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_DSCI = ("dscinitialization.opendatahub.io", "v1", "dscinitializations")
_DSC = ("datasciencecluster.opendatahub.io", "v1", "datascienceclusters")
_NOTEBOOK = ("kubeflow.org", "v1", "notebooks")
_INFERENCE_SVC = ("serving.kserve.io", "v1beta1", "inferenceservices")
_SERVING_RT = ("serving.kserve.io", "v1alpha1", "servingruntimes")
_CLUSTER_SERVING_RT = ("serving.kserve.io", "v1alpha1", "clusterservingruntimes")
_DSPA = ("datasciencepipelinesapplications.opendatahub.io", "v1alpha1", "datasciencepipelinesapplications")
_MODEL_REG = ("modelregistry.opendatahub.io", "v1alpha1", "modelregistries")

_RHOAI_NAMESPACES = [
    "redhat-ods-operator",
    "redhat-ods-applications",
    "redhat-ods-monitoring",
    "rhods-notebooks",
]

_KEY_CRDS = [
    "notebooks.kubeflow.org",
    "inferenceservices.serving.kserve.io",
    "servingruntimes.serving.kserve.io",
    "datascienceclusters.datasciencecluster.opendatahub.io",
    "dscinitializations.dscinitialization.opendatahub.io",
    "datasciencepipelinesapplications.datasciencepipelinesapplications.opendatahub.io",
    "modelregistries.modelregistry.opendatahub.io",
]

_NOT_FOUND_HINT = {
    _DSCI[2]: "DSCInitialization not found — OpenShift AI (RHOAI) may not be installed.",
    _DSC[2]: "DataScienceCluster not found — OpenShift AI (RHOAI) may not be installed.",
    _NOTEBOOK[2]: "Notebooks not found — kubeflow.org CRD may not be installed.",
    _INFERENCE_SVC[2]: "InferenceServices not found — kserve may not be installed.",
    _SERVING_RT[2]: "ServingRuntimes not found — kserve may not be installed.",
    _DSPA[2]: "DataSciencePipelinesApplications not found — RHOAI Pipelines may not be installed.",
    _MODEL_REG[2]: "ModelRegistries not found — Model Registry may not be enabled.",
}


def _not_found_msg(plural: str) -> str:
    return _NOT_FOUND_HINT.get(plural, f"{plural} not found (404).")


@mcp.tool()
def get_dsci(cluster: str = "") -> str:
    """Get DSCInitialization status: phase, conditions, and component enablement."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_DSCI)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_DSCI[2])
        return format_error(e)
    if not items:
        return _not_found_msg(_DSCI[2])
    dsci = items[0]
    meta = dsci.get("metadata", {})
    spec = dsci.get("spec", {})
    status = dsci.get("status", {})
    lines = [
        f"DSCInitialization: {meta.get('name', '')}",
        f"  Phase:          {status.get('phase', '?')}",
        f"  Age:            {age_string(meta.get('creationTimestamp'))}",
    ]
    # Application namespace
    app_ns = spec.get("applicationsNamespace", "")
    if app_ns:
        lines.append(f"  Apps Namespace: {app_ns}")
    # Service mesh / monitoring config
    monitoring = spec.get("monitoring", {})
    if monitoring:
        lines.append(f"  Monitoring NS:  {monitoring.get('namespace', '')}")
    lines.append("\nConditions:")
    for cond in status.get("conditions", []):
        lines.append(
            f"  {cond.get('type', ''):35s} {cond.get('status', '?'):8s} "
            f"[{age_string(cond.get('lastTransitionTime'))}] {cond.get('message', '')[:80]}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_data_science_cluster(cluster: str = "") -> str:
    """Get DataScienceCluster status: component management states."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_DSC)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_DSC[2])
        return format_error(e)
    if not items:
        return _not_found_msg(_DSC[2])
    dsc = items[0]
    meta = dsc.get("metadata", {})
    spec = dsc.get("spec", {})
    status = dsc.get("status", {})
    lines = [
        f"DataScienceCluster: {meta.get('name', '')}",
        f"  Phase: {status.get('phase', '?')}",
        f"  Age:   {age_string(meta.get('creationTimestamp'))}",
        "\nComponents:",
    ]
    components_spec = spec.get("components", {})
    components_status = status.get("installedComponents", {})
    rows = []
    for comp_name, comp_spec in components_spec.items():
        mgmt_state = comp_spec.get("managementState", "?") if isinstance(comp_spec, dict) else str(comp_spec)
        installed = str(components_status.get(comp_name, ""))
        rows.append([comp_name, mgmt_state, installed])
    lines.append(format_table(["COMPONENT", "MANAGEMENT-STATE", "INSTALLED"], rows))
    lines.append("\nConditions:")
    for cond in status.get("conditions", []):
        lines.append(
            f"  {cond.get('type', ''):40s} {cond.get('status', '?'):8s} "
            f"[{age_string(cond.get('lastTransitionTime'))}]"
        )
    return "\n".join(lines)


@mcp.tool()
def list_data_science_projects(cluster: str = "") -> str:
    """List OpenShift AI Data Science Projects (namespaces with opendatahub.io/dashboard=true label)."""
    import json
    ok, out = run_oc([
        "get", "namespaces",
        "-l", "opendatahub.io/dashboard=true",
        "-o", "json",
    ])
    if not ok:
        return f"Error listing data science projects: {out}"
    try:
        obj = json.loads(out)
        items = obj.get("items", [])
        if not items:
            return "No Data Science Projects found (no namespaces with label opendatahub.io/dashboard=true)."
        rows = []
        for ns in items:
            meta = ns.get("metadata", {})
            status = ns.get("status", {})
            labels = meta.get("labels", {})
            rows.append([
                meta.get("name", ""),
                status.get("phase", "?"),
                labels.get("modelmesh-enabled", ""),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAME", "PHASE", "MODELMESH", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_notebooks(namespace: str = "", cluster: str = "") -> str:
    """List Kubeflow Notebooks with state, image, CPU/memory requests, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_NOTEBOOK, namespace=namespace)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_NOTEBOOK[2])
        return format_error(e)
    rows = []
    for nb in items:
        meta = nb.get("metadata", {})
        annotations = meta.get("annotations", {})
        spec = nb.get("spec", {})
        # State: if kubeflow-resource-stopped annotation is present → Stopped
        stopped_at = annotations.get("kubeflow-resource-stopped", "")
        if stopped_at and stopped_at.lower() not in ("", "false", "null"):
            state = "Stopped"
        else:
            containers = (spec.get("template", {}).get("spec", {}).get("containers", [])
                          or [])
            # Check pod status via status field
            nb_status = nb.get("status", {})
            conditions = nb_status.get("conditions", [])
            running = next(
                (cond.get("status") == "True" for cond in conditions if cond.get("type") == "Running"),
                False,
            )
            state = "Running" if running else "Starting"
        containers = spec.get("template", {}).get("spec", {}).get("containers", [])
        first = containers[0] if containers else {}
        image = first.get("image", "")
        image_short = image.split("/")[-1] if image else ""
        resources = first.get("resources", {}).get("requests", {})
        rows.append([
            meta.get("namespace", ""),
            meta.get("name", ""),
            state,
            image_short[:35],
            resources.get("cpu", "?"),
            resources.get("memory", "?"),
            age_string(meta.get("creationTimestamp")),
        ])
    return format_table(["NAMESPACE", "NAME", "STATE", "IMAGE", "CPU", "MEMORY", "AGE"], rows)


@mcp.tool()
def start_notebook(name: str, namespace: str, cluster: str = "") -> str:
    """Start a stopped Notebook by removing the kubeflow-resource-stopped annotation."""
    c = get_client(cluster)
    try:
        # Setting annotation value to None removes it via strategic merge patch
        c.patch_custom(*_NOTEBOOK, name, {
            "metadata": {"annotations": {"kubeflow-resource-stopped": None}}
        }, namespace)
        return f"Notebook '{namespace}/{name}' start requested (kubeflow-resource-stopped annotation removed)."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def stop_notebook(name: str, namespace: str, cluster: str = "") -> str:
    """Stop a running Notebook by setting the kubeflow-resource-stopped annotation."""
    from datetime import datetime, timezone
    c = get_client(cluster)
    try:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        c.patch_custom(*_NOTEBOOK, name, {
            "metadata": {"annotations": {"kubeflow-resource-stopped": timestamp}}
        }, namespace)
        return f"Notebook '{namespace}/{name}' stop requested (stopped at {timestamp})."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_model_servers(namespace: str = "", cluster: str = "") -> str:
    """List ServingRuntimes and ClusterServingRuntimes with scope, formats, multi-model, and age."""
    c = get_client(cluster)
    rows = []
    # Namespaced ServingRuntimes
    try:
        ns_items = c.list_custom(*_SERVING_RT, namespace=namespace)
        for rt in ns_items:
            meta = rt.get("metadata", {})
            spec = rt.get("spec", {})
            supported = spec.get("supportedModelFormats", [])
            formats = ",".join(f.get("name", "") for f in supported)
            multi_model = str(spec.get("multiModel", False))
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                "Namespaced",
                formats[:40],
                multi_model,
                age_string(meta.get("creationTimestamp")),
            ])
    except Exception as e:
        err = str(e)
        if "404" not in err and "not found" not in err.lower():
            return format_error(e)
    # Cluster-scoped ClusterServingRuntimes
    try:
        cluster_items = c.list_custom(*_CLUSTER_SERVING_RT)
        for rt in cluster_items:
            meta = rt.get("metadata", {})
            spec = rt.get("spec", {})
            supported = spec.get("supportedModelFormats", [])
            formats = ",".join(f.get("name", "") for f in supported)
            multi_model = str(spec.get("multiModel", False))
            rows.append([
                "",
                meta.get("name", ""),
                "Cluster",
                formats[:40],
                multi_model,
                age_string(meta.get("creationTimestamp")),
            ])
    except Exception as e:
        err = str(e)
        if "404" not in err and "not found" not in err.lower():
            return format_error(e)
    if not rows:
        return "No ServingRuntimes or ClusterServingRuntimes found. kserve may not be installed."
    return format_table(["NAMESPACE", "NAME", "SCOPE", "FORMATS", "MULTI-MODEL", "AGE"], rows)


@mcp.tool()
def list_inference_services(namespace: str = "", cluster: str = "") -> str:
    """List InferenceServices with readiness, model format, storage URI, URL, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_INFERENCE_SVC, namespace=namespace)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_INFERENCE_SVC[2])
        return format_error(e)
    rows = []
    for isvc in items:
        meta = isvc.get("metadata", {})
        spec = isvc.get("spec", {})
        status = isvc.get("status", {})
        predictor = spec.get("predictor", {})
        model = predictor.get("model", {})
        model_format = model.get("modelFormat", {}).get("name", "")
        storage_uri = model.get("storageUri", predictor.get("storageUri", ""))
        conditions = status.get("conditions", [])
        ready = next(
            (cond.get("status", "?") for cond in conditions if cond.get("type") == "Ready"),
            "?",
        )
        url = status.get("url", "")
        rows.append([
            meta.get("namespace", ""),
            meta.get("name", ""),
            ready,
            model_format,
            storage_uri[-40:] if storage_uri else "",
            url[-50:] if url else "",
            age_string(meta.get("creationTimestamp")),
        ])
    return format_table(["NAMESPACE", "NAME", "READY", "FORMAT", "STORAGE", "URL", "AGE"], rows)


@mcp.tool()
def create_inference_service(
    name: str,
    namespace: str,
    model_format: str,
    storage_uri: str,
    serving_runtime: str = "",
    min_replicas: int = 1,
    cluster: str = "",
) -> str:
    """Create a KServe InferenceService CR."""
    c = get_client(cluster)
    try:
        model_spec: dict = {
            "modelFormat": {"name": model_format},
            "storageUri": storage_uri,
        }
        if serving_runtime:
            model_spec["runtime"] = serving_runtime
        predictor: dict = {
            "minReplicas": min_replicas,
            "model": model_spec,
        }
        body = {
            "apiVersion": "serving.kserve.io/v1beta1",
            "kind": "InferenceService",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {"predictor": predictor},
        }
        c.create_custom(*_INFERENCE_SVC, body, namespace)
        return (
            f"InferenceService '{namespace}/{name}' created "
            f"(format={model_format}, storage={storage_uri}, minReplicas={min_replicas})."
        )
    except Exception as e:
        return format_error(e)


@mcp.tool()
def delete_inference_service(name: str, namespace: str, cluster: str = "") -> str:
    """Delete a KServe InferenceService."""
    c = get_client(cluster)
    try:
        c.delete_custom(*_INFERENCE_SVC, name, namespace)
        return f"InferenceService '{namespace}/{name}' deleted."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_data_science_pipelines(namespace: str = "", cluster: str = "") -> str:
    """List DataSciencePipelinesApplications with readiness, storage, and API endpoint."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_DSPA, namespace=namespace)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_DSPA[2])
        return format_error(e)
    rows = []
    for dspa in items:
        meta = dspa.get("metadata", {})
        spec = dspa.get("spec", {})
        status = dspa.get("status", {})
        conditions = status.get("conditions", [])
        ready = next(
            (cond.get("status", "?") for cond in conditions if cond.get("type") == "Ready"),
            "?",
        )
        # Storage backend info
        object_storage = spec.get("objectStorage", {})
        storage_type = "external" if object_storage.get("externalStorage") else "managed"
        endpoint = status.get("components", {}).get("apiServer", {}).get("url", "")
        rows.append([
            meta.get("namespace", ""),
            meta.get("name", ""),
            ready,
            storage_type,
            endpoint[-50:] if endpoint else "",
            age_string(meta.get("creationTimestamp")),
        ])
    return format_table(["NAMESPACE", "NAME", "READY", "STORAGE", "ENDPOINT", "AGE"], rows)


@mcp.tool()
def list_model_registries(namespace: str = "", cluster: str = "") -> str:
    """List ModelRegistries with availability, REST port, gRPC port, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_MODEL_REG, namespace=namespace)
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return _not_found_msg(_MODEL_REG[2])
        return format_error(e)
    rows = []
    for mr in items:
        meta = mr.get("metadata", {})
        spec = mr.get("spec", {})
        status = mr.get("status", {})
        conditions = status.get("conditions", [])
        available = next(
            (cond.get("status", "?") for cond in conditions if cond.get("type") == "Available"),
            "?",
        )
        rest_port = spec.get("rest", {}).get("serviceRoute", {})
        # Try common fields for ports
        rest_p = str(spec.get("rest", {}).get("port", spec.get("restPort", "")))
        grpc_p = str(spec.get("grpc", {}).get("port", spec.get("grpcPort", "")))
        rows.append([
            meta.get("namespace", ""),
            meta.get("name", ""),
            available,
            rest_p,
            grpc_p,
            age_string(meta.get("creationTimestamp")),
        ])
    return format_table(["NAMESPACE", "NAME", "AVAILABLE", "REST-PORT", "GRPC-PORT", "AGE"], rows)


@mcp.tool()
def get_rhoai_component_status(cluster: str = "") -> str:
    """Check RHOAI/OpenShift AI overall health: pods in RHOAI namespaces, DSC/DSCI status, CRD presence."""
    import json
    lines = ["RHOAI / OpenShift AI Component Status", "=" * 50]

    # DSC / DSCI
    c = get_client(cluster)
    for label, gvp in [("DSCInitialization", _DSCI), ("DataScienceCluster", _DSC)]:
        try:
            items = c.list_custom(*gvp)
            if not items:
                lines.append(f"{label}: NOT FOUND")
            else:
                obj = items[0]
                status = obj.get("status", {})
                lines.append(f"{label}: {obj.get('metadata', {}).get('name', '')}  "
                              f"phase={status.get('phase', '?')}")
        except Exception as e:
            err = str(e)
            if "404" in err or "not found" in err.lower():
                lines.append(f"{label}: NOT INSTALLED (CRD missing)")
            else:
                lines.append(f"{label}: ERROR — {err[:80]}")

    # CRD presence check
    lines.append("\nKey CRDs:")
    ok, crd_out = run_oc(["get", "crds", "-o", "name"])
    installed_crds: set[str] = set()
    if ok:
        for line in crd_out.splitlines():
            installed_crds.add(line.strip().removeprefix("customresourcedefinition.apiextensions.k8s.io/"))
    for crd_name in _KEY_CRDS:
        present = "PRESENT" if crd_name in installed_crds else "MISSING"
        lines.append(f"  {crd_name}: {present}")

    # Pod summary per RHOAI namespace
    lines.append("\nPod Status by Namespace:")
    for ns in _RHOAI_NAMESPACES:
        ok, out = run_oc(["get", "pods", "-n", ns, "-o", "json", "--ignore-not-found"])
        if not ok:
            # Namespace may not exist
            lines.append(f"  [{ns}] — namespace not found or error")
            continue
        try:
            obj = json.loads(out) if out.strip() else {"items": []}
            pods = obj.get("items", [])
            if not pods:
                lines.append(f"  [{ns}] — no pods")
                continue
            total = len(pods)
            running = sum(
                1 for p in pods
                if p.get("status", {}).get("phase") == "Running"
            )
            not_running = [
                f"{p.get('metadata',{}).get('name','')}({p.get('status',{}).get('phase','?')})"
                for p in pods
                if p.get("status", {}).get("phase") not in ("Running", "Succeeded")
            ]
            status_str = f"{running}/{total} Running"
            if not_running:
                status_str += f"  NOT-OK: {', '.join(not_running[:5])}"
            lines.append(f"  [{ns}] {status_str}")
        except Exception:
            lines.append(f"  [{ns}] — could not parse pod list")

    return "\n".join(lines)
