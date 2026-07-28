#!/bin/bash
# ====================================================================
# NetSpot <-> Kathará Network Automation Script
# Connects NetSpot containers to Docker's default bridge network
# and configures static routes to Kathará lab subnets (10.0.0.0/16 & 100.0.0.0/16).
# ====================================================================

set -e

ROUTER_IP="${KATHARA_ROUTER_IP:-172.17.0.2}"

echo "🚀 [1/3] Conectando containers do NetSpot à rede bridge..."
docker network connect bridge netspot-backend 2>/dev/null || echo "   ℹ️ netspot-backend já está conectado à rede bridge."
docker network connect bridge netspot-n8n 2>/dev/null || echo "   ℹ️ netspot-n8n já está conectado à rede bridge."

echo "🛣️ [2/3] Aplicando rotas estáticas no container netspot-backend..."
docker exec --privileged netspot-backend ip route replace 10.0.0.0/16 via "$ROUTER_IP" 2>/dev/null || true
docker exec --privileged netspot-backend ip route replace 100.0.0.0/16 via "$ROUTER_IP" 2>/dev/null || true

echo "🛣️ [3/3] Aplicando rotas estáticas no container netspot-n8n..."
docker exec -u 0 netspot-n8n /bin/sh -c "command -v ip || (apt-get update -qq && apt-get install -y -qq iproute2)" 2>/dev/null || true
docker exec --privileged netspot-n8n ip route replace 10.0.0.0/16 via "$ROUTER_IP" 2>/dev/null || true
docker exec --privileged netspot-n8n ip route replace 100.0.0.0/16 via "$ROUTER_IP" 2>/dev/null || true

echo "🎉 ✅ Integração de Rede NetSpot <-> Kathará configurada com sucesso!"
