"""
OpenShift workload MCP tools.

Covers: Pods, Deployments, StatefulSets, DaemonSets, Jobs, CronJobs,
DeploymentConfigs (OpenShift-specific), and rollout operations.
"""

from __future__ import annotations

from kubernetes import client as k8s_client

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------

@mcp.tool()
def list_pods(
    namespace: str = "",
    label_selector: str = "",
    field_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List pods with NAMESPACE, NAME, STATUS, READY, RESTARTS, NODE, and AGE columns.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector (e.g. "app=nginx").
        field_selector: Field selector (e.g. "status.phase=Running").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector
        if field_selector:
            kwargs["field_selector"] = field_selector

        if namespace:
            pods = c.core_v1.list_namespaced_pod(namespace, **kwargs)
        else:
            pods = c.core_v1.list_pod_for_all_namespaces(**kwargs)

        items = pods.items or []
        if not items:
            return "No pods found."

        headers = ["NAMESPACE", "NAME", "STATUS", "READY", "RESTARTS", "NODE", "AGE"]
        rows = []
        for pod in items:
            ns = pod.metadata.namespace or ""
            name = pod.metadata.name or ""
            phase = pod.status.phase or "Unknown"

            # Determine effective status (matches kubectl behaviour)
            container_statuses = pod.status.container_statuses or []
            init_statuses = pod.status.init_container_statuses or []

            # Check for explicit deletion
            if pod.metadata.deletion_timestamp:
                phase = "Terminating"

            # Override phase with container-level waiting/error reasons
            if phase not in ("Succeeded", "Failed", "Terminating"):
                for cs in container_statuses:
                    if cs.state and cs.state.waiting and cs.state.waiting.reason:
                        phase = cs.state.waiting.reason
                        break

            ready_count = sum(1 for cs in container_statuses if cs.ready)
            total_count = len(pod.spec.containers) if pod.spec and pod.spec.containers else 0
            ready_str = f"{ready_count}/{total_count}"

            restarts = sum(cs.restart_count or 0 for cs in container_statuses)

            node_name = pod.spec.node_name or "<none>" if pod.spec else "<none>"
            age = age_string(pod.metadata.creation_timestamp)

            rows.append([ns, name, phase, ready_str, str(restarts), node_name, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing pods: {format_error(exc)}"


@mcp.tool()
def get_pod(name: str, namespace: str = "default", cluster: str = "") -> str:
    """
    Show detailed information for a pod: phase, node, IP, QoS class, container states, and conditions.

    Args:
        name: Pod name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        pod = c.core_v1.read_namespaced_pod(name, namespace)

        meta = pod.metadata
        spec = pod.spec
        status = pod.status

        lines = [
            f"=== Pod: {namespace}/{name} ===",
            f"  Phase             : {status.phase or 'Unknown'}",
            f"  Node              : {spec.node_name or '<none>'}",
            f"  Pod IP            : {status.pod_ip or '<none>'}",
            f"  Host IP           : {status.host_ip or '<none>'}",
            f"  QoS Class         : {status.qos_class or 'unknown'}",
            f"  Service Account   : {spec.service_account_name or '<none>'}",
            f"  Age               : {age_string(meta.creation_timestamp)}",
        ]

        if meta.deletion_timestamp:
            lines.append(f"  Terminating since : {age_string(meta.deletion_timestamp)}")

        # Containers
        container_statuses = {cs.name: cs for cs in (status.container_statuses or [])}
        lines += ["", "=== Containers ==="]
        for container in spec.containers or []:
            cs = container_statuses.get(container.name)
            lines.append(f"  [{container.name}]")
            lines.append(f"    Image    : {container.image}")
            if cs:
                lines.append(f"    Ready    : {cs.ready}  |  Restarts: {cs.restart_count}")
                st = cs.state
                if st:
                    if st.running:
                        lines.append(f"    State    : Running (started {age_string(st.running.started_at)})")
                    elif st.waiting:
                        lines.append(f"    State    : Waiting — {st.waiting.reason or ''}: {st.waiting.message or ''}")
                    elif st.terminated:
                        t = st.terminated
                        lines.append(
                            f"    State    : Terminated — exit {t.exit_code}  reason: {t.reason or ''}"
                        )
                last = cs.last_state
                if last and last.terminated:
                    lt = last.terminated
                    lines.append(
                        f"    LastState: Terminated — exit {lt.exit_code}  "
                        f"finished {age_string(lt.finished_at)}"
                    )

            # Resource requests/limits
            res = container.resources
            if res:
                req = res.requests or {}
                lim = res.limits or {}
                if req or lim:
                    lines.append(
                        f"    Resources: requests cpu={req.get('cpu', '-')} mem={req.get('memory', '-')}  "
                        f"limits cpu={lim.get('cpu', '-')} mem={lim.get('memory', '-')}"
                    )

        # Init containers
        if spec.init_containers:
            init_statuses_map = {cs.name: cs for cs in (status.init_container_statuses or [])}
            lines += ["", "=== Init Containers ==="]
            for ic in spec.init_containers:
                cs = init_statuses_map.get(ic.name)
                state_str = "unknown"
                if cs:
                    st = cs.state
                    if st:
                        if st.running:
                            state_str = "Running"
                        elif st.terminated:
                            state_str = f"Terminated (exit {st.terminated.exit_code})"
                        elif st.waiting:
                            state_str = f"Waiting ({st.waiting.reason or ''})"
                lines.append(f"  {ic.name:<28} {state_str}")

        # Conditions
        conditions = status.conditions or []
        if conditions:
            lines += ["", "=== Conditions ==="]
            cond_rows = [
                [cd.type, cd.status, cd.reason or "", age_string(cd.last_transition_time)]
                for cd in conditions
            ]
            lines.append(format_table(["TYPE", "STATUS", "REASON", "AGE"], cond_rows))

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting pod '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def get_pod_logs(
    name: str,
    namespace: str = "default",
    container: str = "",
    previous: bool = False,
    tail_lines: int = 100,
    since_seconds: int = 0,
    cluster: str = "",
) -> str:
    """
    Fetch logs from a pod container.

    Args:
        name: Pod name.
        namespace: Namespace (default: "default").
        container: Container name (empty = first/only container).
        previous: Return logs from the previous container instance.
        tail_lines: Number of lines from the end (default 100, 0 = unlimited).
        since_seconds: Only return logs newer than this many seconds.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {"previous": previous}
        if container:
            kwargs["container"] = container
        if tail_lines > 0:
            kwargs["tail_lines"] = tail_lines
        if since_seconds > 0:
            kwargs["since_seconds"] = since_seconds

        logs = c.core_v1.read_namespaced_pod_log(name, namespace, **kwargs)
        if not logs:
            return f"No logs returned for pod '{namespace}/{name}'."
        return logs
    except Exception as exc:
        return f"Error getting logs for pod '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def exec_in_pod(
    name: str,
    command: str,
    namespace: str = "default",
    container: str = "",
    cluster: str = "",
) -> str:
    """Execute a command inside a pod via oc exec.
    command is split with shlex — shell metacharacters (pipes, redirects) are not interpreted."""
    import shlex
    try:
        cmd_argv = shlex.split(command)
    except ValueError as e:
        return f"Invalid command syntax: {e}"
    try:
        c = get_client(cluster)
        args = c.oc_args() + ["exec", name, "-n", namespace]
        if container:
            args += ["-c", container]
        args += ["--"] + cmd_argv
        ok, out = run_oc(args, timeout=120)
        if ok:
            return out or "(no output)"
        return f"exec failed:\n{out}"
    except Exception as exc:
        return f"Error exec-ing into pod '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def delete_pod(
    name: str,
    namespace: str = "default",
    force: bool = False,
    cluster: str = "",
) -> str:
    """
    Delete a pod.

    Args:
        name: Pod name.
        namespace: Namespace (default: "default").
        force: Force-delete immediately (grace-period=0).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if force:
            kwargs["grace_period_seconds"] = 0
        c.core_v1.delete_namespaced_pod(name, namespace, **kwargs)
        suffix = " (forced, grace period 0)" if force else ""
        return f"Pod '{namespace}/{name}' deletion initiated{suffix}."
    except Exception as exc:
        return f"Error deleting pod '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def describe_pod(name: str, namespace: str = "default", cluster: str = "") -> str:
    """
    Run 'oc describe pod' for detailed pod information including events.

    Args:
        name: Pod name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ok, out = run_oc(c.oc_args() + ["describe", "pod", name, "-n", namespace])
        if ok:
            return out
        return f"describe pod failed:\n{out}"
    except Exception as exc:
        return f"Error describing pod '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

@mcp.tool()
def list_deployments(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List Deployments with NAMESPACE, NAME, READY, UP-TO-DATE, AVAILABLE, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter deployments.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            deployments = c.apps_v1.list_namespaced_deployment(namespace, **kwargs)
        else:
            deployments = c.apps_v1.list_deployment_for_all_namespaces(**kwargs)

        items = deployments.items or []
        if not items:
            return "No deployments found."

        headers = ["NAMESPACE", "NAME", "READY", "UP-TO-DATE", "AVAILABLE", "AGE"]
        rows = []
        for dep in items:
            ns = dep.metadata.namespace or ""
            name = dep.metadata.name or ""
            spec_replicas = dep.spec.replicas if dep.spec else 0
            status = dep.status or k8s_client.V1DeploymentStatus()
            ready = status.ready_replicas or 0
            up_to_date = status.updated_replicas or 0
            available = status.available_replicas or 0
            ready_str = f"{ready}/{spec_replicas}"
            age = age_string(dep.metadata.creation_timestamp)
            rows.append([ns, name, ready_str, str(up_to_date), str(available), age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing deployments: {format_error(exc)}"


@mcp.tool()
def scale_deployment(
    name: str,
    replicas: int,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Scale a Deployment to the specified number of replicas.

    Args:
        name: Deployment name.
        replicas: Desired replica count.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        scale_body = {"spec": {"replicas": replicas}}
        c.apps_v1.patch_namespaced_deployment_scale(name, namespace, scale_body)
        return f"Deployment '{namespace}/{name}' scaled to {replicas} replicas."
    except Exception as exc:
        return f"Error scaling deployment '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def rollout_restart_deployment(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Trigger a rolling restart of a Deployment (equivalent to 'oc rollout restart').

    Args:
        name: Deployment name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ok, out = run_oc(
            c.oc_args() + ["rollout", "restart", f"deployment/{name}", "-n", namespace]
        )
        if ok:
            return f"Rollout restart triggered for deployment '{namespace}/{name}'.\n{out.strip()}"
        return f"Failed to restart deployment '{namespace}/{name}':\n{out}"
    except Exception as exc:
        return f"Error restarting deployment '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def rollout_undo_deployment(
    name: str,
    namespace: str = "default",
    revision: int = 0,
    cluster: str = "",
) -> str:
    """
    Undo a Deployment rollout, optionally to a specific revision.

    Args:
        name: Deployment name.
        namespace: Namespace (default: "default").
        revision: Target revision number (0 = previous revision).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        args = c.oc_args() + ["rollout", "undo", f"deployment/{name}", "-n", namespace]
        if revision > 0:
            args += [f"--to-revision={revision}"]
        ok, out = run_oc(args)
        if ok:
            return f"Rollout undo successful for deployment '{namespace}/{name}'.\n{out.strip()}"
        return f"Failed to undo rollout for deployment '{namespace}/{name}':\n{out}"
    except Exception as exc:
        return f"Error undoing rollout for deployment '{namespace}/{name}': {format_error(exc)}"


@mcp.tool()
def rollout_status_deployment(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Show the rollout status of a Deployment (equivalent to 'oc rollout status').

    Args:
        name: Deployment name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ok, out = run_oc(
            c.oc_args() + ["rollout", "status", f"deployment/{name}", "-n", namespace],
            timeout=30,
        )
        if ok:
            return out.strip() or f"Deployment '{namespace}/{name}' rollout is complete."
        return f"Rollout status check failed for '{namespace}/{name}':\n{out}"
    except Exception as exc:
        return f"Error checking rollout status for '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# StatefulSets
# ---------------------------------------------------------------------------

@mcp.tool()
def list_statefulsets(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List StatefulSets with NAMESPACE, NAME, READY, SERVICE, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter StatefulSets.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            statefulsets = c.apps_v1.list_namespaced_stateful_set(namespace, **kwargs)
        else:
            statefulsets = c.apps_v1.list_stateful_set_for_all_namespaces(**kwargs)

        items = statefulsets.items or []
        if not items:
            return "No StatefulSets found."

        headers = ["NAMESPACE", "NAME", "READY", "SERVICE", "AGE"]
        rows = []
        for sts in items:
            ns = sts.metadata.namespace or ""
            name = sts.metadata.name or ""
            desired = sts.spec.replicas if sts.spec else 0
            ready = (sts.status.ready_replicas or 0) if sts.status else 0
            service = sts.spec.service_name if sts.spec else ""
            age = age_string(sts.metadata.creation_timestamp)
            rows.append([ns, name, f"{ready}/{desired}", service, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing statefulsets: {format_error(exc)}"


@mcp.tool()
def scale_statefulset(
    name: str,
    replicas: int,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Scale a StatefulSet to the specified number of replicas.

    Args:
        name: StatefulSet name.
        replicas: Desired replica count.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        scale_body = {"spec": {"replicas": replicas}}
        c.apps_v1.patch_namespaced_stateful_set_scale(name, namespace, scale_body)
        return f"StatefulSet '{namespace}/{name}' scaled to {replicas} replicas."
    except Exception as exc:
        return f"Error scaling statefulset '{namespace}/{name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# DaemonSets
# ---------------------------------------------------------------------------

@mcp.tool()
def list_daemonsets(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List DaemonSets with NAMESPACE, NAME, DESIRED, CURRENT, READY, UP-TO-DATE, AVAILABLE, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter DaemonSets.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            daemonsets = c.apps_v1.list_namespaced_daemon_set(namespace, **kwargs)
        else:
            daemonsets = c.apps_v1.list_daemon_set_for_all_namespaces(**kwargs)

        items = daemonsets.items or []
        if not items:
            return "No DaemonSets found."

        headers = ["NAMESPACE", "NAME", "DESIRED", "CURRENT", "READY", "UP-TO-DATE", "AVAILABLE", "AGE"]
        rows = []
        for ds in items:
            ns = ds.metadata.namespace or ""
            name = ds.metadata.name or ""
            st = ds.status or k8s_client.V1DaemonSetStatus(
                current_number_scheduled=0,
                desired_number_scheduled=0,
                number_misscheduled=0,
                number_ready=0,
                observed_generation=0,
            )
            age = age_string(ds.metadata.creation_timestamp)
            rows.append([
                ns,
                name,
                str(st.desired_number_scheduled or 0),
                str(st.current_number_scheduled or 0),
                str(st.number_ready or 0),
                str(st.updated_number_scheduled or 0),
                str(st.number_available or 0),
                age,
            ])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing daemonsets: {format_error(exc)}"


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@mcp.tool()
def list_jobs(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List Jobs with NAMESPACE, NAME, COMPLETIONS, ACTIVE, SUCCEEDED, FAILED, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter Jobs.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            jobs = c.batch_v1.list_namespaced_job(namespace, **kwargs)
        else:
            jobs = c.batch_v1.list_job_for_all_namespaces(**kwargs)

        items = jobs.items or []
        if not items:
            return "No Jobs found."

        headers = ["NAMESPACE", "NAME", "COMPLETIONS", "ACTIVE", "SUCCEEDED", "FAILED", "AGE"]
        rows = []
        for job in items:
            ns = job.metadata.namespace or ""
            name = job.metadata.name or ""
            spec_completions = job.spec.completions if job.spec and job.spec.completions is not None else 1
            st = job.status or k8s_client.V1JobStatus()
            succeeded = st.succeeded or 0
            active = st.active or 0
            failed = st.failed or 0
            completions_str = f"{succeeded}/{spec_completions}"
            age = age_string(job.metadata.creation_timestamp)
            rows.append([ns, name, completions_str, str(active), str(succeeded), str(failed), age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing jobs: {format_error(exc)}"


# ---------------------------------------------------------------------------
# CronJobs
# ---------------------------------------------------------------------------

@mcp.tool()
def list_cronjobs(
    namespace: str = "",
    label_selector: str = "",
    cluster: str = "",
) -> str:
    """
    List CronJobs with NAMESPACE, NAME, SCHEDULE, SUSPEND, ACTIVE, LAST RUN, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        label_selector: Label selector to filter CronJobs.
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        kwargs: dict = {}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if namespace:
            cronjobs = c.batch_v1.list_namespaced_cron_job(namespace, **kwargs)
        else:
            cronjobs = c.batch_v1.list_cron_job_for_all_namespaces(**kwargs)

        items = cronjobs.items or []
        if not items:
            return "No CronJobs found."

        headers = ["NAMESPACE", "NAME", "SCHEDULE", "SUSPEND", "ACTIVE", "LAST RUN", "AGE"]
        rows = []
        for cj in items:
            ns = cj.metadata.namespace or ""
            name = cj.metadata.name or ""
            schedule = cj.spec.schedule if cj.spec else ""
            suspend = str(cj.spec.suspend) if cj.spec else "False"
            st = cj.status or k8s_client.V1CronJobStatus()
            active_count = len(st.active) if st.active else 0
            last_run = age_string(st.last_schedule_time) if st.last_schedule_time else "<never>"
            age = age_string(cj.metadata.creation_timestamp)
            rows.append([ns, name, schedule, suspend, str(active_count), last_run, age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing cronjobs: {format_error(exc)}"


@mcp.tool()
def create_job_from_cronjob(
    cronjob_name: str,
    job_name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Create a Job immediately from a CronJob template (manual trigger).

    Args:
        cronjob_name: Source CronJob name.
        job_name: Name for the newly created Job.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ok, out = run_oc(
            c.oc_args() + [
                "create", "job", job_name,
                f"--from=cronjob/{cronjob_name}",
                "-n", namespace,
            ]
        )
        if ok:
            return f"Job '{namespace}/{job_name}' created from CronJob '{cronjob_name}'.\n{out.strip()}"
        return f"Failed to create job from cronjob:\n{out}"
    except Exception as exc:
        return f"Error creating job from cronjob '{cronjob_name}': {format_error(exc)}"


# ---------------------------------------------------------------------------
# OpenShift DeploymentConfigs
# ---------------------------------------------------------------------------

@mcp.tool()
def list_deployment_configs(
    namespace: str = "",
    cluster: str = "",
) -> str:
    """
    List OpenShift DeploymentConfigs (apps.openshift.io/v1) with NAMESPACE, NAME, REVISION, DESIRED, CURRENT, and AGE.

    Args:
        namespace: Namespace to query (empty = all namespaces).
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        items = c.list_custom(
            "apps.openshift.io", "v1", "deploymentconfigs", namespace=namespace
        )
        if not items:
            return "No DeploymentConfigs found."

        headers = ["NAMESPACE", "NAME", "REVISION", "DESIRED", "CURRENT", "READY", "AGE"]
        rows = []
        for dc in items:
            meta = dc.get("metadata", {})
            ns = meta.get("namespace", "")
            name = meta.get("name", "")
            status = dc.get("status", {})
            spec = dc.get("spec", {})
            revision = status.get("latestVersion", "0")
            desired = spec.get("replicas", 0)
            current = status.get("replicas", 0)
            ready = status.get("readyReplicas", 0)
            age = age_string(meta.get("creationTimestamp"))
            rows.append([ns, name, str(revision), str(desired), str(current), str(ready), age])

        return format_table(headers, rows, max_col=50)
    except Exception as exc:
        return f"Error listing DeploymentConfigs: {format_error(exc)}"


@mcp.tool()
def rollout_deployment_config(
    name: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """
    Trigger a new rollout of an OpenShift DeploymentConfig (oc rollout latest dc/<name>).

    Args:
        name: DeploymentConfig name.
        namespace: Namespace (default: "default").
        cluster: Named cluster to target (empty = default).
    """
    try:
        c = get_client(cluster)
        ok, out = run_oc(
            c.oc_args() + ["rollout", "latest", f"dc/{name}", "-n", namespace]
        )
        if ok:
            return f"Rollout triggered for DeploymentConfig '{namespace}/{name}'.\n{out.strip()}"
        return f"Failed to trigger rollout for DeploymentConfig '{namespace}/{name}':\n{out}"
    except Exception as exc:
        return f"Error rolling out DeploymentConfig '{namespace}/{name}': {format_error(exc)}"
