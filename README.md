# OpenShift & Kubernetes MCP Server

[![OpenShift 4 MCP Server MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/ay-garg/openshift-mcp-server/badges/card.svg)](https://glama.ai/mcp/servers/ay-garg/openshift-mcp-server)

[![OpenShift 4 MCP Server MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/ay-garg/openshift-mcp-server/badges/score.svg)](https://glama.ai/mcp/servers/ay-garg/openshift-mcp-server)

A comprehensive [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes **216 tools**, **7 resources**, and **10 runbook prompts** for cluster operations — all driven by an LLM. Works with **OpenShift 4** and **vanilla Kubernetes**; OpenShift-specific tools (Routes, BuildConfigs, SCCs, OLM, Machines, RHOAI, Virtualization) return a clear error on plain Kubernetes clusters that don't have those APIs.

Connect it to Claude (Desktop, Code, or API) and ask natural-language questions like:

> *"Why is my pod crashlooping in namespace prod?"*
> *"Scale the frontend deployment to 5 replicas."*
> *"Show me all firing alerts and create a 4-hour silence for the watchdog."*
> *"Live-migrate VM database-0 to another node."*
> *"Deploy llama-3 with KServe in the ds-team namespace."*
> *"What's the status of my Tekton pipeline run in namespace ci?"*
> *"Show me all Konflux components and their latest snapshot status."*

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
  - [OCP_CLUSTERS — multi-cluster JSON](#1-ocp_clusters--multi-cluster-json-highest-priority)
  - [Service Account Token](#2-service-account-token-recommended-for-cicd)
  - [Username / Password](#3-username--password)
  - [kubeconfig](#4-kubeconfig-default-for-local-dev)
  - [In-cluster](#5-in-cluster-when-running-inside-a-pod)
  - [TLS verification](#tls-verification)
- [Multi-cluster](#multi-cluster)
- [Monitoring / Prometheus](#monitoring--prometheus)
- [Environment variables reference](#environment-variables-reference)
- [Usage with Claude](#usage-with-claude)
  - [Claude Code](#claude-code-this-repository)
  - [Claude Desktop](#claude-desktop)
  - [Streamable HTTP transport](#streamable-http-transport-for-remote-use-or-web-apps)
  - [Web UI (Gradio)](#web-ui-gradio)
- [Interactive Chat Client](#interactive-chat-client-mcp_chatpy)
- [Container Deployment](#container--openshift-deployment)
  - [1. Build the image](#1-build-the-image)
  - [2. Push the image](#2-push-the-image)
  - [3. Deploy to OpenShift](#3-deploy-to-openshift)
  - [3b. Deploy to vanilla Kubernetes](#3b-deploy-to-vanilla-kubernetes)
  - [4. Connect an MCP client](#4-connect-an-mcp-client)
  - [5. MCP Inspector](#5-mcp-inspector)
  - [6. Deploy the Gradio web UI](#6-deploy-the-gradio-web-ui)
  - [7. Environment variables reference (container)](#7-environment-variables-reference-container)
  - [8. Production checklist](#8-production-checklist)
- [MCP Resources](#mcp-resources)
- [MCP Prompts](#mcp-prompts)
- [Example prompts](#example-prompts)
- [Repository structure](#repository-structure)
- [Architecture](#architecture)
- [Adding a new tool](#adding-a-new-tool)
- [Tool highlights](#tool-highlights)
- [Dependencies](#dependencies)
- [Security considerations](#security-considerations)
- [License](#license)
- [Contributing](#contributing)

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

---

## Requirements

- Python 3.11+
- `oc` CLI in PATH (for operations that use it; many tools fall back to direct k8s API calls)
- `virtctl` in PATH (for VM pause/unpause; optional)
- Access to an OpenShift 4.x cluster

---

## Installation

```bash
git clone https://github.com/ay-garg/openshift-mcp-server.git
cd openshift-mcp-server

python3 -m venv .venv
.venv/bin/pip install -e .
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
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | `127.0.0.1` | Bind address for streamable-http transport |
| `MCP_PORT` | `8080` | Port for streamable-http transport |
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

### Streamable HTTP transport (for remote use or web apps)

> **Note:** `MCP_HOST` defaults to `127.0.0.1` (loopback-only, with DNS-rebinding protection enabled by the MCP SDK).
> Set `MCP_HOST=0.0.0.0` explicitly when you need external access.

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HOST=0.0.0.0   # bind to all interfaces for remote access
export MCP_PORT=8080
.venv/bin/ocp-mcp-server
```

Then point your MCP client at `http://your-host:8080/mcp`.

### Web UI (Gradio)

A browser-based UI with two tabs — no MCP client required.

**Install UI dependencies:**

```bash
.venv/bin/pip install -e ".[ui]"
```

**Run:**

```bash
export OCP_API_URL=https://api.mycluster.example.com:6443
export OCP_TOKEN=sha256~...
.venv/bin/ocp-mcp-ui
# Opens at http://localhost:7860
```

**Tab 1 — Tool Playground:** Select any of the 216 tools from a searchable dropdown, fill in parameters, and run it directly against your cluster. Results appear instantly — no AI in the loop.

**Tab 2 — AI Chat:** Natural-language chat backed by Claude. Set `ANTHROPIC_API_KEY` and ask anything — Claude will automatically call the right OCP tools and show you what it did.

---

## Interactive Chat Client (`mcp_chat.py`)

`mcp_chat.py` is a standalone terminal chat client that connects to any running MCP server and drives an agentic loop using the LLM of your choice. All configuration is prompted at startup — no environment variables required, though they are used as defaults when present.

### Supported LLM providers

| Provider | Auth |
|---|---|
| **Anthropic API** | API key |
| **Google Vertex AI** | GCP project ID + region (GCP ADC — `gcloud auth application-default login`) |
| **Ollama** | Base URL (local or remote) |
| **OpenAI-compatible** | Base URL + optional API key (OpenAI, LM Studio, vLLM, llama.cpp, …) |

### Install

```bash
pip install mcp anthropic "anthropic[vertex]" openai httpx
```

### Run

```bash
python mcp_chat.py
```

The script walks you through setup interactively:

```
╔══════════════════════════════════════════════════════════════╗
║                  MCP Chat — Setup                           ║
╚══════════════════════════════════════════════════════════════╝

MCP server URL [http://localhost:8080/mcp]:

LLM provider
  1. Anthropic API  (API key)
  2. Google Vertex AI  (GCP project ID + region, GCP ADC auth)
  3. Ollama  (local or remote)
  4. OpenAI-compatible  (OpenAI / LM Studio / vLLM / llama.cpp / …)
Choice:
```

### Self-signed / internal CA certificates

When an HTTPS URL is entered (for the MCP server or the model endpoint) the script asks whether the certificate is CA-signed or self-signed:

```
  The MCP server URL is using HTTPS.
  Does it use a valid CA-signed certificate? (answer 'n' for self-signed / internal CA) [Y/n]:
```

Answering **`n`** disables SSL verification for that endpoint automatically. This is the correct answer for:

- **CRC (CodeReady Containers)** — uses a self-signed router CA
- **Self-hosted OpenShift** clusters with internal PKI
- **Local Ollama or OpenAI-compatible servers** fronted by nginx with a self-signed cert

> **Note:** For the MCP server connection, SSL verification is disabled by patching `httpx.AsyncClient` for the duration of the session (the MCP SDK does not expose a `verify=` parameter directly). For Ollama/OpenAI-compatible clients, `httpx.Client(verify=False)` is passed directly. Anthropic API and Google Vertex AI always use CA-signed certificates and are never prompted.

### Environment variable defaults

All prompts use environment variables as pre-filled defaults so repeat runs need fewer keystrokes:

| Prompt | Env var |
|---|---|
| MCP server URL | `MCP_SERVER_URL` |
| Anthropic API key | `ANTHROPIC_API_KEY` |
| Model (Anthropic / Vertex) | `ANTHROPIC_MODEL` |
| GCP project ID | `ANTHROPIC_VERTEX_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT` |
| GCP region | `CLOUD_ML_REGION` or `ANTHROPIC_VERTEX_REGION` |
| Ollama base URL | `OLLAMA_HOST` |
| Ollama model | `OLLAMA_MODEL` |
| OpenAI base URL | `OPENAI_BASE_URL` |
| OpenAI API key | `OPENAI_API_KEY` |
| OpenAI model | `OPENAI_MODEL` |

### Example session (Vertex AI + CRC cluster)

```bash
# Port-forward the deployed MCP server
oc port-forward svc/ocp-mcp-server 8080:8080 -n ocp-mcp &

python mcp_chat.py
# MCP server URL [http://localhost:8080/mcp]: https://ocp-mcp-server-ocp-mcp.apps-crc.testing/mcp
#   The MCP server URL is using HTTPS.
#   Does it use a valid CA-signed certificate? [Y/n]: n
#   ⚠  SSL verification disabled for MCP server (self-signed cert).
# LLM provider → 2 (Google Vertex AI)
# GCP project ID: my-gcp-project
# Region [us-east5]:
# Model [claude-opus-4-8]:
# Ready — 216 tools available | provider: vertex | model: claude-opus-4-8

You: What nodes are in my cluster and are any under memory pressure?
  → list_nodes({})
  → get_node_conditions({"node":"crc-xxxxx-master-0"})
```

---

## Container & OpenShift Deployment

This section covers building the container image and deploying to OpenShift or any Kubernetes cluster.

### Prerequisites

- [Podman](https://podman.io/) or Docker for building/pushing the image
- Access to a container registry (Quay.io, OpenShift internal registry, etc.)
- `oc` CLI logged in to your cluster

---

### 1. Build the image

```bash
# Clone and enter the repo
git clone https://github.com/ay-garg/openshift-mcp-server.git
cd openshift-mcp-server

# Build with Podman (recommended for OpenShift)
podman build -f Containerfile -t quay.io/your-org/ocp-mcp-server:latest .

# Multi-arch build (amd64 + arm64)
podman buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Containerfile \
  -t quay.io/your-org/ocp-mcp-server:latest .
podman push quay.io/your-org/ocp-mcp-server:latest
```

**Build arguments:**

| Argument | Default | Description |
|---|---|---|
| `OC_VERSION` | `stable` | OpenShift CLI version; e.g. `4.16.3` to pin a release |
| `VIRTCTL_VERSION` | `v1.4.0` | KubeVirt virtctl version |
| `TARGETARCH` | `amd64` | CPU architecture: `amd64` or `arm64` (set automatically by BuildKit) |

```bash
# Pin specific CLI versions
podman build -f Containerfile \
  --build-arg OC_VERSION=4.16.3 \
  --build-arg VIRTCTL_VERSION=v1.4.0 \
  -t quay.io/your-org/ocp-mcp-server:4.16.3 .
```

---

### 2. Push the image

```bash
podman push quay.io/your-org/ocp-mcp-server:latest
```

For the OpenShift internal registry:

```bash
# Log in to the internal registry
oc registry login
IMAGE="$(oc registry info)/ocp-mcp/ocp-mcp-server:latest"
podman build -f Containerfile -t "$IMAGE" .
podman push "$IMAGE"
```

---

### 3. Deploy to OpenShift

#### 3a. Create the namespace

```bash
oc new-project ocp-mcp
# or:
oc apply -f deploy/namespace.yaml
```

#### 3b. Create the credentials Secret

The Secret holds cluster auth and the optional Anthropic API key. **Never commit real values.**

**In-cluster deployment** (server manages the same cluster it runs in — no credentials needed):

```bash
# Only set ANTHROPIC_API_KEY if you want the Gradio AI Chat tab
oc create secret generic ocp-mcp-server-credentials \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-xxxxxxxx \
  -n ocp-mcp

# If no Anthropic key either, create an empty secret:
oc create secret generic ocp-mcp-server-credentials -n ocp-mcp
```

**External cluster** (server is deployed elsewhere and manages a remote cluster):

```bash
# Single cluster — token auth (recommended)
oc create secret generic ocp-mcp-server-credentials \
  --from-literal=OCP_API_URL=https://api.cluster.example.com:6443 \
  --from-literal=OCP_TOKEN=sha256~xxxxxxxxxxxxxxxxxxxxxxxx \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-xxxxxxxx \
  -n ocp-mcp

# Multi-cluster
oc create secret generic ocp-mcp-server-credentials \
  --from-literal=OCP_CLUSTERS='[
    {"name":"prod",    "api_url":"https://api.prod.example.com:6443",    "token":"sha256~prod..."},
    {"name":"staging", "api_url":"https://api.staging.example.com:6443", "token":"sha256~staging..."}
  ]' \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-xxxxxxxx \
  -n ocp-mcp
```

> **Tip:** Generate a long-lived ServiceAccount token for the MCP server:
> ```bash
> oc create serviceaccount mcp-server -n default
> oc adm policy add-cluster-role-to-user cluster-admin -z mcp-server -n default
> oc create token mcp-server -n default --duration=8760h
> ```

#### 3c. Edit the image reference

Open `deploy/deployment.yaml` and replace the placeholder image:

```yaml
image: quay.io/your-org/ocp-mcp-server:latest
```

#### 3d. Apply all resources

```bash
# Using kustomize (recommended)
oc apply -k deploy/

# Or apply individually
oc apply -f deploy/serviceaccount.yaml
oc apply -f deploy/clusterrolebinding.yaml
oc apply -f deploy/configmap.yaml
oc apply -f deploy/deployment.yaml
oc apply -f deploy/service.yaml
oc apply -f deploy/route.yaml
```

#### 3e. Verify the deployment

```bash
# Check pod status
oc get pods -n ocp-mcp -l app.kubernetes.io/name=ocp-mcp-server

# Check logs
oc logs -n ocp-mcp -l app.kubernetes.io/name=ocp-mcp-server -f

# Get the public MCP URL
oc get route ocp-mcp-server -n ocp-mcp -o jsonpath='{.spec.host}'
```

The server is ready when you see a line like:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8080
```

---

### 3b. Deploy to vanilla Kubernetes

The same manifests work on any Kubernetes cluster. The differences from the OpenShift steps above:

- Use `kubectl` instead of `oc`
- Use `deploy/ingress.yaml` instead of `deploy/route.yaml` (Ingress requires an ingress controller such as nginx-ingress)
- Skip `deploy/namespace.yaml` if your cluster auto-creates namespaces; otherwise `kubectl create namespace ocp-mcp`

#### Create the namespace and credentials

```bash
kubectl create namespace ocp-mcp

# Token auth (replace with your cluster API URL and token)
kubectl create secret generic ocp-mcp-server-credentials \
  --from-literal=OCP_API_URL=https://api.k8s.example.com:6443 \
  --from-literal=OCP_TOKEN=<serviceaccount-token> \
  -n ocp-mcp
```

Generate a long-lived ServiceAccount token:

```bash
kubectl create serviceaccount mcp-server -n default
kubectl create clusterrolebinding mcp-server-admin \
  --clusterrole=cluster-admin --serviceaccount=default:mcp-server
kubectl create token mcp-server -n default --duration=8760h
```

#### Apply the manifests

```bash
# Apply all resources except the OpenShift Route
kubectl apply -f deploy/serviceaccount.yaml
kubectl apply -f deploy/clusterrolebinding.yaml
kubectl apply -f deploy/configmap.yaml
kubectl apply -f deploy/deployment.yaml
kubectl apply -f deploy/service.yaml
kubectl apply -f deploy/ingress.yaml   # Kubernetes Ingress (not Route)
```

Edit `deploy/ingress.yaml` first to set the correct hostname for your cluster.

#### Verify

```bash
kubectl get pods -n ocp-mcp -l app.kubernetes.io/name=ocp-mcp-server
kubectl logs -n ocp-mcp -l app.kubernetes.io/name=ocp-mcp-server -f
kubectl get ingress -n ocp-mcp
```

**Kubernetes compatibility note:** Core tools (workloads, networking, storage, RBAC, config, monitoring, Tekton Pipelines) work on any Kubernetes cluster. Tools for OpenShift-specific APIs (Routes, BuildConfigs, SCCs, OLM, Machines, OpenShift AI, Virtualization, Service Mesh, ACM) return a clear `"API not available"` message on clusters where those CRDs are absent — they do not crash the server.

---

### 4. Connect an MCP client

Once deployed, point your MCP client at the Route URL:

```
https://<route-host>/mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ocp": {
      "transport": "http",
      "url": "https://<route-host>/mcp"
    }
  }
}
```

**Claude Code** (`.claude/settings.json` in your project):

```json
{
  "mcpServers": {
    "ocp": {
      "type": "http",
      "url": "https://<route-host>/mcp"
    }
  }
}
```

---

### 5. MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a browser-based UI for exploring MCP tools, resources, and prompts at the protocol level.

> **Route access is not possible** with the standard inspector package. Its proxy backend binds to `127.0.0.1` (loopback) by design, and the browser-side JS connects to the proxy at `localhost:SERVER_PORT`. Via a Route, `localhost` resolves to the user's machine — not the pod — so the proxy is never reachable. `oc port-forward` is required.
>
> For remote browser-based tool exploration without port-forward, use the **Gradio web UI** instead (see section 7 below) — it has a Tool Playground tab covering all 216 tools and works via a standard Route.

**Deploy:**

```bash
oc apply -f deploy/inspector.yaml -n ocp-mcp
```

**Access via port-forward (required):**

```bash
# Forward both ports — UI (6274) and proxy backend (6277)
oc port-forward svc/mcp-inspector 6274:6274 6277:6277 -n ocp-mcp
```

Open **`http://localhost:6274`** in your browser, then connect with:

| Field | Value |
|---|---|
| Transport | Streamable HTTP |
| URL | `http://ocp-mcp-server:8080/mcp` |

Use the internal ClusterIP service name — the inspector proxy (inside the pod) makes the actual connection to the MCP server, not the browser.

**Remove when done:**

```bash
oc delete -f deploy/inspector.yaml -n ocp-mcp
```

---

### 6. Deploy the Gradio web UI

The Gradio UI runs as a separate Deployment using the same image with `OCP_MODE=ui`.

Edit `deploy/deployment.yaml`, add a second Deployment (or patch the existing one):

```yaml
# Add to the container's env section:
- name: OCP_MODE
  value: "ui"
# Change containerPort to 7860 and update the Service/Route accordingly.
```

Or run it locally:

```bash
docker compose --profile ui up
```

---

### 7. Environment variables reference (container)

All variables from [Environment variables reference](#environment-variables-reference) apply. Container-specific additions:

| Variable | Default | Purpose |
|---|---|---|
| `OCP_MODE` | `server` | `server` — MCP server; `ui` — Gradio web UI |
| `MCP_TRANSPORT` | `stdio` | Always set to `streamable-http` in Kubernetes/OpenShift |
| `MCP_HOST` | `127.0.0.1` | Set to `0.0.0.0` in containers (already in ConfigMap) |

---

### 8. Production checklist

- [ ] Image pushed to a private registry with image pull secret configured
- [ ] Credentials Secret created with real values (not the template YAML)
- [ ] `OCP_SKIP_TLS_VERIFY` and `OCP_VERIFY_SSL` set correctly for your cluster's TLS posture
- [ ] ClusterRoleBinding scoped to the minimum permissions your use case needs (see `deploy/clusterrolebinding.yaml`)
- [ ] Route has TLS edge termination with `insecureEdgeTerminationPolicy: Redirect`
- [ ] MCP Inspector NOT deployed (or behind port-forward only) in production
- [ ] `ANTHROPIC_API_KEY` rotated on the schedule required by your org's secret management policy
- [ ] Resource `requests`/`limits` tuned to observed usage (check `oc top pod`)
- [ ] NetworkPolicy applied to restrict ingress to the MCP port from known LLM clients only

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
├── Containerfile                   # multi-stage UBI9 container image build
├── entrypoint.sh                   # container entrypoint (server or Gradio UI mode)
├── mcp_chat.py                     # universal interactive chat client (multi-provider)
├── deploy/                         # OpenShift / Kubernetes manifests
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── serviceaccount.yaml
│   ├── clusterrolebinding.yaml
│   ├── configmap.yaml
│   ├── secret.yaml                 # template only — create via oc create secret
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── route.yaml
│   └── inspector.yaml              # optional MCP Inspector pod (port-forward access)
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
    │  MCP protocol (stdio or streamable-http)
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

### Tekton Pipelines (`pipelines.py`)

Works on any Kubernetes cluster with Tekton installed (including OpenShift Pipelines).

| Tool | Description |
|---|---|
| `list_pipelines` | List Pipelines in a namespace |
| `get_pipeline` | Full Pipeline spec: tasks, params, workspaces |
| `list_pipeline_runs` | List PipelineRuns with status; filter by label selector |
| `get_pipeline_run` | PipelineRun detail: task statuses, params, start/end time, duration |
| `start_pipeline_run` | Trigger a new PipelineRun with optional params and workspaces |
| `cancel_pipeline_run` | Cancel a running PipelineRun |
| `list_tasks` | List Tasks in a namespace |
| `list_task_runs` | List TaskRuns with status |
| `list_trigger_templates` | List TriggerTemplates (webhook-driven pipeline triggers) |
| `list_event_listeners` | List EventListeners and their trigger bindings |

Example prompts:

```
"List all pipeline runs in namespace ci and show me which ones failed"
"Get the full log context for pipeline run build-frontend-xyz"
"Start pipeline build-and-push in namespace ci with IMAGE=quay.io/org/app:latest"
"Cancel the running pipeline run deploy-staging-abc"
"What triggers are configured in the platform namespace?"
```

### Konflux / RHTAP (`konflux.py`)

Konflux (Red Hat Trusted Application Pipeline) tools. Requires the Konflux CRDs (`appstudio.redhat.com`) installed on your cluster.

| Tool | Description |
|---|---|
| `list_konflux_applications` | List Konflux Applications in a workspace/namespace |
| `get_konflux_application` | Application detail: components, environments, status |
| `list_components` | List Components; filter by application |
| `get_component` | Component detail: source repo, build pipeline, container image |
| `create_component` | Register a new Component from a git repository |
| `list_snapshots` | List Snapshots; filter by application |
| `get_snapshot_status` | Snapshot status including all integration test results |
| `list_integration_test_scenarios` | List IntegrationTestScenarios for an application |
| `list_release_plans` | List ReleasePlans; filter by application |
| `list_releases` | List Releases with status and target environment |
| `list_component_pipeline_runs` | List PipelineRuns for a component (build history) |

Example prompts:

```
"What Konflux applications exist in namespace team-a?"
"Show me the latest snapshot for application frontend and its integration test results"
"List all components in application backend-api and their source repos"
"What's the build history for component api-gateway?"
"Are there any failed releases in namespace platform?"
"Show me all integration test scenarios configured for application my-app"
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `mcp>=1.6.0` | Model Context Protocol SDK (FastMCP + streamable-http transport) |
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
