# NetSpot - Sistema Inteligente de Monitoramento de Rede (NOC Lite)

![NetSpot Architecture](https://img.shields.io/badge/Architecture-Clean%20Architecture-blue)
![Python](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python%203.11-green)
![Docker](https://img.shields.io/badge/Container-Docker%20%26%20Docker%20Compose-blueviolet)
![License](https://img.shields.io/badge/License-MIT-orange)

**NetSpot** é um sistema completo e moderno de **Network Operations Center (NOC Lite)** desenvolvido para monitoramento em tempo real de infraestruturas de TI, servidores, ativos de rede e conectividade.

O sistema combina monitoramento passivo e ativo (**ICMP Ping, Portas TCP, HTTP/HTTPS, DNS e SNMP Multivendor**), cálculo estatístico de métricas de saúde, SLA e latência, além de gestão automatizada de alertas via **RabbitMQ, N8N e Telegram**.

---

## 🏛️ Arquitetura do Sistema

O projeto foi construído seguindo os princípios de **Clean Architecture**, **SOLID**, **DRY**, **KISS** e **Isolamento de Serviços por Containers**.

```text
                                +-------------------+
                                |   Navegador Web   |
                                | (Dashboard HTML5) |
                                +---------+---------+
                                          | :8080
                                          v
+------------------+             +-------------------+             +------------------+
|   Base de Dados  |  SQLAlchemy  |  Backend FastAPI  |   PySNMP    | Agentes Nativos  |
|  PostgreSQL 15   |<----------->|   (Python 3.11)   |<----------->| (Windows / Linux)|
+------------------+  AsyncPG    +---------+---------+  UDP :161   +------------------+
                                          | AMQP
                                          v
                                 +-------------------+
                                 |     RabbitMQ      |
                                 +---------+---------+
                                           | HTTP Webhook
                                           v
                                 +-------------------+             +------------------+
                                 |  N8N Automation   |------------>| Alertas Telegram |
                                 +-------------------+             +------------------+
```

---

## ✨ Funcionalidades Principais

* **🖥️ Monitoramento Multi-Protocolo**:
  * **ICMP Ping**: Latência em ms e taxa de perda de pacotes.
  * **TCP**: Checagem de portas abertas/fechadas.
  * **HTTP / HTTPS**: Verificação de código de status HTTP e tempo de resposta.
  * **DNS**: Validação de resolução de nomes de domínio.
* **📊 Agente SNMP Nativo Multivendor**:
  * Leitura em tempo real de **Uso de CPU (%)**, **Memória RAM (%)**, **Uso de Disco (`C:\` e `/`)** e **Tráfego de Rede (Bps / Download e Upload)**.
  * Mapeamento dinâmico automático para MIBs **Linux (UCD-SNMP)** e **Windows (HOST-RESOURCES-MIB)**, além de roteadores Cisco e Mikrotik.
* **🧹 Política de Retenção de Dados Configurável**:
  * Limpeza automática de histórico de checagens, métricas SNMP, alertas e incidentes com base no campo `NETSPOT_RETENTION_DAYS` do arquivo `.env` (ex: `30` para 30 dias de histórico). Definir `NETSPOT_RETENTION_DAYS=0` **desativa** a limpeza automática mantendo o histórico indefinidamente.
* **🧠 Inteligência e Métricas NOC**:
  * Cálculo dinâmico do **Score de Saúde (0 a 100%)**.
  * Medição de **Disponibilidade SLA (%)** e cálculo de **Jitter (Variação de Latência em ms)**.
  * Identificação automática de tendências (**Estável, Degradação, Recuperação**).
* **🔔 Gestão de Alertas e Incidentes**:
  * Abertura e fechamento automatizado de incidentes no banco de dados.
  * Notificações instantâneas via webhook integrado ao **N8N** com despacho para grupos do Telegram.

---

## 📁 Estrutura de Diretórios

```text
NetSpot/
├── Backend/                    # Container FastAPI (Python 3.11)
│   ├── core/                   # Banco de Dados, Segurança e Auth JWT
│   ├── models/                 # Modelos ORM SQLAlchemy
│   ├── schemas/                # Schemas Pydantic / DTOs
│   ├── services/               # Regras de Negócio, Métricas, Checadores e Notificações
│   ├── snmp/                   # Módulo SNMP Multivendor (Discovery, Cache, Resolvers)
│   ├── routes/                 # Endpoints RESTful da API
│   ├── tests/                  # Suíte de Testes Automatizados (Pytest)
│   │   ├── conftest.py         # Fixtures de teste e cliente HTTP
│   │   ├── test_checker.py     # Testes de Ping, TCP, HTTP e DNS
│   │   ├── test_metrics.py     # Testes de Saúde, SLA, Jitter e Tendências
│   │   ├── test_retention.py   # Testes da Política de Retenção de Dados
│   │   ├── test_snmp.py        # Testes do Módulo SNMP e Conversores
│   │   ├── test_api_routes.py  # Testes de Integração das Rotas RESTful
│   │   └── test_models_schemas.py # Testes de Modelos e DTOs
│   ├── main.py                 # Ponto de Entrada da Aplicação
│   ├── scheduler.py            # Orquestrador de Polling e Coleta Assíncrona
│   └── snmp_engine.py          # Motor de Coleta SNMP de Alta Performance
├── Frontend/                   # Container Nginx SPA
│   ├── css/                    # Estilos CSS (Design System Moderno)
│   ├── js/                     # Lógica JavaScript (Dashboard e Incidentes)
│   ├── dashboard.html          # Painel Principal com Cartões 3D Flip
│   ├── incidents.html          # Histórico de Incidentes
│   └── nginx.conf              # Configuração Nginx
├── Database/                   # Volume Persistente PostgreSQL
├── N8N/                        # Workflows de Automação de Alertas
├── RabbitMQ/                   # Mensageria e Filas de Eventos
├── scripts/
│   └── snmp/                   # Scripts de Configuração dos Agentes SNMP
│       ├── setup_snmp_windows.ps1 # Automação para Windows 10/11
│       ├── setup_snmp_linux.sh    # Automação para Linux (Debian, Ubuntu, Mint, RHEL)
│       └── README.md              # Instruções de Instalação dos Agentes
└── docker-compose.yml          # Orquestração de Containers
```

---

## 🚀 Como Executar o Projeto

### Pró-requisitos

* **Docker** (versão 20.10 ou superior)
* **Docker Compose** (versão 2.0 ou superior)

### 1. Iniciar todos os Containers

Na raiz do projeto, execute:

```bash
docker-compose up -d --build
```

O Docker Compose irá inicializar automaticamente os 5 serviços:
1. `netspot-db` (PostgreSQL 15 em `localhost:5432`)
2. `netspot-backend` (FastAPI em `localhost:8000`)
3. `netspot-frontend` (Nginx em `localhost:8080`)
4. `netspot-rabbitmq` (RabbitMQ Management em `localhost:15672`)
5. `netspot-n8n` (N8N Automation em `localhost:5678`)

## 🧪 Suíte de Testes Automatizados (Pytest)

O NetSpot inclui uma suíte de testes assíncronos completa cobrindo checadores de rede, métricas NOC, retenção de dados, módulo SNMP, modelos ORM e rotas de API RESTful.

Para executar todos os testes automatizados dentro do container backend, rode:

```bash
docker exec -e PYTHONPATH=. netspot-backend python -m pytest Backend/tests -v
```

---

## 🌐 Endereços de Acesso

| Serviço | URL de Acesso | Credenciais Padrão |
| :--- | :--- | :--- |
| 🖥️ **Frontend Dashboard** | [http://localhost:8080](http://localhost:8080) | — |
| 🔌 **Backend API Docs (Swagger)** | [http://localhost:8080/docs](http://localhost:8000/docs) | — |
| 🐇 **RabbitMQ Management** | [http://localhost:15672](http://localhost:15672) | `guest` / `guest` |
| ⚡ **N8N Automation** | [http://localhost:5678](http://localhost:5678) | `admin` / `admin` |

---

## 🔌 Configuração dos Agentes SNMP nos Hosts

Para habilitar o monitoramento de **CPU, Memória RAM, Disco e Tráfego de Rede** nas suas máquinas clientes, utilize os scripts prontos localizados no diretório [`scripts/snmp/`](scripts/snmp/):

### 🪟 No Windows (10 ou 11)

Abra o **PowerShell como Administrador** e execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\snmp\setup_snmp_windows.ps1
```

### 🐧 No Linux (Debian, Ubuntu, Linux Mint, RHEL/Fedora, Arch)

Abra o **Terminal como Root** e execute:

```bash
chmod +x ./scripts/snmp/setup_snmp_linux.sh
sudo ./scripts/snmp/setup_snmp_linux.sh
```

---

## 🛠️ Tecnologias Utilizadas

* **Backend**: Python 3.11, FastAPI, SQLAlchemy, AsyncPG, PySNMP, Pydantic, Uvicorn.
* **Frontend**: HTML5, Vanilla CSS3 (Dark Glassmorphism UI), JavaScript ES6+, Chart.js, Nginx Alpine.
* **Banco de Dados**: PostgreSQL 15.
* **Mensageria & Automação**: RabbitMQ, N8N Workflows.
* **Infraestrutura**: Docker & Docker Compose.

---

## 📄 Licença

Este projeto é disponibilizado sob a licença **MIT**. Sinta-se livre para utilizar, modificar e contribuir!