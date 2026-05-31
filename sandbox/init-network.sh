#!/bin/bash
# init-network.sh — egress allowlist for the Skoll sandbox.
#
# Installs an iptables firewall whose DEFAULT is DROP. Only the hosts/ports in
# SKOLL_SANDBOX_NETWORK_ALLOWLIST (plus loopback, established replies, and DNS)
# may be reached. Everything else is silently dropped.
#
# Requires CAP_NET_ADMIN. Invoked by container-init.sh while still root, BEFORE
# privileges are dropped to UID 1001. After this runs the agent has no way to
# alter the rules (it is unprivileged and lacks NET_ADMIN).
#
#   In dev with `runc`  : these rules run inside the container's net namespace.
#   In prod with `runsc`: gVisor enforces the same netstack rules in user space;
#                         optionally pair with an outer host firewall.
#
# Allowlist format (comma-separated host:port):
#   host.docker.internal:1234,r.jina.ai:443,searxng:8080
# `host.docker.internal` resolves to the host (LM Studio) via --add-host.

set -euo pipefail

log() { echo "sandbox-net: $*" >&2; }

ALLOWLIST="${SKOLL_SANDBOX_NETWORK_ALLOWLIST:-}"

# --- Base policy: deny by default --------------------------------------------
# OUTPUT: drop everything unless explicitly allowed below.
# INPUT : drop unsolicited inbound (only established replies get back in).
# FORWARD: this container is an endpoint, never a router — drop.
iptables -F OUTPUT
iptables -F INPUT
iptables -P OUTPUT DROP
iptables -P INPUT DROP
iptables -P FORWARD DROP

# Loopback is always fine (intra-container IPC, health checks).
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT

# Returning packets for connections we initiated.
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# DNS — needed to resolve allowlist hosts. We allow the *query* (UDP/TCP 53) but
# the egress firewall still blocks traffic to any resolved address that is not on
# the allowlist, so name resolution never silently widens egress.
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# --- Allowlist ---------------------------------------------------------------
if [ -z "${ALLOWLIST}" ]; then
    log "allowlist is EMPTY — only loopback + DNS + established replies permitted"
fi

allowed_count=0
IFS=',' read -ra ENTRIES <<< "${ALLOWLIST}"
for entry in "${ENTRIES[@]}"; do
    entry="$(echo "${entry}" | tr -d '[:space:]')"
    [ -z "${entry}" ] && continue

    host="${entry%%:*}"
    port="${entry##*:}"
    if [ -z "${host}" ] || [ -z "${port}" ] || [ "${host}" = "${port}" ]; then
        log "skipping malformed allowlist entry: '${entry}' (want host:port)"
        continue
    fi
    case "${port}" in
        ''|*[!0-9]*)
            log "skipping entry with non-numeric port: '${entry}'"
            continue
            ;;
    esac

    # Resolve host -> IP(s) at init time and pin a rule per address.
    resolved=0
    for ip in $(getent ahosts "${host}" 2>/dev/null | awk '{print $1}' | sort -u); do
        iptables -A OUTPUT -p tcp -d "${ip}" --dport "${port}" -j ACCEPT
        log "ALLOW tcp -> ${host} (${ip}):${port}"
        resolved=1
        allowed_count=$((allowed_count + 1))
    done
    if [ "${resolved}" -eq 0 ]; then
        log "WARNING: could not resolve '${host}' — no rule added for ${entry}"
    fi
done

log "egress policy applied: ${allowed_count} allow rule(s); default DENY for all other egress"
