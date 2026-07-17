"""Konflux (RHTAP) tools: Applications, Components, Snapshots, IntegrationTests, Releases."""

from __future__ import annotations

from ocp_mcp.app import mcp
from ocp_mcp.client import age_string, format_error, format_table, get_client

_APP_GV = ("appstudio.redhat.com", "v1alpha1")
_ITS_GV = ("appstudio.redhat.com", "v1beta2")
_TKN = ("tekton.dev", "v1")


@mcp.tool()
def list_konflux_applications(namespace: str, cluster: str = "") -> str:
    """List Konflux Applications in a workspace namespace."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_APP_GV, "applications", namespace=namespace)
        rows = []
        for app in items:
            status = app.get("status", {})
            conditions = status.get("conditions", [])
            ready = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Created"), "?")
            rows.append([app.get("metadata", {}).get("name", ""),
                         app.get("spec", {}).get("displayName", ""), ready,
                         age_string(app.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "DISPLAY-NAME", "CREATED", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_konflux_application(name: str, namespace: str, cluster: str = "") -> str:
    """Get Konflux Application details including conditions."""
    c = get_client(cluster)
    try:
        app = c.get_custom(*_APP_GV, "applications", name, namespace)
        spec = app.get("spec", {})
        status = app.get("status", {})
        lines = [f"Application: {namespace}/{name}",
                 f"  DisplayName:  {spec.get('displayName','')}",
                 f"  AppModelRepo: {spec.get('appModelRepository',{}).get('url','')}",
                 f"  GitOpsRepo:   {status.get('devfile','')[:80]}",
                 "\nConditions:"]
        for cond in status.get("conditions", []):
            lines.append(f"  {cond.get('type',''):30s} {cond.get('status','?'):8s} "
                         f"[{age_string(cond.get('lastTransitionTime'))}] {cond.get('message','')[:80]}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_components(namespace: str, application_name: str = "", cluster: str = "") -> str:
    """List Konflux Components with source repo, branch, and build status."""
    c = get_client(cluster)
    try:
        label = f"appstudio.openshift.io/application={application_name}" if application_name else ""
        items = c.list_custom(*_APP_GV, "components", namespace=namespace, label_selector=label)
        rows = []
        for comp in items:
            spec = comp.get("spec", {})
            status = comp.get("status", {})
            src = spec.get("source", {}).get("git", {})
            conditions = status.get("conditions", [])
            built = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Built"), "?")
            rows.append([comp.get("metadata", {}).get("name", ""),
                         spec.get("application", ""),
                         src.get("url", "")[-40:], src.get("revision", "main"),
                         built, age_string(comp.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "APPLICATION", "REPO", "BRANCH", "BUILT", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_component(name: str, namespace: str, cluster: str = "") -> str:
    """Get detailed Konflux Component info including GitOps repo and nudges."""
    c = get_client(cluster)
    try:
        comp = c.get_custom(*_APP_GV, "components", name, namespace)
        spec = comp.get("spec", {})
        status = comp.get("status", {})
        src = spec.get("source", {}).get("git", {})
        lines = [f"Component: {namespace}/{name}",
                 f"  Application:    {spec.get('application','')}",
                 f"  Source Repo:    {src.get('url','')}",
                 f"  Branch:         {src.get('revision','main')}",
                 f"  Context:        {src.get('context','/')}",
                 f"  ContainerImage: {spec.get('containerImage','')}",
                 f"  GitOps Repo:    {status.get('gitopsRepository',{}).get('url','')}",
                 f"  Nudges:         {', '.join(spec.get('build',{}).get('nudgesComponent',[]))}",
                 "\nConditions:"]
        for cond in status.get("conditions", []):
            lines.append(f"  {cond.get('type',''):30s} {cond.get('status','?')}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def create_component(name: str, namespace: str, application_name: str, source_repo_url: str, source_branch: str = "main", container_image: str = "", cluster: str = "") -> str:
    """Create a Konflux Component."""
    c = get_client(cluster)
    try:
        spec = {
            "application": application_name,
            "componentName": name,
            "source": {"git": {"url": source_repo_url, "revision": source_branch}},
        }
        if container_image:
            spec["containerImage"] = container_image
        body = {
            "apiVersion": "appstudio.redhat.com/v1alpha1", "kind": "Component",
            "metadata": {"name": name, "namespace": namespace},
            "spec": spec,
        }
        c.create_custom(*_APP_GV, "components", body, namespace)
        return f"Component '{namespace}/{name}' created for application '{application_name}'."
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_snapshots(namespace: str, application_name: str = "", cluster: str = "") -> str:
    """List Konflux Snapshots with components and integration test status."""
    c = get_client(cluster)
    try:
        label = f"appstudio.openshift.io/application={application_name}" if application_name else ""
        items = c.list_custom(*_APP_GV, "snapshots", namespace=namespace, label_selector=label)
        rows = []
        for snap in items:
            spec = snap.get("spec", {})
            status = snap.get("status", {})
            conditions = status.get("conditions", [])
            test_status = next((c2.get("status","?") for c2 in conditions
                                if c2.get("type") == "AppStudioTestSucceeded"), "Pending")
            components = spec.get("components", [])
            rows.append([snap.get("metadata", {}).get("name", ""),
                         spec.get("application", ""), str(len(components)), test_status,
                         age_string(snap.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "APPLICATION", "COMPONENTS", "TESTS", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def get_snapshot_status(name: str, namespace: str, cluster: str = "") -> str:
    """Get Snapshot with integration test results and component images."""
    c = get_client(cluster)
    try:
        snap = c.get_custom(*_APP_GV, "snapshots", name, namespace)
        spec = snap.get("spec", {})
        status = snap.get("status", {})
        lines = [f"Snapshot: {namespace}/{name}",
                 f"  Application: {spec.get('application','')}",
                 "\nComponents:"]
        for comp in spec.get("components", []):
            lines.append(f"  {comp.get('name','')}: {comp.get('containerImage','')}")
        lines.append("\nConditions:")
        for cond in status.get("conditions", []):
            lines.append(f"  {cond.get('type',''):35s} {cond.get('status','?'):8s} "
                         f"[{age_string(cond.get('lastTransitionTime'))}] {cond.get('message','')[:80]}")
        return "\n".join(lines)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_integration_test_scenarios(namespace: str, application_name: str = "", cluster: str = "") -> str:
    """List Konflux IntegrationTestScenarios."""
    c = get_client(cluster)
    try:
        label = f"appstudio.openshift.io/application={application_name}" if application_name else ""
        items = c.list_custom(*_ITS_GV, "integrationtestscenarios", namespace=namespace, label_selector=label)
        rows = []
        for its in items:
            spec = its.get("spec", {})
            resolver = spec.get("resolverRef", {})
            optional = spec.get("optional", False)
            rows.append([its.get("metadata", {}).get("name", ""),
                         spec.get("application", ""),
                         resolver.get("resolver", ""),
                         resolver.get("params", [{}])[0].get("value", "") if resolver.get("params") else "",
                         str(optional),
                         age_string(its.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "APPLICATION", "RESOLVER", "PIPELINE", "OPTIONAL", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_release_plans(namespace: str, application_name: str = "", cluster: str = "") -> str:
    """List Konflux ReleasePlans with target workspace."""
    c = get_client(cluster)
    try:
        label = f"appstudio.openshift.io/application={application_name}" if application_name else ""
        items = c.list_custom(*_APP_GV, "releaseplans", namespace=namespace, label_selector=label)
        rows = []
        for rp in items:
            spec = rp.get("spec", {})
            rows.append([rp.get("metadata", {}).get("name", ""),
                         spec.get("application", ""),
                         spec.get("target", ""),
                         str(spec.get("autoReleaseLabel", False)),
                         age_string(rp.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "APPLICATION", "TARGET", "AUTO-RELEASE", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_releases(namespace: str, application_name: str = "", cluster: str = "") -> str:
    """List Konflux Releases with snapshot, status, and target workspace."""
    c = get_client(cluster)
    try:
        items = c.list_custom(*_APP_GV, "releases", namespace=namespace)
        rows = []
        for rel in items:
            spec = rel.get("spec", {})
            status = rel.get("status", {})
            conditions = status.get("conditions", [])
            released = next((c2.get("status","?") for c2 in conditions if c2.get("type") == "Released"), "?")
            if application_name:
                # Filter by snapshot application label
                labels = rel.get("metadata", {}).get("labels", {})
                if labels.get("appstudio.openshift.io/application") != application_name:
                    continue
            rows.append([rel.get("metadata", {}).get("name", ""),
                         spec.get("snapshot", ""), spec.get("releasePlan", ""),
                         released, status.get("target", ""),
                         age_string(rel.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "SNAPSHOT", "RELEASE-PLAN", "RELEASED", "TARGET", "AGE"], rows)
    except Exception as e:
        return format_error(e)


@mcp.tool()
def list_component_pipeline_runs(namespace: str, component_name: str = "", cluster: str = "") -> str:
    """List Tekton PipelineRuns associated with Konflux components."""
    c = get_client(cluster)
    try:
        label = f"appstudio.openshift.io/component={component_name}" if component_name else ""
        items = c.list_custom(*_TKN, "pipelineruns", namespace=namespace, label_selector=label)
        rows = []
        for pr in items:
            status = pr.get("status", {})
            conditions = status.get("conditions", [])
            main = next((c2 for c2 in conditions if c2.get("type") == "Succeeded"), {})
            st = ("Succeeded" if main.get("status") == "True"
                  else "Failed" if main.get("status") == "False" else "Running")
            comp = pr.get("metadata", {}).get("labels", {}).get("appstudio.openshift.io/component", "")
            rows.append([pr.get("metadata", {}).get("name", ""),
                         comp, st,
                         age_string(pr.get("metadata", {}).get("creationTimestamp"))])
        return format_table(["NAME", "COMPONENT", "STATUS", "AGE"], rows)
    except Exception as e:
        return format_error(e)
