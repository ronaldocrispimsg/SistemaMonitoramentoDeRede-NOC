# ===============================================================================
# NetSpot - Script de Automacao SNMP para Windows (10 e 11)
# ===============================================================================

Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "   CONFIGURADOR AUTOMATICO DE SNMP NATIVO - NETSPOT   " -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Cyan

# 1. Verificar se esta rodando como Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERRO: Este script deve ser executado como ADMINISTRADOR!" -ForegroundColor Red
    Write-Host "Abra o PowerShell como Administrador e tente novamente." -ForegroundColor Yellow
    Exit
}

# 2. Instalar o recurso SNMP do Windows
Write-Host "`n[1/4] Instalando recurso nativo do Servico SNMP..." -ForegroundColor Yellow
$serviceExists = Get-Service -Name "SNMP" -ErrorAction SilentlyContinue

if ($null -eq $serviceExists) {
    Write-Host "Instalando recurso SNMP via Windows Capabilities..." -ForegroundColor Gray
    Add-WindowsCapability -Online -Name "SNMP.Client~~~~0.0.1.0" -ErrorAction SilentlyContinue | Out-Null
} else {
    Write-Host "[OK] Servico SNMP ja esta instalado no sistema." -ForegroundColor Green
}

# 3. Configurar Community 'netspot' no Registro do Windows
Write-Host "`n[2/4] Configurando Community 'netspot' no Registro..." -ForegroundColor Yellow
Reg Add "HKLM\SYSTEM\CurrentControlSet\Services\SNMP\Parameters\ValidCommunities" /v "netspot" /t REG_DWORD /d 4 /f | Out-Null

# Remover restricoes de IP no PermittedManagers para permitir chamadas do Docker/WSL/Debian
Remove-Item -Path "HKLM:\SYSTEM\CurrentControlSet\Services\SNMP\Parameters\PermittedManagers" -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
Write-Host "[OK] Community 'netspot' configurada para aceitar qualquer origem (Docker/WSL/Debian)!" -ForegroundColor Green

# 4. Configurar Regra no Firewall do Windows (Porta UDP 161 para Todos os Perfis)
Write-Host "`n[3/4] Configurando Regra no Firewall (UDP 161)..." -ForegroundColor Yellow
Remove-NetFirewallRule -Name "Allow_SNMP_WSL" -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -Name "Allow_SNMP_WSL" -DisplayName "Permitir SNMP NetSpot (UDP 161)" -Protocol UDP -LocalPort 161 -Action Allow -Profile Any -Enabled True | Out-Null
Write-Host "[OK] Regra de Firewall criada com suporte a qualquer perfil de rede (Publico/Privado)!" -ForegroundColor Green

# 5. Reiniciar o Servico SNMP
Write-Host "`n[4/4] Reiniciando o Servico SNMP do Windows..." -ForegroundColor Yellow
Restart-Service -Name "SNMP" -Force -ErrorAction SilentlyContinue
Write-Host "[OK] Servico SNMP (snmp.exe) iniciado e rodando!" -ForegroundColor Green

Write-Host "`n===========================================================" -ForegroundColor Cyan
Write-Host "   PRONTO! O Windows esta pronto para ser monitorado.   " -ForegroundColor Green
Write-Host "   Cadastre o IP desta maquina no Dashboard do NetSpot!" -ForegroundColor White
Write-Host "===========================================================" -ForegroundColor Cyan
