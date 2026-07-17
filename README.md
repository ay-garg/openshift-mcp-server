# OpenShift 4 MCP Server

A comprehensive [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes **216 tools**, **7 resources**, and **10 runbook prompts** for every OpenShift 4 cluster operation an SRE, developer, or operator could need — all driven by an LLM.

Connect it to Claude (Desktop, Code, or API) and ask natural-language questions like:

> *"Why is my pod crashlooping in namespace prod?"*
> *"Scale the frontend deployment to 5 replicas."*
> *"Show me all firing alerts and create a 4-hour silence for the watchdog."*
> *"Live-migrate VM database-0 to another node."*
> *"Deploy llama-3 with KServe in the ds-team namespace."*

---

## Features

| Domain | Tools | What you can do |
|---|---|---|
| **Cluster** | 17 | ClusterVersion, upgrade status, nodes, cordon/drain, namespaces, etcd health, events |
| **Workloads** | 19 | Pods (logs, exec, describe), Deployments (scale, rollout, undo), StatefulSets, DaemonSets, Jobs, CronJobs, DeploymentConfigs |
| **Networking** | 12 | Services, OpenShift Routes (TLS), Ingress, NetworkPolicies, IngressControllers |
| **Storage** | 10 | PVs, PVCs (create/delete), StorageClasses, VolumeSnapshots |
| **Config** | 8 | ConfigMaps, Secrets (keys only — values never exposed), ServiceAccounts |
| **RBAC** | 13 | OCP Users/Groups, Roles, ClusterRoles, RoleBindings, `auth can-i` checks |
| **Builds** | 8 | BuildConfigs, start/log builds, ImageStreams and tags |
| **Operators (OLM)** | 10 | CSVs, Subscriptions, CatalogSources, InstallPlans (approve), OperatorConditions |
| **Machines** | 11 | MachineSets (scale), Machines, MachineConfigs, MachineConfigPools (pause/unpause) |
| **Monitoring** | 10 | PromQL instant/range queries, Alertmanager alerts/silences (CRUD), PrometheusRules |
| **Security** | 9 | SCCs (list/create/assign), OAuth config, pod security violations |
| **Autoscaling** | 8 | HPA (create/delete), VPA recommendations, ClusterAutoscaler, MachineAutoscaler |
| **GitOps** | 7 | ArgoCD Applications (sync, health, refresh), AppProjects, registered clusters |
| **Pipelines** | 10 | Tekton Pipelines/PipelineRuns/Tasks/TaskRuns, start/cancel, EventListeners |
| **Service Mesh** | 8 | SMCP status, VirtualServices, DestinationRules, PeerAuthentications, Gateways |
| **OpenShift AI** | 13 | DSCI/DSC status, Notebooks (start/stop), KServe InferenceServices, DSP, ModelRegistry |
| **Virtualization** | 15 | VMs (start/stop/restart/pause/create/delete), live migration, DataVolumes, snapshots |
| **Konflux** | 11 | Applications, Components, Snapshots, IntegrationTestScenarios, ReleasePlans |
| **ACM** | 11 | ManagedClusters, Policies, Placements, ManifestWorks (deploy to managed clusters) |
| **Generic** | 6 | `apply_manifest`, `get_resource`, `run_oc_command`, `list_crds` |
| **MCP Resources** | 7 | Live cluster URIs: `ocp://cluster/info`, `ocp://{ns}/pods`, alerts, etc. |
| **MCP Prompts** | 10 | SRE runbooks: troubleshoot pod, upgrade cluster, debug network, deploy ML model, and more |

📖 **Blog:** [Konflux CI on OpenShift — Build, Sign, Test & Release with Enterprise Contract and SLSA Provenance](https://blackhatinside.com/2026/07/17/konflux-ci-on-openshift-build-sign-test-release-with-enterprise-contract-and-slsa-provenance/)

---

## Requirements

- Python 3.11+
- `oc` CLI in PATH (for operations that use it; many tools fall back to direct k8s API calls)
- `virtctl` in PATH (for VM pause/unpause; optional)
- Access to an OpenShift 4.x cluster

---

## Installation

```bash
git clone https://github.com/your-org/ocp-mcp-server.git
cd ocp-mcp-server

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

---

## Authentication

The server supports five auth modes, tried in priority order:

### 1. OCP_CLUSTERS — multi-cluster JSON (highest priority)

See the [Multi-cluster](#multi-cluster) section below.

### 2. Service Account Token (recommended for CI/CD)

```bash
export OCP_API_URL=https://api.mycluster.example.com:6443
export OCP_TOKEN=sha256~xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Get a long-lived token:
```bash
oc create serviceaccount mcp-server -n default
oc adm policy add-cluster-role-to-user cluster-admin -z mcp-server -n default
oc create token mcp-server -n default --duration=8760h
```

### 3. Username / Password

```bash
export OCP_API_URL=https://api.mycluster.example.com:6443
export OCP_USERNAME=kubeadmin
export OCP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

The server runs `oc login` and extracts the resulting bearer token automatically.

### 4. kubeconfig (default for local dev)

```bash
# Uses ~/.kube/config automatically, or:
export OCP_KUBECONFIG=/path/to/kubeconfig
export OCP_KUBECONFIG_CONTEXT=my-cluster-admin   # optional context name
```

### 5. In-cluster (when running inside a pod)

No env vars needed — uses the mounted ServiceAccount token automatically.

### TLS verification

```bash
# Disable TLS verification for the Kubernetes API connection (k8s client):
export OCP_SKIP_TLS_VERIFY=true   # for self-signed certs in dev/lab clusters

# Disable TLS verification for Prometheus/Alertmanager HTTP calls:
export OCP_VERIFY_SSL=false
```

These are two independent settings — `OCP_SKIP_TLS_VERIFY` controls the kubernetes Python client (API calls), `OCP_VERIFY_SSL` controls HTTP requests to Prometheus and Alertmanager.

---

## Multi-cluster

Set `OCP_CLUSTERS` to a JSON array of named cluster configs:

```bash
export OCP_CLUSTERS='[
  {"name": "prod",    "api_url": "https://api.prod.example.com:6443",    "token": "sha256~prod..."},
  {"name": "staging", "api_url": "https://api.staging.example.com:6443", "token": "sha256~staging..."},
  {"name": "lab",     "api_url": "https://api.lab.example.com:6443",     "token": "sha256~lab...", "skip_tls_verify": true}
]'
```

Each cluster config object supports:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Logical name used in the `cluster=` tool parameter |
| `api_url` | yes | API server URL (`https://api.<cluster>:6443`) |
| `token` | one of token/user+pass | Bearer token |
| `username` / `password` | one of token/user+pass | Credentials for `oc login` |
| `skip_tls_verify` | no | Set `true` to disable TLS verification for this cluster |

Then pass `cluster="prod"` to any tool:

```
list_pods(namespace="kube-system", cluster="prod")
scale_deployment(name="api", replicas=3, namespace="default", cluster="staging")
```

---

## Monitoring / Prometheus

By default the server auto-derives the Alertmanager URL from `OCP_PROMETHEUS_URL`. Override if needed:

```bash
export OCP_PROMETHEUS_URL=https://thanos-querier.openshift-monitoring.svc:9091
export OCP_ALERTMANAGER_URL=https://alertmanager-main.openshift-monitoring.svc:9093
export OCP_PROMETHEUS_TOKEN=sha256~...   # defaults to OCP_TOKEN
```

---

## Environment variables reference

| Variable | Default | Purpose |
|---|---|---|
| `OCP_API_URL` | — | API server URL for single-cluster token/password auth |
| `OCP_TOKEN` | — | Bearer token for the service account or user |
| `OCP_USERNAME` | — | Username for `oc login` |
| `OCP_PASSWORD` | — | Password for `oc login` |
| `OCP_SKIP_TLS_VERIFY` | `false` | Set `true`/`1`/`yes` to skip TLS for the k8s API client |
| `OCP_KUBECONFIG` | `~/.kube/config` | Path to a kubeconfig file |
| `OCP_KUBECONFIG_CONTEXT` | — | Named context within the kubeconfig |
| `OCP_CLUSTERS` | — | JSON array of multi-cluster configs (see above) |
| `OCP_PROMETHEUS_URL` | auto-detected | Prometheus/Thanos querier URL |
| `OCP_ALERTMANAGER_URL` | auto-derived | Alertmanager URL |
| `OCP_PROMETHEUS_TOKEN` | `OCP_TOKEN` | Token for Prometheus/Alertmanager HTTP calls |
| `OCP_VERIFY_SSL` | `true` | Set `false` to skip TLS for Prometheus/Alertmanager HTTP calls |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `sse` |
| `MCP_HOST` | `127.0.0.1` | Bind address for SSE transport |
| `MCP_PORT` | `8080` | Port for SSE transport |
| `GRADIO_HOST` | `0.0.0.0` | Bind address for the Gradio web UI |
| `GRADIO_PORT` | `7860` | Port for the Gradio web UI |
| `GRADIO_SHARE` | `false` | Set `true` for a temporary public Gradio URL |
| `ANTHROPIC_API_KEY` | — | Required for the AI Chat tab in the Gradio UI |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Model for the AI Chat tab |

---

## Usage with Claude

### Claude Code (this repository)

The `.claude/settings.json` already wires the server up. Open this directory in Claude Code and the `ocp` MCP server is available automatically.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "ocp": {
      "command": "/path/to/ocp-mcp-server/.venv/bin/python",
      "args": ["-m", "ocp_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/ocp-mcp-server/src",
        "OCP_API_URL": "https://api.mycluster.example.com:6443",
        "OCP_TOKEN": "sha256~..."
      }
    }
  }
}
```

### SSE transport (for remote use or web apps)

> **Note:** `MCP_HOST` defaults to `127.0.0.1` (loopback-only, with DNS-rebinding protection enabled by the MCP SDK).
> Set `MCP_HOST=0.0.0.0` explicitly when you need external access.

```bash
export MCP_TRANSPORT=sse
export MCP_HOST=0.0.0.0   # bind to all interfaces for remote access
export MCP_PORT=8080
python -m ocp_mcp.server
```

Then point your MCP client at `http://your-host:8080/sse`.

### Web UI (Gradio)

A browser-based UI with two tabs — no MCP client required.

**Install UI dependencies:**

```bash
pip install -e ".[ui]"
```

**Run:**

```bash
export OCP_API_URL=https://api.mycluster.example.com:6443
export OCP_TOKEN=sha256~...
ocp-mcp-ui
# Opens at http://localhost:7860
```

**Tab 1 — Tool Playground:** Select any of the 216 tools from a searchable dropdown, fill in parameters, and run it directly against your cluster. Results appear instantly — no AI in the loop.

**Tab 2 — AI Chat:** Natural-language chat backed by Claude. Set `ANTHROPIC_API_KEY` and ask anything — Claude will automatically call the right OCP tools and show you what it did.

---

## MCP Resources

Resources expose live cluster state as URI-addressable read-only content. MCP clients can subscribe to them and display them alongside tool results.

| URI | Description |
|---|---|
| `ocp://cluster/info` | Cluster version, infrastructure name, API URL, platform, topology, upgrade history, and available updates |
| `ocp://cluster/nodes` | All nodes with role, ready status, OS image, kubelet version, and age |
| `ocp://cluster/operators` | All ClusterOperators sorted degraded-first with Available/Progressing/Degraded columns |
| `ocp://cluster/alerts` | Currently firing Alertmanager alerts, severity-sorted, with summary |
| `ocp://{namespace}/pods` | Pods in a namespace: phase, ready containers, restarts, IP, node, age |
| `ocp://{namespace}/events` | Last 50 events in a namespace sorted most-recent-first |
| `ocp://{namespace}/deployments` | Deployments in a namespace: desired/ready/available/updated replicas and health conditions |

---

## MCP Prompts

Prompts are pre-built operational runbooks that the LLM can invoke to get step-by-step guidance. Each prompt returns a structured multi-step plan that chains together the right tools automatically.

| Prompt | Parameters | Purpose |
|---|---|---|
| `troubleshoot_pod` | `pod_name`, `namespace` | Diagnose a failing or crashlooping pod: inspect status, read logs, check events, diagnose by failure pattern (CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending) |
| `debug_network_connectivity` | `source_pod`, `target_service`, `namespace` | Diagnose network connectivity between pods/services: verify selectors, check endpoints, test DNS, test TCP, inspect NetworkPolicies, check Routes |
| `investigate_node_pressure` | `node_name` | Diagnose node MemoryPressure/DiskPressure/PIDPressure: check conditions, review resource usage, surface events, cordon/drain if needed |
| `plan_cluster_upgrade` | `target_version` | Safe upgrade pre-flight + procedure: verify operators, nodes, etcd, alerts; pause MCPs; initiate upgrade; monitor rollout; verify completion |
| `setup_new_project` | `project_name`, `team` | Provision a new OpenShift project with ResourceQuota, LimitRange, default-deny NetworkPolicy, RoleBindings, and a dedicated ServiceAccount |
| `deploy_ml_model` | `model_name`, `namespace`, `model_format` | Deploy an ML model via OpenShift AI/RHOAI: verify RHOAI, find serving runtime, create InferenceService, monitor readiness, test endpoint, configure HPA |
| `investigate_cluster_degradation` | — | Systematic triage for a degraded cluster: survey operators, check nodes, verify etcd, list alerts, scan events, deep-dive degraded operators |
| `migrate_vm_workload` | `vm_name`, `namespace`, `target_node` | Live-migrate a KubeVirt VM: verify running state, check RWX storage, initiate VMIM, monitor progress, verify success, troubleshoot if stuck |
| `debug_operator_install` | `operator_name`, `namespace` | Diagnose a stuck operator install: inspect Subscription, InstallPlan, CSV status, approve pending plans, check pod logs, verify CatalogSource |
| `configure_gitops_application` | `app_name`, `repo_url`, `namespace` | Deploy via ArgoCD: verify GitOps operator, create AppProject, configure namespace access, create Application CR, trigger sync, verify health |

---

## Example prompts

```
# Cluster health
"Give me a full health summary of the cluster"
"Which ClusterOperators are degraded and why?"
"Are there any nodes in NotReady state?"

# Workloads
"List all crashlooping pods across all namespaces"
"Scale the checkout deployment to 10 replicas in namespace shop"
"Get the last 200 log lines from pod api-xyz-abc in namespace backend"
"Roll back the frontend deployment to the previous version"

# Monitoring
"Show me all critical alerts currently firing"
"Query: rate(http_requests_total[5m]) for the last hour"
"Create a 2-hour silence for AlertName=Watchdog"

# RBAC / Security
"What permissions does user john.doe have in namespace dev?"
"Grant the edit role to group platform-team in namespace staging"
"List all SCCs and which service accounts use them"
"Create a non-privileged SCC for a workload that needs setuid binaries"

# OpenShift AI
"What's the status of the DataScienceCluster?"
"List all running notebooks in the ml-team namespace"
"Deploy a scikit-learn model from s3://models/lr-v1 using KServe"

# Virtualization
"List all VMs and their current status"
"Live-migrate VM postgres-main to node worker-3"
"Take a snapshot of VM database-0 before the upgrade"

# Konflux
"What's the build status of my component frontend in workspace team-a?"
"Show me the latest snapshot and its integration test results"

# ACM
"Which managed clusters are not compliant with the security policy?"
"Show me all placements and which clusters they selected"
```

---

## Repository structure

```
ocp-mcp-server/
├── pyproject.toml                  # package metadata and dependencies
├── .env.example                    # environment variable reference
├── .claude/
│   └── settings.json               # Claude Code MCP configuration
└── src/
    └── ocp_mcp/
        ├── __init__.py
        ├── app.py                  # shared FastMCP server instance + port/host config
        ├── server.py               # entry point — imports all tool modules
        ├── ui.py                   # Gradio web UI entry point (ocp-mcp-ui)
        ├── client.py               # multi-cluster k8s client management
        ├── tools/
        │   ├── cluster.py          # ClusterVersion, nodes, namespaces, etcd
        │   ├── workloads.py        # Pods, Deployments, StatefulSets, Jobs
        │   ├── networking.py       # Services, Routes, Ingress, NetworkPolicies
        │   ├── storage.py          # PVs, PVCs, StorageClasses, VolumeSnapshots
        │   ├── config.py           # ConfigMaps, Secrets, ServiceAccounts
        │   ├── rbac.py             # Users, Groups, Roles, RoleBindings
        │   ├── builds.py           # BuildConfigs, Builds, ImageStreams
        │   ├── operators.py        # OLM — CSVs, Subscriptions, InstallPlans
        │   ├── machines.py         # MachineSets, MachineConfigs, MCPs
        │   ├── monitoring.py       # Prometheus queries, Alertmanager
        │   ├── security.py         # SCCs, OAuth, pod security
        │   ├── autoscaling.py      # HPA, VPA, ClusterAutoscaler
        │   ├── gitops.py           # ArgoCD Applications, AppProjects
        │   ├── pipelines.py        # Tekton Pipelines, PipelineRuns, Tasks
        │   ├── service_mesh.py     # SMCP, VirtualServices, DestinationRules
        │   ├── ocp_ai.py           # RHOAI, Notebooks, KServe, ModelRegistry
        │   ├── virtualization.py   # KubeVirt VMs, live migration, snapshots
        │   ├── konflux.py          # Konflux Applications, Components, Releases
        │   ├── acm.py              # ACM ManagedClusters, Policies, ManifestWorks
        │   └── generic.py          # apply_manifest, run_oc_command, list_crds
        ├── resources/
        │   └── __init__.py         # MCP resource URIs (ocp://cluster/info, etc.)
        └── prompts/
            └── __init__.py         # SRE runbook prompt templates
```

---

## Architecture

```
LLM (Claude)
    │
    │  MCP protocol (stdio or SSE)
    ▼
ocp-mcp-server
    │
    ├── client.py  ──────────────────────────────────────────┐
    │   ClusterRegistry                                        │
    │   ├── ClusterClient("prod")   → kubernetes Python SDK   │
    │   ├── ClusterClient("staging")                          │
    │   └── ClusterClient("lab")                              │
    │                                                          │
    ├── tools/*.py  → @mcp.tool()                             │
    │   All 216 tools call get_client(cluster) ───────────────┘
    │   then use: k8s typed APIs (CoreV1, AppsV1, …)
    │             CustomObjectsApi for OCP/OLM/RHOAI/Virt CRDs
    │             subprocess oc CLI for operations not in k8s API
    │
    ├── resources/__init__.py → @mcp.resource("ocp://…")
    │   Live cluster state as URI-addressable content
    │
    └── prompts/__init__.py → @mcp.prompt()
        SRE runbook templates the LLM can invoke
```

### Auth flow

```
ClusterRegistry._load() — tried in order, first success wins:
  1. OCP_CLUSTERS  → JSON array → one ClusterClient per entry
  2. OCP_API_URL + OCP_TOKEN  → bearer-token ClusterClient
  3. OCP_API_URL + OCP_USERNAME + OCP_PASSWORD  → oc login → extract token
  4. OCP_KUBECONFIG / OCP_KUBECONFIG_CONTEXT → load_kube_config
  5. In-cluster ServiceAccount token
```

### Design principles

- **No mock data** — every tool makes real API calls or runs `oc`.
- **Safe defaults** — secrets never expose values, only key names. Destructive tools have `WARNING` in their docstrings so the LLM knows to confirm before executing.
- **Graceful degradation** — tools catch `ApiException` and return readable errors. Missing CRDs (e.g. KubeVirt not installed) return a helpful message instead of crashing.
- **Multi-cluster first** — every tool accepts a `cluster` parameter. The default cluster is whichever config loaded first.
- **Escape hatches** — `apply_manifest`, `run_oc_command`, and `list_custom_resources` let the LLM reach anything not covered by a typed tool.

---

## Adding a new tool

1. Find the relevant module in `src/ocp_mcp/tools/` or create a new one.
2. Add a function decorated with `@mcp.tool()`:

```python
from ocp_mcp.app import mcp
from ocp_mcp.client import format_error, get_client

@mcp.tool()
def my_new_tool(name: str, namespace: str = "default", cluster: str = "") -> str:
    """One-sentence description shown to the LLM."""
    c = get_client(cluster)
    try:
        result = c.core_v1.read_namespaced_something(name, namespace)
        return f"Result: {result.metadata.name}"
    except Exception as e:
        return format_error(e)
```

3. If you created a new file, add `import ocp_mcp.tools.your_module` to `server.py`.

**Conventions:**
- Always accept `cluster: str = ""` as the last parameter before any cluster-specific args.
- Call `get_client(cluster)` and use `c.oc_args()` when building `run_oc` invocations — never call `run_oc` without the cluster auth args, or multi-cluster calls will silently target the wrong cluster.
- Return strings only — tool output is text surfaced directly to the LLM.
- Catch all exceptions and return `format_error(e)` rather than letting them propagate.

---

## Tool highlights

### Security tools (`security.py`)

| Tool | Description |
|---|---|
| `list_sccs` | List all SCCs sorted by priority |
| `get_scc` | Full SCC detail: volumes, capabilities, users, groups |
| `create_scc` | Create a custom SCC with parameters: `privileged`, `host_network`, `host_pid`, `run_as_any`, `allow_privilege_escalation` |
| `add_scc_to_service_account` | Grant an SCC to a ServiceAccount via `oc adm policy` |
| `remove_scc_from_service_account` | Revoke an SCC from a ServiceAccount |
| `add_cluster_role_to_user` | Grant a ClusterRole to a user |
| `add_cluster_role_to_group` | Grant a ClusterRole to a group |
| `get_oauth_config` | Get OAuth configuration and identity providers |
| `list_pod_security_violations` | Surface FailedCreate events matching SCC/security keywords |

`create_scc` parameters:

| Parameter | Default | Description |
|---|---|---|
| `name` | required | SCC name |
| `privileged` | `false` | Allow containers to run as fully privileged (root with all capabilities) |
| `host_network` | `false` | Allow containers to use the host network namespace |
| `host_pid` | `false` | Allow containers to use the host PID namespace |
| `run_as_any` | `false` | Sets `RunAsAny` for `runAsUser` and `fsGroup` (required for some legacy workloads) |
| `allow_privilege_escalation` | `false` | Allow processes to gain more privileges than their parent (required for setuid binaries like `sudo`, `ping`, `newgrp`) — independent of `privileged` |
| `cluster` | `""` | Named cluster to target |

### Generic escape-hatch tools (`generic.py`)

| Tool | Description |
|---|---|
| `apply_manifest` | Apply YAML/JSON manifest via `oc apply -f -` |
| `get_resource` | Get any resource in YAML, JSON, wide, or describe format |
| `delete_resource` | Delete any resource by type and name |
| `list_custom_resources` | List any CRD by group/version/plural |
| `run_oc_command` | Escape hatch: run any `oc` command (blocked verbs: `delete`, `exec`, `replace`) |
| `list_crds` | List all CustomResourceDefinitions |

---

## Dependencies

| Package | Purpose |
|---|---|
| `mcp>=1.3.0` | Model Context Protocol SDK (FastMCP) |
| `kubernetes>=29.0.0` | Kubernetes Python client (typed APIs + dynamic client) |
| `httpx>=0.27.0` | HTTP client for Prometheus/Alertmanager API calls |
| `pyyaml>=6.0` | YAML parsing for `apply_manifest` and ManifestWork creation |
| `python-dateutil>=2.9.0` | Timestamp parsing for `age_string()` |
| `tabulate>=0.9.0` | Alternative table formatting |
| `gradio` | Browser-based web UI (optional — `pip install ocp-mcp-server[ui]`) |
| `anthropic` | Claude AI for the Chat tab (optional — included in `[ui]`) |

---

## Security considerations

- **Secrets** — `get_secret_keys` lists key names only. `list_secrets` shows type and count. Values are never returned.
- **Destructive ops** — `delete_namespace`, `drain_node`, `delete_virtual_machine`, etc. include `DESTRUCTIVE` warnings in their docstrings so the LLM knows to confirm before executing.
- **`run_oc_command`** — uses `shlex.split` (no shell=True) so shell metacharacters (`|`, `>`, `;`) are inert literal arguments. Blocked verbs: `delete`, `rm`, `exec`, `replace` — these have typed tools with confirmation prompts.
- **`apply_manifest`** — applies arbitrary YAML; the LLM should show the manifest to the user before calling this in agentic contexts. The `-n namespace` flag does not restrict cluster-scoped resources.
- **Bearer token redaction** — `run_oc` redacts `--token <value>` to `--token <redacted>` in all error messages, preventing credential exposure in LLM context or logs.
- **Multi-cluster routing** — all `oc` CLI calls prepend `c.oc_args()` (injects `--server` and `--token`) so the correct cluster is always targeted when multiple clusters are configured.
- **RBAC** — create a minimal ServiceAccount with only the permissions your use case needs. The tools work with whatever RBAC the token has.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

## Contributing

Issues and PRs welcome. The tool modules are intentionally kept flat and simple — one domain per file, one `@mcp.tool()` per operation, no shared state between tools.
