"""Build tools: BuildConfigs, Builds, ImageStreams — build.openshift.io/v1 and image.openshift.io/v1."""

from __future__ import annotations

from datetime import datetime, timezone

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client, run_oc

_BC = ("build.openshift.io", "v1", "buildconfigs")
_BUILD = ("build.openshift.io", "v1", "builds")
_IS = ("image.openshift.io", "v1", "imagestreams")


def _build_duration(status: dict) -> str:
    """Compute human-readable build duration from status timestamps."""
    start = status.get("startTimestamp") or status.get("startTime", "")
    end = status.get("completionTimestamp", "")
    if not start or not end:
        return ""
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        s = datetime.strptime(start, fmt).replace(tzinfo=timezone.utc)
        e = datetime.strptime(end, fmt).replace(tzinfo=timezone.utc)
        secs = int((e - s).total_seconds())
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m{secs % 60}s"
    except Exception:
        return ""


@mcp.tool()
def list_build_configs(namespace: str = "", cluster: str = "") -> str:
    """List BuildConfigs with strategy type, source, last version, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_BC, namespace=namespace)
        rows = []
        for bc in items:
            meta = bc.get("metadata", {})
            spec = bc.get("spec", {})
            strategy_type = spec.get("strategy", {}).get("type", "?")
            source = spec.get("source", {})
            source_type = source.get("type", "?")
            git_uri = (source.get("git") or {}).get("uri", "")
            source_str = f"{source_type}:{git_uri}" if git_uri else source_type
            last_ver = bc.get("status", {}).get("lastVersion", 0)
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                strategy_type,
                source_str[:50],
                str(last_ver),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "STRATEGY", "SOURCE", "LAST-VER", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_build_config(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Describe a BuildConfig in detail using oc describe bc."""
    args = ["describe", "bc", name, "-n", namespace]
    ok, out = run_oc(args, timeout=30)
    return out if ok else f"Error:\n{out}"


@mcp.tool()
def start_build(
    build_config_name: str,
    namespace: str = "default",
    from_dir: str = "",
    cluster: str = "",
) -> str:
    """Start a new build from a BuildConfig.
    Optionally supply from_dir to use a local directory as the binary source."""
    args = ["start-build", build_config_name, "-n", namespace]
    if from_dir:
        args.append(f"--from-dir={from_dir}")
    ok, out = run_oc(args, timeout=120)
    return out if ok else f"start-build failed:\n{out}"


@mcp.tool()
def list_builds(namespace: str = "", label_selector: str = "", cluster: str = "") -> str:
    """List Builds with phase, duration, reason, and age."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_BUILD, namespace=namespace, label_selector=label_selector)
        rows = []
        for build in items:
            meta = build.get("metadata", {})
            status = build.get("status", {})
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                status.get("phase", "?"),
                _build_duration(status),
                status.get("reason", ""),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "PHASE", "DURATION", "REASON", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_build(name: str, namespace: str = "default", cluster: str = "") -> str:
    """Get detailed Build information: phase, reason, output image, and timing."""
    c = get_client(cluster)
    try:
        build = c.get_custom(*_BUILD, name, namespace)
        meta = build.get("metadata", {})
        spec = build.get("spec", {})
        status = build.get("status", {})
        strategy_type = spec.get("strategy", {}).get("type", "?")
        output_to = spec.get("output", {}).get("to", {}).get("name", "")
        bc_label = meta.get("labels", {}).get("openshift.io/build-config.name", "")
        lines = [
            f"Build: {namespace}/{name}",
            f"  Phase:       {status.get('phase', '?')}",
            f"  Reason:      {status.get('reason', '')}",
            f"  Message:     {status.get('message', '')}",
            f"  Strategy:    {strategy_type}",
            f"  OutputTo:    {output_to}",
            f"  BuildConfig: {bc_label}",
            f"  StartTime:   {status.get('startTimestamp', status.get('startTime', ''))}",
            f"  Completed:   {status.get('completionTimestamp', '')}",
            f"  Duration:    {_build_duration(status)}",
            f"  Age:         {age_string(meta.get('creationTimestamp'))}",
        ]
        if status.get("outputDockerImageReference"):
            lines.append(f"  Image:       {status.get('outputDockerImageReference')}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_build_logs(
    name: str,
    namespace: str = "default",
    follow: bool = False,
    cluster: str = "",
) -> str:
    """Retrieve logs for a Build. Set follow=True to stream (returns available output)."""
    args = ["logs", f"build/{name}", "-n", namespace]
    if follow:
        args.append("-f")
    ok, out = run_oc(args, timeout=300)
    return out if ok else f"Error getting build logs:\n{out}"


@mcp.tool()
def list_image_streams(namespace: str = "", cluster: str = "") -> str:
    """List ImageStreams with their internal Docker repository and tag count."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_IS, namespace=namespace)
        rows = []
        for istream in items:
            meta = istream.get("metadata", {})
            status = istream.get("status", {})
            tags = status.get("tags") or []
            docker_repo = status.get("dockerImageRepository", "")
            rows.append([
                meta.get("namespace", ""),
                meta.get("name", ""),
                docker_repo[:60],
                str(len(tags)),
                age_string(meta.get("creationTimestamp")),
            ])
        return format_table(["NAMESPACE", "NAME", "DOCKER-REPO", "TAGS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_image_stream_tags(
    image_stream: str,
    namespace: str = "default",
    cluster: str = "",
) -> str:
    """List tags for an ImageStream with image digest and creation timestamp."""
    c = get_client(cluster)
    try:
        istream = c.get_custom(*_IS, image_stream, namespace)
        tags = istream.get("status", {}).get("tags") or []
        if not tags:
            return f"ImageStream '{namespace}/{image_stream}' has no tags."
        rows = []
        for tag in tags:
            tag_name = tag.get("tag", "?")
            history = tag.get("items") or []
            if history:
                latest = history[0]
                image_id = latest.get("image", "")[:32]
                created = latest.get("created", "")
                rows.append([tag_name, image_id, created, str(len(history))])
            else:
                rows.append([tag_name, "(no image)", "", "0"])
        return (f"ImageStream: {namespace}/{image_stream}\n"
                + format_table(["TAG", "IMAGE-ID", "CREATED", "HISTORY"], rows))
    except Exception as e:
        return format_error(e)
