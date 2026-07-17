"""Tekton Pipelines tools: Pipelines, PipelineRuns, Tasks, TaskRuns, Triggers, EventListeners."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_PIPELINE = ("tekton.dev", "v1", "pipelines")
_PIPELINE_RUN = ("tekton.dev", "v1", "pipelineruns")
_TASK = ("tekton.dev", "v1", "tasks")
_TASK_RUN = ("tekton.dev", "v1", "taskruns")
_TRIGGER_TEMPLATE = ("triggers.tekton.dev", "v1beta1", "triggertemplates")
_EVENT_LISTENER = ("triggers.tekton.dev", "v1beta1", "eventlisteners")


def _duration(start: str | None, end: str | None) -> str:
    """Compute a human-readable duration string like '3m45s' between two ISO timestamps."""
    if not start:
        return ""
    try:
        from datetime import datetime, timezone
        from dateutil.parser import parse as dt_parse

        s = dt_parse(start)
        e = dt_parse(end) if end else datetime.now(timezone.utc)
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        total = int((e - s).total_seconds())
        if total < 0:
            return ""
        m, secs = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m}m{secs}s"
        elif m:
            return f"{m}m{secs}s"
        return f"{secs}s"
    except Exception:
        return ""


def _run_status(conditions: list) -> str:
    """Return a human-readable status string from a list of Tekton conditions."""
    if not conditions:
        return "Pending"
    main = next((c for c in conditions if c.get("type") == "Succeeded"), {})
    status = main.get("status", "")
    reason = main.get("reason", "")
    if status == "True":
        return "Succeeded"
    elif status == "False":
        return f"Failed: {reason}" if reason else "Failed"
    else:
        return f"Running: {reason}" if reason else "Running"


@mcp.tool()
def list_pipelines(namespace: str = "", cluster: str = "") -> str:
    """List Tekton Pipelines with task count and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PIPELINE, namespace=namespace)
        rows = []
        for pl in items:
            spec = pl.get("spec", {})
            tasks = spec.get("tasks", [])
            rows.append([
                pl.get("metadata", {}).get("namespace", ""),
                pl.get("metadata", {}).get("name", ""),
                str(len(tasks)),
                age_string(pl.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "TASKS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_pipeline(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Get Tekton Pipeline details: tasks with dependencies, params, and workspaces."""
    c = get_client(cluster)
    try:
        pl = c.get_custom(*_PIPELINE, name, namespace)
        spec = pl.get("spec", {})
        lines = [
            f"Pipeline: {namespace}/{name}",
            f"  Age: {age_string(pl.get('metadata', {}).get('creationTimestamp'))}",
        ]
        params = spec.get("params", [])
        if params:
            lines.append("\nParams:")
            for p in params:
                default = f" (default={p.get('default', '')})" if "default" in p else ""
                lines.append(f"  {p.get('name', '')}: {p.get('type', 'string')}{default}")
        workspaces = spec.get("workspaces", [])
        if workspaces:
            lines.append("\nWorkspaces:")
            for ws in workspaces:
                optional = " [optional]" if ws.get("optional") else ""
                lines.append(f"  {ws.get('name', '')}{optional}")
        tasks = spec.get("tasks", [])
        if tasks:
            lines.append("\nTasks:")
            rows = []
            for t in tasks:
                run_after = ", ".join(t.get("runAfter", []))
                task_ref = t.get("taskRef", {})
                task_name = task_ref.get("name", task_ref.get("resolver", "?"))
                rows.append([
                    t.get("name", ""),
                    task_name,
                    run_after or "(first)",
                ])
            lines.append(format_table(["STEP-NAME", "TASK-REF", "RUN-AFTER"], rows))
        finally_tasks = spec.get("finally", [])
        if finally_tasks:
            lines.append("\nFinally:")
            for ft in finally_tasks:
                task_ref = ft.get("taskRef", {})
                lines.append(f"  {ft.get('name', '')}: {task_ref.get('name', '?')}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_pipeline_runs(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List Tekton PipelineRuns with pipeline name, status, duration, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_PIPELINE_RUN, namespace=namespace, label_selector=label_selector)
        rows = []
        for pr in items:
            meta = pr.get("metadata", {})
            spec = pr.get("spec", {})
            status = pr.get("status", {})
            pipeline_ref = spec.get("pipelineRef", {})
            pipeline_name = (pipeline_ref.get("name", "")
                             or meta.get("labels", {}).get("tekton.dev/pipeline", ""))
            conditions = status.get("conditions", [])
            run_status = _run_status(conditions)
            duration = _duration(status.get("startTime"), status.get("completionTime"))
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                pipeline_name,
                run_status,
                duration,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "PIPELINE", "STATUS", "DURATION", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_pipeline_run(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Get Tekton PipelineRun details: status, duration, and child task run references."""
    c = get_client(cluster)
    try:
        pr = c.get_custom(*_PIPELINE_RUN, name, namespace)
        meta = pr.get("metadata", {})
        spec = pr.get("spec", {})
        status = pr.get("status", {})
        conditions = status.get("conditions", [])
        run_status = _run_status(conditions)
        duration = _duration(status.get("startTime"), status.get("completionTime"))
        pipeline_ref = spec.get("pipelineRef", {})
        lines = [
            f"PipelineRun: {namespace}/{name}",
            f"  Pipeline:   {pipeline_ref.get('name', '')}",
            f"  Status:     {run_status}",
            f"  Duration:   {duration}",
            f"  Start:      {status.get('startTime', '')}",
            f"  Complete:   {status.get('completionTime', '')}",
        ]
        for cond in conditions:
            if cond.get("message"):
                lines.append(f"  Message:    {cond['message'][:100]}")
        child_refs = status.get("childReferences", [])
        if child_refs:
            lines.append("\nTask Runs:")
            rows = []
            for ref in child_refs:
                rows.append([
                    ref.get("displayName", ref.get("name", "")),
                    ref.get("name", ""),
                    ref.get("kind", "TaskRun"),
                ])
            lines.append(format_table(["STEP", "TASKRUN-NAME", "KIND"], rows))
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def start_pipeline_run(
    pipeline_name: str,
    namespace: str = "default",
    params: str = "",
    cluster: str = "",
) -> str:
    """Start a Tekton PipelineRun. params is a comma-separated list of KEY=VALUE pairs."""
    c = get_client(cluster)
    try:
        import time
        run_name = f"{pipeline_name}-run-{int(time.time())}"
        param_list = []
        if params:
            for pair in params.split(","):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    param_list.append({"name": k.strip(), "value": v.strip()})
        body = {
            "apiVersion": "tekton.dev/v1",
            "kind": "PipelineRun",
            "metadata": {"name": run_name, "namespace": namespace},
            "spec": {
                "pipelineRef": {"name": pipeline_name},
                "params": param_list,
            },
        }
        c.create_custom(*_PIPELINE_RUN, body, namespace)
        return f"PipelineRun '{namespace}/{run_name}' created for pipeline '{pipeline_name}'."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def cancel_pipeline_run(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Cancel a running Tekton PipelineRun."""
    c = get_client(cluster)
    try:
        c.patch_custom(*_PIPELINE_RUN, name, {"spec": {"status": "CancelledRunFinally"}}, namespace)
        return f"PipelineRun '{namespace}/{name}' cancellation requested (spec.status=CancelledRunFinally)."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_tasks(namespace: str = "", cluster: str = "") -> str:
    """List Tekton Tasks with step count and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_TASK, namespace=namespace)
        rows = []
        for task in items:
            spec = task.get("spec", {})
            steps = spec.get("steps", [])
            rows.append([
                task.get("metadata", {}).get("namespace", ""),
                task.get("metadata", {}).get("name", ""),
                str(len(steps)),
                age_string(task.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "STEPS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_task_runs(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List Tekton TaskRuns with task name, status, duration, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_TASK_RUN, namespace=namespace, label_selector=label_selector)
        rows = []
        for tr in items:
            meta = tr.get("metadata", {})
            spec = tr.get("spec", {})
            status = tr.get("status", {})
            task_ref = spec.get("taskRef", {})
            task_name = (task_ref.get("name", "")
                         or meta.get("labels", {}).get("tekton.dev/task", ""))
            conditions = status.get("conditions", [])
            run_status = _run_status(conditions)
            duration = _duration(status.get("startTime"), status.get("completionTime"))
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                task_name,
                run_status,
                duration,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "TASK", "STATUS", "DURATION", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_trigger_templates(namespace: str = "", cluster: str = "") -> str:
    """List Tekton TriggerTemplates with template count and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_TRIGGER_TEMPLATE, namespace=namespace)
        rows = []
        for tt in items:
            spec = tt.get("spec", {})
            resource_templates = spec.get("resourcetemplates", [])
            rows.append([
                tt.get("metadata", {}).get("namespace", ""),
                tt.get("metadata", {}).get("name", ""),
                str(len(resource_templates)),
                age_string(tt.get("metadata", {}).get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "TEMPLATES", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_event_listeners(namespace: str = "", cluster: str = "") -> str:
    """List Tekton EventListeners with readiness, URL, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_EVENT_LISTENER, namespace=namespace)
        rows = []
        for el in items:
            meta = el.get("metadata", {})
            status = el.get("status", {})
            conditions = status.get("conditions", [])
            ready = next(
                (cond.get("status", "?") for cond in conditions if cond.get("type") == "Ready"),
                "?",
            )
            url = status.get("address", {}).get("url", "")
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                ready,
                url,
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "READY", "URL", "AGE"], rows)
    except Exception as e:
        return format_error(e)
