#!/bin/bash
# init-network.sh — applied as container CAP_NET_ADMIN init (run by Docker, not by user wolf).
# Drops all outbound traffic except the configured allowlist.
#
# In dev with `runc`, this script runs as part of the entrypoint.
# In prod with `runsc` (gVisor), prefer Docker network policy + an outer iptables
# applied by the host before the agent is given access.
#
# Allowlist comes from SKOLL_SANDBOX_NETWORK_ALLOWLIST env var:
#   host:port,host:port,...
# Special host `host.docker.internal` resolves to the host (LM Studio).

set -euo pipefail

# Flush
iptables -F OUTPUT
iptables -P OUTPUT DROP
# Always allow loopback and established connections (returning replies)
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# DNS to whatever resolver Docker provides (needed to resolve allowlist hosts)
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Apply allowlist
IFS=',' read -ra ENTRIES <<< "${SKOLL_SANDBOX_NETWORK_ALLOWLIST:-}"
for entry in "${ENTRIES[@]}"; do
    host="${entry%%:*}"
    port="${entry##*:}"
    if [ -z "$host" ] || [ -z "$port" ]; then
        continue
    fi
    # Resolve host to one or more IPs
    for ip in $(getent ahosts "$host" | awk '{print $1}' | sort -u); do
        iptables -A OUTPUT -p tcp -d "$ip" --dport "$port" -j ACCEPT
        echo "sandbox: allow tcp to $host ($ip):$port"
    done
done

echo "sandbox: network policy applied; default DENY for unmatched egress"
