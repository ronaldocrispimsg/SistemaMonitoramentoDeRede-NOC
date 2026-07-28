#!/bin/bash
# ====================================================================
# Script unificado para iniciar o NetSpot e integrar à rede Kathará
# ====================================================================

set -e

echo "🚀 Iniciando containers do NetSpot via Docker Compose..."
docker compose up -d "$@"

echo ""
echo "🔗 Conectando containers à rede do Kathará e aplicando rotas estáticas..."
./scripts/setup_kathara_network.sh

echo ""
echo "🎉 NetSpot iniciado e 100% integrado ao Kathará!"
echo "📍 Acesse o Dashboard em: http://localhost:8080/dashboard.html"
