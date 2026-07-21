# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder
# Downloads oc + virtctl CLIs, builds the Python venv with all dependencies.
# ─────────────────────────────────────────────────────────────────────────────
FROM registry.access.redhat.com/ubi9/python-312:latest AS builder

USER 0
WORKDIR /build

# Pin CLI versions via build args; override at build time with --build-arg.
# OC_VERSION: "stable" → latest stable; or e.g. "4.16.3" for a pinned release.
ARG OC_VERSION=stable
ARG VIRTCTL_VERSION=v1.4.0
# TARGETARCH is automatically set by BuildKit: amd64 | arm64
ARG TARGETARCH=amd64

# ── Download oc CLI ──────────────────────────────────────────────────────────
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) OC_ARCH="" ;; \
      arm64) OC_ARCH="-arm64" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    curl -fsSL \
      "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OC_VERSION}/openshift-client-linux${OC_ARCH}.tar.gz" \
    | tar -xzf - oc \
    && chmod 0755 oc

# ── Download virtctl CLI (KubeVirt VM console / pause / unpause) ─────────────
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) VC_ARCH="amd64" ;; \
      arm64) VC_ARCH="arm64" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    curl -fsSL \
      "https://github.com/kubevirt/kubevirt/releases/download/${VIRTCTL_VERSION}/virtctl-${VIRTCTL_VERSION}-linux-${VC_ARCH}" \
      -o virtctl \
    && chmod 0755 virtctl

# ── Build Python venv ────────────────────────────────────────────────────────
# --copies avoids symlinks so the venv is self-contained when copied between stages.
RUN python3 -m venv --copies /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY pyproject.toml .
COPY src/ src/

# Install the package with all optional extras (gradio + anthropic for the UI tab).
# Remove "[ui]" for a smaller image when the Gradio UI is not needed.
RUN pip install --no-cache-dir ".[ui]"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# Minimal production image: venv + CLI binaries + non-root user.
# ─────────────────────────────────────────────────────────────────────────────
FROM registry.access.redhat.com/ubi9/python-312:latest

LABEL org.opencontainers.image.title="OCP MCP Server" \
      org.opencontainers.image.description="OpenShift 4 MCP Server — 216 tools for LLM-assisted cluster operations" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.documentation="https://github.com/your-org/openshift-mcp-server/blob/main/README.md" \
      org.opencontainers.image.base.name="registry.access.redhat.com/ubi9/python-312"

USER 0

# Copy the fully-installed venv and CLI binaries from the builder stage.
COPY --from=builder /opt/venv      /opt/venv
COPY --from=builder /build/oc      /usr/local/bin/oc
COPY --from=builder /build/virtctl /usr/local/bin/virtctl

# ── OpenShift-compatible non-root setup ─────────────────────────────────────
# OpenShift runs containers with arbitrary UIDs from the project's UID range.
# Pattern: no useradd needed — just own the writable paths by GID 0 (root group)
# and make them group-writable (g=u). The numeric USER 1001 below works without
# a /etc/passwd entry; OpenShift will substitute its own UID at runtime.
# /home/ocp-mcp: runtime home for oc (~/.kube) and Python caches.
# /app:          optional mount point for kubeconfig / config files.
RUN mkdir -p /home/ocp-mcp /app \
    && chown -R 1001:0 /home/ocp-mcp /app \
    && chmod -R g=u /home/ocp-mcp /app

# ── Environment ──────────────────────────────────────────────────────────────
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/ocp-mcp \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Entrypoint ───────────────────────────────────────────────────────────────
COPY --chown=0:0 entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

USER 1001
WORKDIR /app

# Port legend:
#   8080 — MCP streamable-http transport (MCP_TRANSPORT=streamable-http)
#   7860 — Gradio web UI                 (OCP_MODE=ui)
# MCP Inspector runs as a separate pod/service — see deploy/inspector.yaml.
EXPOSE 8080
EXPOSE 7860

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
