# Skoll sandbox image
# Runs untrusted shell commands on behalf of the agent.
# MUST be launched with --runtime=runsc (gVisor) in production.
# See sandbox/README.md and sandbox/network-policy.md.

FROM python:3.12-slim-bookworm@sha256:93ab4b7fa528b25124c97bcc755415e60eb671a86b4dbe0328df2fe2d1c1193d
# Pin the digest above on first build, then keep it fixed across rebuilds.
# Bump only via a deliberate PR — see ROADMAP for sandbox base bump cadence.

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Common build / test tools the agent might invoke.
# Add packages here only via PR; each addition is a supply-chain decision.
#   - iptables / iproute2 : egress allowlist enforced by container-init.sh
#   - curl / ca-certificates : egress connectivity tests + agent fetches
#   - gosu : drop from root (needed for iptables) to the unprivileged user
#   - tini : reap zombies for run_bash subprocesses
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        coreutils \
        curl \
        git \
        gosu \
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

# Strip setuid/setgid bits from every binary in the image. The agent has no
# legitimate need to escalate, and dropped capabilities make most of these inert
# anyway — removing the bits is defence in depth. `gosu` does NOT rely on setuid.
RUN find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod -s {} + 2>/dev/null || true

# Non-root user — the agent never runs as root inside the sandbox.
# UID 1001, named `skoll`. container-init.sh drops to this user before exec'ing
# any agent workload (it briefly needs root only to apply iptables rules).
RUN useradd --create-home --shell /bin/bash --uid 1001 skoll

# Common Python tools the agent typically needs for testing.
# Installed into the skoll user's home and pinned at image build.
COPY --chown=skoll:skoll requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN runuser -u skoll -- python -m pip install --user --no-cache-dir \
        -r /tmp/requirements-sandbox.txt \
    && rm -f /tmp/requirements-sandbox.txt

# Control / init scripts.
#   container-init.sh : PID 1 helper — applies egress policy, drops to UID 1001,
#                       then keeps the container alive (or execs an override CMD).
#   init-network.sh   : the iptables allowlist itself (sourced by container-init).
#   entrypoint.py     : Phase 2 JSON stdin protocol for run_bash (Issue 2.4); not
#                       wired as ENTRYPOINT yet — kept here for the 2.4 deliverable.
COPY container-init.sh /usr/local/bin/skoll-container-init
COPY init-network.sh /usr/local/bin/skoll-init-network
COPY --chown=skoll:skoll entrypoint.py /usr/local/bin/skoll-sandbox-entry
RUN chmod 0755 /usr/local/bin/skoll-container-init /usr/local/bin/skoll-init-network

WORKDIR /workspace

# tini reaps zombies properly (matters for `run_bash` that spawns subprocesses).
# container-init applies the network policy and drops privileges; with no CMD it
# blocks forever so the backend can drive the container via `docker exec`.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/skoll-container-init"]
