# NetSpot - Scripts de Automação de Agentes SNMP

Este diretório contém os scripts de automação de infraestrutura SNMP nativa para Windows e Linux.

---

## 1. Windows (10 e 11)

* **Script**: `setup_snmp_windows.ps1`
* **Descrição**: Instala o recurso nativo do Serviço SNMP do Windows (`snmp.exe`), adiciona a community `netspot` (Read-Only), remove a restrição de IP no Registro (`PermittedManagers`), cria a regra no Firewall para a porta UDP 161 (Perfil `Any`) e reinicia o serviço.
* **Como Executar** (no PowerShell como Administrador):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\snmp\setup_snmp_windows.ps1
```

---

## 2. Linux (Debian, Ubuntu, Mint, RHEL/Fedora, Arch)

* **Script**: `setup_snmp_linux.sh`
* **Descrição**: Instala o serviço nativo `snmpd`, gera a configuração em `/etc/snmp/snmpd.conf` com a community `netspot` e permissão total de MIB (`.1`), ajusta as regras de firewall (UFW ou Firewalld) e reinicia o daemon.
* **Como Executar** (no Terminal como Root / Sudo):

```bash
chmod +x ./scripts/snmp/setup_snmp_linux.sh
sudo ./scripts/snmp/setup_snmp_linux.sh
```
