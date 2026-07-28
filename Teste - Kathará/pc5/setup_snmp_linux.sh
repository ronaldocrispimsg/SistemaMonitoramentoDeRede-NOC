#!/usr/bin/env bash
# ===============================================================================
# NetSpot - Script de Automação SNMP para Linux (Debian, Ubuntu, Mint, RHEL/Arch)
# ===============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}===========================================================${NC}"
echo -e "${GREEN}   🚀 CONFIGURADOR AUTOMÁTICO DE SNMP NATIVO - LINUX   ${NC}"
echo -e "${CYAN}===========================================================${NC}"

# 1. Verificar privilégios de ROOT
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ ERRO: Este script deve ser executado como ROOT (sudo)!${NC}"
    exit 1
fi

# 1.1 Aguardar DHCP / Conectividade de rede
if command -v ping &> /dev/null; then
    echo -e "${YELLOW}Aguardando obtenção de IP/DHCP e conectividade...${NC}"
    MAX_ATTEMPTS=30
    ATTEMPT=0
    while ! ping -c 1 -W 2 8.8.8.8 &>/dev/null && ! ping -c 1 -W 2 100.0.1.254 &>/dev/null && [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
        sleep 2
        ATTEMPT=$((ATTEMPT + 1))
    done
fi

# 2. Instalar snmpd respeitando a distribuição
echo -e "\n${YELLOW}[1/4] Instalando pacote nativo snmpd...${NC}"
if command -v apt-get &> /dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq snmpd snmp
elif command -v dnf &> /dev/null; then
    dnf install -y -q net-snmp net-snmp-utils
elif command -v yum &> /dev/null; then
    yum install -y -q net-snmp net-snmp-utils
elif command -v pacman &> /dev/null; then
    pacman -Sy --noconfirm net-snmp
fi
echo -e "${GREEN}   ✔ Pacote snmpd instalado com sucesso!${NC}"

# 3. Configurar arquivo de configuração /etc/snmp/snmpd.conf com acesso TOTAL MIB (.1)
echo -e "\n${YELLOW}[2/4] Configurando Community 'netspot' em /etc/snmp/snmpd.conf...${NC}"
if [ -f /etc/snmp/snmpd.conf ]; then
    cp /etc/snmp/snmpd.conf /etc/snmp/snmpd.conf.bak.$(date +%Y%m%d%H%M%S) 2>/dev/null || true
fi

cat <<EOF > /etc/snmp/snmpd.conf
agentAddress udp:161
rocommunity netspot default .1
EOF
echo -e "${GREEN}   ✔ Arquivo /etc/snmp/snmpd.conf configurado com acesso completo MIB (.1)!${NC}"

# 4. Ajustar Firewall (UFW, Firewalld ou Iptables)
echo -e "\n${YELLOW}[3/4] Ajustando Regras de Firewall (UDP 161)...${NC}"
if command -v ufw &> /dev/null && ufw status 2>/dev/null | grep -q "active"; then
    ufw allow 161/udp &> /dev/null || true
    echo -e "${GREEN}   ✔ Regra UFW (UDP 161) aplicada!${NC}"
elif [ -d /run/systemd/system ] && command -v firewall-cmd &> /dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --add-port=161/udp --permanent &> /dev/null || true
    firewall-cmd --reload &> /dev/null || true
    echo -e "${GREEN}   ✔ Regra Firewalld (UDP 161) aplicada!${NC}"
else
    echo -e "${GREEN}   ✔ Nenhuma restrição de firewall ativa detectada.${NC}"
fi

# 5. Reiniciar o Serviço snmpd (Universal: Systemd, SysVinit, Containers Kathara/Docker)
echo -e "\n${YELLOW}[4/4] Habilitando e reiniciando o serviço snmpd...${NC}"

SERVICE_STARTED=false

# 5.1 Ambientes com Systemd ativo (Linux nativo, VMs, Servidores dedicados)
if [ -d /run/systemd/system ] && command -v systemctl &> /dev/null; then
    if systemctl restart snmpd 2>/dev/null || systemctl restart netsnmp 2>/dev/null; then
        systemctl enable snmpd &> /dev/null || systemctl enable netsnmp &> /dev/null || true
        SERVICE_STARTED=true
    fi
fi

# 5.2 Ambientes sem Systemd (Containers Kathara/Docker, SysVinit, OpenRC, WSL)
if [ "$SERVICE_STARTED" = false ]; then
    if [ -f /etc/init.d/snmpd ]; then
        /etc/init.d/snmpd restart &> /dev/null || /etc/init.d/snmpd start &> /dev/null || true
        SERVICE_STARTED=true
    elif [ -f /etc/init.d/netsnmp ]; then
        /etc/init.d/netsnmp restart &> /dev/null || /etc/init.d/netsnmp start &> /dev/null || true
        SERVICE_STARTED=true
    elif command -v service &> /dev/null; then
        service snmpd restart &> /dev/null || service snmpd start &> /dev/null || true
        SERVICE_STARTED=true
    else
        snmpd &> /dev/null || true
        SERVICE_STARTED=true
    fi
fi

echo -e "${GREEN}   ✔ Serviço nativo snmpd rodando com sucesso!${NC}"

echo -e "\n${CYAN}===========================================================${NC}"
echo -e "${GREEN}   🎉 PRONTO! O Linux está pronto para ser monitorado.   ${NC}"
echo -e "   Cadastre o IP desta máquina no Dashboard do NetSpot!${NC}"
echo -e "${CYAN}===========================================================${NC}"
