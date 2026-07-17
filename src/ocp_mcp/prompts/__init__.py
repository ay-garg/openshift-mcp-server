"""Prompt handlers — multi-step operational runbooks exposed as MCP prompts."""

from __future__ import annotations

from ocp_mcp.app import mcp


@mcp.prompt()
def troubleshoot_pod(pod_name: str, namespace: str = "default") -> str:
    """Step-by-step runbook for diagnosing a failing or misbehaving pod."""
    return f"""
Troubleshooting pod '{pod_name}' in namespace '{namespace}'.

**Step 1 — Inspect pod status and conditions**
Call get_pod(name="{pod_name}", namespace="{namespace}") to retrieve the full pod spec and status.
Look at:
- status.phase (Pending, Running, Succeeded, Failed, Unknown)
- status.conditions[] for Ready, PodScheduled, Initialized, ContainersReady
- status.containerStatuses[].state for Waiting (with reason), Running, or Terminated

**Step 2 — Read current logs**
Call get_pod_logs(pod_name="{pod_name}", namespace="{namespace}") to retrieve stdout/stderr from
all containers. Scan for application errors, stack traces, or connection refused messages.

**Step 3 — Read previous-container logs (if CrashLoopBackOff)**
If status shows CrashLoopBackOff, call get_pod_logs(pod_name="{pod_name}",
namespace="{namespace}", previous=True) to read the log output from the last crashed container.
Note the exit code reported in status.containerStatuses[].lastState.terminated.exitCode.

**Step 4 — Check namespace events**
Call list_events(namespace="{namespace}", involved_object="{pod_name}") to surface scheduler
messages, image pull failures, OOM kills, liveness/readiness probe failures, and volume mount errors.

**Step 5 — Review resource limits and requests**
In the pod spec from Step 1 examine containers[].resources.requests and containers[].resources.limits.
Compare against node capacity obtained with get_node_resource_usage.

**Step 6 — Diagnose by failure pattern**

CrashLoopBackOff
- Exit code 1 or 2: application error — check logs from Step 3 for the root cause.
- Exit code 137: SIGKILL (usually OOMKilled) — increase memory limit.
- Exit code 143: SIGTERM — application did not shut down cleanly; check shutdown hooks.
- Check liveness probe configuration; a mis-configured probe can kill a healthy container.

OOMKilled
- Confirm with: status.containerStatuses[].lastState.terminated.reason == "OOMKilled".
- Increase containers[].resources.limits.memory in the Deployment/StatefulSet spec.
- Use exec_in_pod to run 'top' or 'cat /sys/fs/cgroup/memory/memory.usage_in_bytes' if the pod
  is still running.

ImagePullBackOff / ErrImagePull
- Verify the image name and tag are correct in spec.containers[].image.
- Check whether an imagePullSecret is configured: spec.imagePullSecrets[].
- Confirm the registry is reachable and the credentials are valid.

Pending
- Scheduler cannot place the pod. Events (Step 4) will say why:
  - Insufficient CPU/memory → scale up or add nodes.
  - Taint/toleration mismatch → add tolerations or remove taints.
  - NodeAffinity/PodAffinity constraints → relax or fix selectors.
  - PVC not bound → check list_pvcs for the volume's status.

FailedScheduling
- Check node selectors: spec.nodeSelector must match existing node labels.
- Confirm PersistentVolumeClaims are bound with list_pvcs(namespace="{namespace}").
- Verify the pod is not requesting more resources than any single node can provide.
""".strip()


@mcp.prompt()
def debug_network_connectivity(
    source_pod: str,
    target_service: str,
    namespace: str = "default",
) -> str:
    """Step-by-step runbook for diagnosing network connectivity between pods/services."""
    return f"""
Debugging network connectivity from pod '{source_pod}' to service '{target_service}'
in namespace '{namespace}'.

**Step 1 — Verify the target service exists and has correct selectors**
Call get_service(name="{target_service}", namespace="{namespace}") and confirm:
- spec.selector matches the labels on the target pods.
- spec.ports[] defines the correct port and targetPort.

**Step 2 — Check service endpoints**
Call list_endpoints(name="{target_service}", namespace="{namespace}") (or get_resource
resource_type="endpoints", name="{target_service}", namespace="{namespace}").
If subsets[].addresses is empty, the selector is not matching any ready pods.
Fix the selector or check that target pods are Running and their readiness probes pass.

**Step 3 — Test DNS resolution from the source pod**
Call exec_in_pod(pod_name="{source_pod}", namespace="{namespace}",
command="nslookup {target_service}.{namespace}.svc.cluster.local") to verify that the
cluster DNS resolves the service correctly. If this fails, check the CoreDNS pods in
the openshift-dns namespace.

**Step 4 — Test TCP/HTTP reachability**
Call exec_in_pod(pod_name="{source_pod}", namespace="{namespace}",
command="curl -v http://{target_service}.{namespace}.svc.cluster.local:<port>/")
to attempt a real connection. A "connection refused" error points to the application not
listening; a timeout points to a NetworkPolicy or routing issue.

**Step 5 — Inspect NetworkPolicies**
Call list_network_policies(namespace="{namespace}") and review every policy whose
podSelector could match the source or target pod. Confirm:
- An ingress rule on the target allows traffic from the source's labels/namespace.
- No egress rule on the source blocks outbound traffic to the target.
- If no NetworkPolicy applies, all traffic within the namespace is allowed by default.

**Step 6 — Check external access via Route (if needed)**
If the target service should be reachable from outside the cluster, call
list_routes(namespace="{namespace}") and confirm a Route exists with the correct
spec.to.name pointing to '{target_service}'.
Verify the Route's host DNS and TLS settings.

**Step 7 — Confirm port alignment**
Cross-check: container's containerPort → service's targetPort → service's port → route's
targetPort. A mismatch at any layer silently drops traffic.
""".strip()


@mcp.prompt()
def investigate_node_pressure(node_name: str) -> str:
    """Step-by-step runbook for diagnosing and resolving node resource pressure."""
    return f"""
Investigating resource pressure on node '{node_name}'.

**Step 1 — Check node conditions**
Call get_node(name="{node_name}") and examine status.conditions[]:
- MemoryPressure = True: the node is low on available memory.
- DiskPressure = True: the node is low on disk space (usually /var/lib/containers).
- PIDPressure = True: too many processes are running.
- Ready = False: the kubelet is not healthy; check the kubelet service on the host.

**Step 2 — Review pod resource requests on the node**
Call get_node_resource_usage(node_name="{node_name}") to see the sum of all pod CPU and
memory requests versus the node's allocatable capacity. Identify the heaviest consumers.

**Step 3 — Surface node-related events**
Call list_events(field_selector="involvedObject.name={node_name}") to see recent evictions,
OOM kills, disk pressure events, and kubelet warnings.

**Step 4 — Investigate MemoryPressure**
If MemoryPressure is True:
- Find recently OOMKilled pods: search list_events for reason=OOMKilling.
- Use exec_in_pod or get_pod to check containers with no memory limit set.
- Consider evicting low-priority pods or increasing the node's memory.

**Step 5 — Investigate DiskPressure**
If DiskPressure is True:
- The most common cause is stale container images and logs under /var/lib/containers.
- Run exec_in_pod on a debug pod on the node, or use the node debug tool:
  run_oc_command("debug node/{node_name}") then: "chroot /host; df -h; du -sh /var/lib/containers/*"
- Remove unused images: "crictl rmi --prune" inside the debug shell.
- Ensure log rotation is configured in the MachineConfig if persistent.

**Step 6 — Cordon the node to stop scheduling new workloads**
WARNING: Confirm with the user before running this.
Call cordon_node(name="{node_name}") to mark the node as unschedulable while you
investigate, preventing new pods from being placed on the pressured node.

**Step 7 — Drain the node for maintenance (if needed)**
WARNING: This evicts all pods. Confirm with the user before running.
Call drain_node(name="{node_name}", ignore_daemonsets=True, delete_emptydir_data=True)
to safely move all workloads to other nodes before performing maintenance (kernel upgrade,
disk expansion, etc.).

**Step 8 — Uncordon after maintenance**
Call uncordon_node(name="{node_name}") when the maintenance is complete to allow new
pods to be scheduled on the node again.
""".strip()


@mcp.prompt()
def plan_cluster_upgrade(target_version: str) -> str:
    """Step-by-step runbook for safely upgrading an OpenShift cluster to a new version."""
    return f"""
Planning a cluster upgrade to OpenShift {target_version}.

**Pre-flight checks — must all pass before proceeding**

Step 1 — Verify current version and available updates
Call get_cluster_version() to check:
- status.history[0].version (current running version)
- status.availableUpdates[] (confirm {target_version} is listed)
- status.conditions where type=Upgradeable must be True

Step 2 — Verify all cluster operators are healthy
Call get_cluster_operators() and confirm every operator has:
- Available = True
- Degraded = False
- Progressing = False
Any degraded operator must be resolved before starting the upgrade.

Step 3 — Verify all nodes are Ready
Call list_nodes() and confirm every node shows Ready = True.
Nodes that are NotReady or SchedulingDisabled will block the upgrade.

Step 4 — Check etcd health
Call get_etcd_status() to confirm all etcd members are healthy and the cluster
has quorum. A degraded etcd is a hard blocker.

Step 5 — Verify no critical alerts are firing
Call list_alerts(state="firing") and confirm no critical or high-severity alerts are active.
Alerts like KubeAPIDown, EtcdMemberNotStarted, or ClusterOperatorDegraded must be cleared.

**Upgrade procedure**

Step 6 — Pause MachineConfigPools for worker and infra nodes
Call pause_machine_config_pool(name="worker") and pause_machine_config_pool(name="infra")
to prevent worker nodes from rebooting immediately when the MachineConfig is updated.
This lets you control the rollout pace.

Step 7 — Initiate the upgrade
Patch the ClusterVersion to set the desired update:
Call patch ClusterVersion (via apply_manifest or run_oc_command) to set:
  spec.desiredUpdate.version: "{target_version}"
  spec.desiredUpdate.channel: <appropriate-channel-for-{target_version}>

Step 8 — Monitor control plane upgrade progress
Repeatedly call get_cluster_version() and watch:
- status.conditions where type=Progressing changes to False when done
Call get_cluster_operators() frequently to catch any operator that becomes Degraded
during the upgrade. Control plane upgrade typically takes 30–90 minutes.

Step 9 — Unpause MachineConfigPools after control plane is done
Once get_cluster_version() shows the control plane at {target_version}:
Call unpause_machine_config_pool(name="worker") then unpause_machine_config_pool(name="infra")
Workers will begin rolling reboots. Monitor with list_nodes() until all nodes
show the new kubelet version.

Step 10 — Verify upgrade complete
Call get_cluster_version() and confirm status.history[0].state = "Completed".
Call get_cluster_operators() and confirm all operators are Available and not Degraded.
Call list_nodes() and confirm all nodes are Ready with the updated OS.
""".strip()


@mcp.prompt()
def setup_new_project(project_name: str, team: str = "") -> str:
    """Step-by-step runbook for provisioning a new OpenShift project with proper guardrails."""
    team_label = team if team else "<team-name>"
    return f"""
Setting up new project '{project_name}'{f" for team '{team}'" if team else ""}.

**Step 1 — Create the namespace/project**
Call create_namespace(name="{project_name}", labels={{"team": "{team_label}",
"environment": "production"}}) to create the OpenShift Project.
OpenShift Projects are Namespaces with additional RBAC and network isolation.

**Step 2 — Apply a ResourceQuota**
Call apply_manifest with a ResourceQuota to cap total resource consumption:
  apiVersion: v1
  kind: ResourceQuota
  metadata:
    name: {project_name}-quota
    namespace: {project_name}
  spec:
    hard:
      requests.cpu: "8"
      requests.memory: 16Gi
      limits.cpu: "16"
      limits.memory: 32Gi
      persistentvolumeclaims: "10"
      requests.storage: 100Gi
      count/pods: "50"

**Step 3 — Apply a LimitRange**
Call apply_manifest with a LimitRange to set default requests/limits for pods that
don't specify their own:
  apiVersion: v1
  kind: LimitRange
  metadata:
    name: {project_name}-limits
    namespace: {project_name}
  spec:
    limits:
    - type: Container
      default:
        cpu: 500m
        memory: 512Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      max:
        cpu: "4"
        memory: 8Gi

**Step 4 — Create a default-deny NetworkPolicy**
Call apply_manifest to apply a deny-all ingress policy, then add explicit allow rules
for the services that need to be reachable:
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: deny-all-ingress
    namespace: {project_name}
  spec:
    podSelector: {{}}
    policyTypes: [Ingress]

**Step 5 — Create role bindings for the team**
Call create_role_binding(name="{team_label}-admin-binding",
namespace="{project_name}", role_name="admin",
subjects=[{{"kind":"Group","name":"{team_label}-admins"}}]) to grant the team admin
access to the project. Adjust the ClusterRole (admin/edit/view) to match the access level.

**Step 6 — Create a ServiceAccount for workloads**
Call apply_manifest to create a dedicated ServiceAccount for application workloads
rather than using the default account:
  apiVersion: v1
  kind: ServiceAccount
  metadata:
    name: {project_name}-sa
    namespace: {project_name}

**Step 7 — Verify setup**
Call get_namespace_resource_quota(namespace="{project_name}") to confirm the quota was
applied and is tracking usage correctly.
Call list_role_bindings(namespace="{project_name}") to verify the team has the expected access.
""".strip()


@mcp.prompt()
def deploy_ml_model(
    model_name: str,
    namespace: str,
    model_format: str = "onnx",
) -> str:
    """Step-by-step runbook for deploying an ML model using OpenShift AI (RHOAI)."""
    return f"""
Deploying ML model '{model_name}' in namespace '{namespace}' using format '{model_format}'.

**Step 1 — Verify RHOAI is installed**
Call get_dsci() (DataScienceClusterInitialization) and get_data_science_cluster() to confirm
that Red Hat OpenShift AI is installed and all components show a Ready condition.
If RHOAI is not installed, contact your cluster administrator.

**Step 2 — Find a compatible serving runtime**
Call list_model_servers(namespace="{namespace}") or list_serving_runtimes(namespace="{namespace}")
to enumerate available ServingRuntime resources. Identify a runtime that supports
'{model_format}' format (e.g., OpenVINO Model Server for ONNX, Triton for TensorFlow/ONNX).

**Step 3 — Confirm the namespace is a Data Science Project**
Call list_data_science_projects() and verify '{namespace}' is listed. A Data Science Project
is a regular namespace with the label "opendatahub.io/dashboard=true".
If it is not a DS project, add the label via apply_manifest or ask the RHOAI admin.

**Step 4 — Create the InferenceService**
Call create_inference_service(name="{model_name}", namespace="{namespace}",
model_format="{model_format}", storage_uri="<s3://bucket/path-to-model>")
with the S3 URI (or PVC path) where the model artefacts are stored.
The InferenceService CR triggers the model server to load and serve the model.

**Step 5 — Monitor InferenceService readiness**
Call list_inference_services(namespace="{namespace}") repeatedly until
'{model_name}' shows URL populated and condition Ready = True.
This can take 2–10 minutes depending on model size and image pull time.

**Step 6 — Test the model endpoint**
Once ready, call exec_in_pod from a test pod to send a sample inference request:
  curl -H "Authorization: Bearer <token>" \\
       -H "Content-Type: application/json" \\
       -d '{{"inputs": [...]}}' \\
       <InferenceService URL>/v2/models/{model_name}/infer
Verify the response matches expected output.

**Step 7 — Configure autoscaling**
Call create_hpa(name="{model_name}-hpa", namespace="{namespace}",
target_name="{model_name}", min_replicas=1, max_replicas=5,
target_cpu_utilization=70) to enable Horizontal Pod Autoscaling based on CPU or
custom metrics (requests-per-second) as traffic grows.
""".strip()


@mcp.prompt()
def investigate_cluster_degradation() -> str:
    """Step-by-step runbook for investigating a degraded or unhealthy cluster."""
    return """
Investigating cluster degradation. Follow these steps in order to identify the root cause.

**Step 1 — Survey cluster operator health**
Call get_cluster_operators() and triage each operator:
- Degraded = True: the operator has a problem. Note all degraded operators.
- Available = False: the operator's managed component is not serving traffic.
- Progressing = True without a recent upgrade: the operator may be stuck.

**Step 2 — Check node health**
Call list_nodes() to identify any node that is:
- NotReady: kubelet stopped reporting; network partition, OOM kill, or OS crash.
- SchedulingDisabled (SchedulingDisabled): node was cordoned — check why.
- Missing from the list: the node may have been terminated at the IaaS layer.

**Step 3 — Verify etcd health**
Call get_etcd_status() and confirm all three (or five) etcd members are healthy.
A quorum loss in etcd causes cascading failures across the entire control plane.
If an etcd member is unhealthy, consult the etcd disaster recovery runbook immediately.

**Step 4 — List all firing alerts**
Call list_alerts(state="firing") across all namespaces to see the full picture of
what Prometheus has already detected. Pay attention to critical-severity alerts first.

**Step 5 — Scan all-namespace events for Warnings**
Call list_events(namespace="") or list_events across each relevant namespace to surface
OOMKilled, Evicted, FailedMount, NetworkNotReady, and BackOff events.

**Step 6 — Deep-dive into each degraded cluster operator**
For every operator flagged in Step 1:
- Call get_cluster_operator_details(name="<operator-name>") to read the status message
  and conditions in detail.
- Identify the operator's namespace (typically openshift-<operator-name>).
- Call list_pods(namespace="openshift-<operator-name>") to check pod health.
- Call get_pod_logs on any pod that is Pending, CrashLoopBackOff, or Error.

**Step 7 — Inspect ClusterVersion conditions**
Call get_cluster_version() and read status.conditions[]:
- Progressing = True with a long duration indicates a stalled upgrade.
- Upgradeable = False signals a pre-upgrade blocker that is now degrading something.
- RetrievedUpdates = False means the cluster cannot reach the Cincinnati update graph
  (network issue).

**Step 8 — Correlate and remediate**
Correlate findings from Steps 1–7:
- A single node loss → drain_node and replace via MachineSet.
- Etcd member loss → follow etcd recovery procedure.
- Stuck upgrade → check the CVO pod logs in openshift-cluster-version-operator.
- Operator image pull failure → check image registry and pull secrets.
Document all findings and actions taken for the post-incident review.
""".strip()


@mcp.prompt()
def migrate_vm_workload(
    vm_name: str,
    namespace: str,
    target_node: str = "",
) -> str:
    """Step-by-step runbook for live-migrating a KubeVirt VM to another node."""
    target_note = f" to node '{target_node}'" if target_node else " to another node (scheduler chooses)"
    return f"""
Live-migrating VirtualMachine '{vm_name}' in namespace '{namespace}'{target_note}.

**Step 1 — Verify the VM is running**
Call get_virtual_machine(name="{vm_name}", namespace="{namespace}") and confirm:
- status.printableStatus = "Running"
- spec.running = true
A VM must be running for live migration. If it is stopped, start it first with
start_virtual_machine(name="{vm_name}", namespace="{namespace}").

**Step 2 — Confirm the VMI exists**
Call list_virtual_machine_instances(namespace="{namespace}") and locate the VMI for
'{vm_name}'. Note the current node name — you will use this to verify the migration succeeded.

**Step 3 — Verify live migration prerequisites**

Storage: Call list_pvcs(namespace="{namespace}") and confirm all PVCs attached to the VM
use ReadWriteMany (RWX) access mode. VMs with ReadWriteOnce (RWO) storage cannot be
live-migrated unless the storage class supports it (check with your storage administrator).

Host devices: In the VM spec from Step 1, check spec.template.spec.domain.devices for any
hostDisk, GPU passthrough, or SR-IOV interfaces. These prevent live migration.
{f"Target node: Confirm node '{target_node}' exists, is Ready, and is not cordoned by calling get_node(name='{target_node}')." if target_node else ""}

**Step 4 — Initiate the live migration**
Call live_migrate_vm(name="{vm_name}", namespace="{namespace}") to create a
VirtualMachineInstanceMigration (VMIM) CR. KubeVirt will begin transferring the VM's
memory state to the target node transparently.

**Step 5 — Monitor migration progress**
Call list_virtual_machine_instances(namespace="{namespace}") repeatedly and watch the
nodeName field for '{vm_name}'. The migration is complete when the node changes
from the original node to{f" '{target_node}'" if target_node else " a new node"}.
Migration duration depends on VM memory size and dirty page rate (typically 1–10 minutes).

**Step 6 — Verify the migration succeeded**
Confirm nodeName has changed and the VMI phase is still "Running".
Check that any workloads the VM was serving are still responding by testing connectivity
(exec_in_pod from another pod, or check application health endpoints).

**Step 7 — Troubleshoot a stuck migration**
If the migration does not complete within 15 minutes:
- Call get_virtual_machine(name="{vm_name}", namespace="{namespace}") and inspect
  status.conditions for MigrationAborted or errors.
- Call get_resource(resource_type="virtualmachineinstancemigration", namespace="{namespace}")
  to inspect the VMIM CR status.message for the failure reason.
- Common causes: network bandwidth insufficient, too many dirty memory pages (high write
  workload), target node lacks resources. Consider stopping the VM and doing a cold migration.
""".strip()


@mcp.prompt()
def debug_operator_install(operator_name: str, namespace: str = "") -> str:
    """Step-by-step runbook for diagnosing a stuck or failed operator installation."""
    ns_hint = namespace if namespace else "<operator-namespace>"
    return f"""
Debugging installation of operator '{operator_name}'{f" in namespace '{namespace}'" if namespace else ""}.

**Step 1 — Find the Subscription**
Call list_subscriptions(namespace="{ns_hint}") (or across all namespaces if namespace unknown)
and locate the Subscription for '{operator_name}'. Inspect:
- spec.channel: the update channel (e.g., "stable", "fast").
- spec.installPlanApproval: "Automatic" or "Manual".
- status.currentCSV: the ClusterServiceVersion (CSV) the subscription is targeting.
- status.state: should be "AtLatestKnown"; "UpgradePending" or blank indicates a problem.

**Step 2 — Check the InstallPlan**
Call list_install_plans(namespace="{ns_hint}") and find the InstallPlan linked to the
Subscription. Check:
- spec.approved: if False and installPlanApproval=Manual, the plan awaits approval.
- status.phase: should be "Complete"; "Installing" or "Failed" requires further investigation.
- status.conditions for any failure message.

**Step 3 — Approve a pending InstallPlan (Manual approval)**
If spec.approved = False, call approve_install_plan(name="<install-plan-name>",
namespace="{ns_hint}") to approve it and allow the installation to proceed.

**Step 4 — Inspect the ClusterServiceVersion**
Call list_installed_operators(namespace="{ns_hint}") and find the CSV for '{operator_name}'.
Check status.phase:
- "Succeeded": operator is fully installed.
- "Installing": still in progress; wait and re-check.
- "Failed": inspect status.message and status.reason for the error.
- "Pending": waiting for a dependency (e.g., another CSV or CRD).

**Step 5 — Get detailed operator status**
Call get_operator_status(name="{operator_name}") to read the Operator CR's conditions,
which provide a higher-level view of readiness across all components.

**Step 6 — Check operator pod logs**
Call list_pods(namespace="{ns_hint}") to find pods belonging to the operator.
For any pod that is not Running, call get_pod_logs(pod_name="<pod>", namespace="{ns_hint}")
to read the controller/manager logs. Common issues:
- CrashLoopBackOff: application error in the operator manager — check logs carefully.
- ImagePullBackOff: registry credentials missing or image tag wrong.
- Pending: resource quota exhausted or PVC not bound.

**Step 7 — Verify the CatalogSource is healthy**
Call list_catalog_sources(namespace="openshift-marketplace") (or "{ns_hint}") and confirm
the CatalogSource that provides '{operator_name}' shows:
- status.connectionState.lastObservedState = "READY"
- No "TRANSIENT_FAILURE" which indicates the catalog pod cannot reach the index registry.
If unhealthy, check the catalog pod logs in the same namespace.
""".strip()


@mcp.prompt()
def configure_gitops_application(
    app_name: str,
    repo_url: str,
    namespace: str,
) -> str:
    """Step-by-step runbook for deploying an application via OpenShift GitOps (ArgoCD)."""
    return f"""
Configuring GitOps application '{app_name}' from '{repo_url}' targeting namespace '{namespace}'.

**Step 1 — Verify the GitOps operator is running**
Call list_pods(namespace="openshift-gitops") and confirm the ArgoCD server, application
controller, repo server, and redis pods are all Running. If any are not, follow the
debug_operator_install runbook for 'openshift-gitops'.

**Step 2 — Check or create an AppProject**
Call list_app_projects(namespace="openshift-gitops") to see existing ArgoCD AppProjects.
If a suitable project does not exist, create one via apply_manifest:
  apiVersion: argoproj.io/v1alpha1
  kind: AppProject
  metadata:
    name: {app_name}-project
    namespace: openshift-gitops
  spec:
    sourceRepos: ["{repo_url}"]
    destinations:
      - namespace: "{namespace}"
        server: https://kubernetes.default.svc
    clusterResourceWhitelist:
      - group: '*'
        kind: '*'

**Step 3 — Ensure the target namespace exists and ArgoCD has access**
Confirm namespace '{namespace}' exists: get_namespace(name="{namespace}").
Grant ArgoCD permission to deploy into the namespace by adding the label
"argocd.argoproj.io/managed-by: openshift-gitops" to the namespace, or by creating
a RoleBinding for the argocd-application-controller ServiceAccount.

**Step 4 — Create the Application CR**
Call apply_manifest to create the ArgoCD Application:
  apiVersion: argoproj.io/v1alpha1
  kind: Application
  metadata:
    name: {app_name}
    namespace: openshift-gitops
  spec:
    project: {app_name}-project
    source:
      repoURL: {repo_url}
      targetRevision: HEAD
      path: <path-to-manifests-in-repo>
    destination:
      server: https://kubernetes.default.svc
      namespace: {namespace}
    syncPolicy:
      automated:
        prune: true
        selfHeal: true
      syncOptions:
        - CreateNamespace=true

**Step 5 — Check sync status**
Call list_gitops_applications(namespace="openshift-gitops") and locate '{app_name}'.
Look at:
- status.sync.status: "Synced" (good), "OutOfSync" (drift or first sync pending).
- status.health.status: "Healthy", "Progressing", "Degraded", "Missing".

**Step 6 — Trigger a sync if OutOfSync**
Call sync_gitops_application(name="{app_name}", namespace="openshift-gitops") to force
ArgoCD to apply the current state from the Git repository to the cluster.
Monitor the sync operation with list_gitops_applications until status changes to Synced.

**Step 7 — Verify all resources are healthy**
Call get_gitops_application_health(name="{app_name}", namespace="openshift-gitops") to
see the health of every individual resource managed by this Application (Deployments,
Services, ConfigMaps, etc.). Any resource showing Degraded or Missing needs investigation.

**Step 8 — Expose the ArgoCD UI (optional)**
Call create_route(name="argocd-server", namespace="openshift-gitops",
service_name="argocd-server") if a Route to the ArgoCD UI does not already exist,
so the team can monitor and manage applications via the browser.
""".strip()
