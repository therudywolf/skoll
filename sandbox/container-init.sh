#!/bin/bash
# container-init.sh — Skoll sandbox PID 1 (under tini).
#
# Responsibilities, in order:
#   1. Apply the egress allowlist (iptables) WHILE we still hold CAP_NET_ADMIN.
#   2. Drop from root to the unprivileged `skoll` user (UID 1001).
#   3. Either exec the override command (CMD / `docker run ... <cmd>`), or block
#      forever so the backend can drive the container via `docker exec`.
#
# Why root at start?  Applying iptables requires CAP_NET_ADMIN, which Docker only
# grants to the *initial* process. We use it for exactly one thing — installing
# the firewall — then immediately drop to UID 1001 via gosu. Agent workloads
# (run_bash, Issue 2.4) therefore never run as root and never hold NET_ADMIN.
#
# This script is intentionally defensive: on hardened hosts the backend may also
# add `--cap-drop=NET_ADMIN`, in which case we *cannot* install the firewall. We
# refuse to continue unless SKOLL_SANDBOX_ALLOW_NO_FIREWALL=1 is set, so a missing
# firewall can never silently become "allow all egress".

set -euo pipefail

log() { echo "skoll-init: $*" >&2; }

UNPRIV_USER="skoll"

apply_network_policy() {
    if [ ! -x /usr/local/bin/skoll-init-network ]; then
        log "FATAL: /usr/local/bin/skoll-init-network missing or not executable"
        exit 1
    fi

    # Probe for CAP_NET_ADMIN by attempting a no-op list of the OUTPUT chain.
    if iptables -S OUTPUT >/dev/null 2>&1; then
        log "applying egress allowlist via init-network.sh"
        /usr/local/bin/skoll-init-network
    else
        if [ "${SKOLL_SANDBOX_ALLOW_NO_FIREWALL:-0}" = "1" ]; then
            log "WARNING: no CAP_NET_ADMIN and SKOLL_SANDBOX_ALLOW_NO_FIREWALL=1 — "
            log "WARNING: starting WITHOUT an egress firewall. Egress is unrestricted."
        else
            log "FATAL: cannot apply egress firewall (no CAP_NET_ADMIN)."
            log "FATAL: deny-by-default egress is mandatory. Launch the container with"
            log "FATAL: --cap-add=NET_ADMIN, or set SKOLL_SANDBOX_ALLOW_NO_FIREWALL=1"
            log "FATAL: ONLY if an outer host firewall already constrains this container."
            exit 1
        fi
    fi
}

main() {
    if [ "$(id -u)" = "0" ]; then
        apply_network_policy
        # Hand off to the unprivileged user. gosu replaces this process image
        # (no setuid, no extra PID) and forwards signals from tini.
        if [ "$#" -gt 0 ]; then
            log "dropping to ${UNPRIV_USER} and exec'ing: $*"
            exec gosu "${UNPRIV_USER}" "$@"
        fi
        log "dropping to ${UNPRIV_USER}; container idle (drive via 'docker exec')"
        exec gosu "${UNPRIV_USER}" sleep infinity
    else
        # Already unprivileged (e.g. launched with --user). We cannot install the
        # firewall in this mode; honour the same deny-by-default contract.
        if ! iptables -S OUTPUT >/dev/null 2>&1; then
            if [ "${SKOLL_SANDBOX_ALLOW_NO_FIREWALL:-0}" != "1" ]; then
                log "FATAL: started as non-root without CAP_NET_ADMIN; cannot enforce"
                log "FATAL: egress firewall. Refusing to start (set"
                log "FATAL: SKOLL_SANDBOX_ALLOW_NO_FIREWALL=1 to override)."
                exit 1
            fi
            log "WARNING: non-root start, no firewall, override set — egress unrestricted"
        else
            apply_network_policy
        fi
        if [ "$#" -gt 0 ]; then
            log "container started as $(id -un); exec'ing: $*"
            exec "$@"
        fi
        log "container started as $(id -un); idle (drive via 'docker exec')"
        exec sleep infinity
    fi
}

main "$@"
