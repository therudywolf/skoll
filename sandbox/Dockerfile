# Skoll sandbox image
# Runs untrusted shell commands on behalf of the agent.
# MUST be launched with --runtime=runsc (gVisor) in production.
# See sandbox/README.md and sandbox/network-policy.md.

FROM python:3.12-slim-bookworm@sha256:af4e85f1cac90dd3771e47292ea7c8a9830abfabbe4faa5c53f158854c2e819d
# Pin the digest above on first build, then keep it fixed across rebuilds.
# Bump only via a deliberate PR — see ROADMAP for sandbox base bump cadence.

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Common build / test tools the agent might invoke.
# Add packages here only via PR; each addition is a supply-chain decision.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        curl \
        git \
        iptables \
        iproute2 \
        less \
        make \
        nano \
        nodejs \
        npm \
        procps \
        ripgrep \
        tar \
        tini \
        tree \
        unzip \
        vim-tiny \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — the agent never runs as root inside the sandbox.
RUN useradd --create-home --shell /bin/bash --uid 1001 skoll
USER skoll
WORKDIR /workspace

# Common Python tools the agent typically needs for testing.
# These run AS THE USER and are pinned at image build.
COPY --chown=skoll:skoll requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --user --no-cache-dir -r /tmp/requirements-sandbox.txt

# Control entrypoint — accepts JSON commands over stdin from the backend.
COPY --chown=skoll:skoll entrypoint.py /usr/local/bin/skoll-sandbox-entry
COPY --chown=skoll:skoll init-network.sh /usr/local/bin/skoll-init-network

# tini reaps zombies properly (matters for `run_bash` that spawns subprocesses).
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/skoll-sandbox-entry"]
