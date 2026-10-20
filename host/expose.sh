#!/bin/sh
# Serves the minikube ingress to direct visitors with their real IPs:
# visitor -> Caddy (:80, all interfaces) -> port-forward (127.0.0.1:8080)
# -> ingress-nginx -> twilight. Requires k8s/ingress-nginx-patch.yaml applied.
set -eu
cd "$(dirname "$0")"
export TWILIGHT_PUBLIC_PORT="${TWILIGHT_PUBLIC_PORT:-80}"
export TWILIGHT_INGRESS_PORT="${TWILIGHT_INGRESS_PORT:-8080}"

# port-forward exits when the controller pod restarts; keep reconnecting.
(
	while :; do
		kubectl -n ingress-nginx port-forward --address 127.0.0.1 \
			svc/ingress-nginx-controller "$TWILIGHT_INGRESS_PORT:80" || true
		sleep 2
	done
) &

trap 'trap - EXIT INT TERM; kill 0' EXIT INT TERM

caddy run --adapter caddyfile --config Caddyfile
