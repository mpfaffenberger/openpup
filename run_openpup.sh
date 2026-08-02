#!/bin/bash
# OpenPup launch script — manages host bridges and the OpenPup container.
# Usage: ./run_openpup.sh [start|stop|status|restart|logs]

set -euo pipefail

BRIDGE_PORT=9081
HOST_SERVICES=(openpup-sms-bridge.service openpup-mmsd.service)

start_host_services() {
    echo "Starting OpenPup host services..."
    systemctl --user start "${HOST_SERVICES[@]}"
    curl -fsS "http://127.0.0.1:$BRIDGE_PORT/health" >/dev/null
    curl -fsS "http://127.0.0.1:$BRIDGE_PORT/mms/health" >/dev/null
}

stop_host_services() {
    systemctl --user stop "${HOST_SERVICES[@]}"
    echo "OpenPup host services stopped"
}

start_container() {
    if podman ps --format '{{.Names}}' | grep -q '^openpup$'; then
        echo "openpup container already running"
        return 0
    fi
    echo "Starting openpup container..."
    podman rm -f openpup >/dev/null 2>&1 || true
    podman run -d \
        --name openpup \
        --restart=always \
        --network=host \
        --security-opt label=disable \
        -v "$HOME/.openpup-container/data:/data" \
        -v "$HOME/.openpup-container/mms-incoming:/data/mms-incoming:ro" \
        -v "$HOME/.code_puppy:/host-code-puppy:ro" \
        -v "$HOME/code/openpup/.env:/app/.env:ro" \
        -e OPENPUP_HOME=/data \
        -e TZ=America/New_York \
        localhost/openpup:latest
    sleep 3
    podman ps --format "table {{.Names}}\t{{.Status}}" --filter name=openpup
}

stop_container() {
    podman rm -f openpup >/dev/null 2>&1 || true
    echo "openpup container stopped"
}

case "${1:-start}" in
    start)
        start_host_services
        start_container
        ;;
    stop)
        stop_container
        stop_host_services
        ;;
    restart)
        stop_container
        stop_host_services
        sleep 2
        start_host_services
        start_container
        ;;
    status)
        echo "--- host services ---"
        systemctl --user is-active "${HOST_SERVICES[@]}" || true
        curl -fsS "http://127.0.0.1:$BRIDGE_PORT/health" || true
        echo ""
        curl -fsS "http://127.0.0.1:$BRIDGE_PORT/mms/health" || true
        echo ""
        echo "--- cellular connection ---"
        nmcli -t -f NAME,TYPE,DEVICE,STATE connection show --active | grep '^openpup-mms:' || true
        echo ""
        echo "--- openpup container ---"
        podman ps --format "table {{.Names}}\t{{.Status}}" --filter name=openpup 2>/dev/null || echo "Not running"
        echo ""
        echo "--- Container logs (last 10 lines) ---"
        podman logs openpup 2>&1 | tail -10
        ;;
    logs)
        podman logs -f openpup 2>&1
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        ;;
esac
