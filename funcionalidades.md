# 📚 Documentação Completa de Funcionalidades e Arquitetura - NetSpot (NOC Lite)

Este documento descreve detalhadamente **todas as funcionalidades, mecanismos de resiliência, inteligência estatística, arquitetura e recursos de interface** do sistema **NetSpot**.

---

## 📋 Sumário
1. [Visão Geral e Arquitetura](#1-visão-geral-e-arquitetura)
2. [Mecanismos de Autocura e Resiliência (Self-Healing)](#2-mecanismos-de-autocura-e-resiliência-self-healing)
3. [As 5 Funcionalidades Avançadas de Engenharia](#3-as-5-funcionalidades-avançadas-de-engenharia)
4. [Protocolos de Monitoramento e Motor SNMP Multivendor](#4-protocolos-de-monitoramento-e-motor-snmp-multivendor)
5. [Descoberta Automática de Rede e Importação](#5-descoberta-automática-de-rede-e-importação)
6. [Métricas NOC, SLA, Jitter e Score de Saúde](#6-métricas-noc-sla-jitter-e-score-de-saúde)
7. [Política de Retenção e Limpeza de Dados](#7-política-de-retenção-e-limpeza-de-dados)
8. [Gestão de Alertas, Incidentes e N8N / Telegram](#8-gestão-de-alertas-incidentes-e-n8n--telegram)
9. [Interface Frontend SPA (UX & UI)](#9-interface-frontend-spa-ux--ui)
10. [Ambiente de Laboratório Kathará (40+ Nós)](#10-ambiente-de-laboratório-kathará-40-nós)
11. [Suíte de Testes Automatizados (Pytest)](#11-suíte-de-testes-automatizados-pytest)

---

## 1. Visão Geral e Arquitetura

O **NetSpot** é uma plataforma moderna de **Network Operations Center (NOC Lite)** projetada para monitorar em tempo real a saúde, latência, disponibilidade e consumo de recursos de ativos de rede.

### 🏛️ Princípios de Design:
- **Clean Architecture & SOLID**: Separação clara entre camada de rotas (`Backend/routes/`), modelos ORM (`Backend/models/`), schemas DTO (`Backend/schemas/`), serviços de negócios (`Backend/services/`) e motor SNMP (`Backend/snmp/`).
- **Containerização Total**: Isolamento em 5 microsserviços Docker (FastAPI, PostgreSQL 15, RabbitMQ 3, N8N Automation e Nginx Alpine).

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

## 2. Mecanismos de Autocura e Resiliência (Self-Healing)

O NetSpot possui um núcleo auto-regenerativo projetado para tolerar falhas temporárias de infraestrutura sem estourar exceções ou derrubar o servidor FastAPI.

### 🐘 A) Autocura do PostgreSQL (`Backend/database.py`)
- **Pool Auto-Regenerativo**: Configurado no SQLAlchemy com `pool_pre_ping=True` (testa cada conexão antes de usá-la) e `pool_recycle=1800` (recicla conexões TCP ociosas a cada 30 minutos).
- **Dimensionamento do Pool**: `pool_size=20`, `max_overflow=10`, `pool_timeout=30`.
- **Loop de Reconexão Inicial (`wait_for_database`)**: Na inicialização do Docker Compose, se o PostgreSQL estiver subindo, o FastAPI tenta reconectar por até 15 vezes com *backoff* exponencial sem quebrar a aplicação.

### 🐇 B) Autocura do RabbitMQ (`Backend/mq_manager.py`)
- **Conexão Robusta**: Conectado via `aio_pika.connect_robust()` que restabelece o canal TCP automaticamente em caso de oscilação de rede.
- **Monitor de Segundo Plano (`_monitor_connection_loop`)**: Loop assíncrono que verifica a saúde do broker a cada 5 segundos. Em caso de queda, reconecta de forma transparente e **re-inscreve todos os consumidores automaticamente**.

---

## 3. As 5 Funcionalidades Avançadas de Engenharia

### 1. 🛡️ Diagnóstico de Saúde Nativo (`/healthz` + Docker Healthcheck)
- Endpoint `/healthz` que faz checagens em sub-milissegundos no PostgreSQL (`SELECT 1`) e nos canais do RabbitMQ.
- Integrado ao `docker-compose.yml` via `CMD-SHELL`, permitindo que o Docker monitore a saúde do container e o reinicie automaticamente caso fique inativo.

### 2. ⚡ Pattern Circuit Breaker (Disjuntor de Polling)
- Implementado em `Backend/services/circuit_breaker.py`.
- Se um host falhar por 5 vezes seguidas (`failure_threshold`), o estado transita de `CLOSED` para `OPEN`.
- Durante 120s em `OPEN`, o NetSpot **interrompe o envio de novos pings e SNMP para aquele host**, evitando tempestades de pacotes e esgotamento de sockets na rede.
- Após 120s, entra em `HALF-OPEN` para testar se o dispositivo respondeu. Se responder, o disjuntor fecha (`CLOSED`).

### 3. 📥 Dead Letter Queue (DLQ) no RabbitMQ (`netspot.dlq`)
- Declaração automatizada da *Dead Letter Exchange* (`netspot.dlx`) e *Dead Letter Queue* (`netspot.dlq`).
- Mensagens que falham no consumo de tarefas ou notificações são encaminhadas para a DLQ, garantindo **0% de perda de eventos** mesmo durante indisponibilidades.

### 4. 🔕 Anti-Fadiga de Alertas e Supressão de Flapping
- Função `is_flapping_suppressed()` em `Backend/notifications.py`.
- Detecta quando um ativo oscila repetidamente de estado (ex: `UP` $\leftrightarrow$ `DOWN` mais de 4 vezes em 5 minutos).
- Suprime disparos repetitivos no Telegram para **evitar a fadiga de alertas (*Alert Fatigue*)** na equipe de TI.

### 5. 🛑 Desligamento Gracioso (Graceful Shutdown com SIGTERM)
- Interceptação de sinais do sistema `SIGTERM` e `SIGINT` em `Backend/main.py`.
- Ao executar `docker stop`, o sistema encerra o motor de polling, aguarda as mensagens pendentes e libera de forma sequencial os pools do SQLAlchemy (`engine.dispose()`) e canais do broker.

---

## 4. Protocolos de Monitoramento e Motor SNMP Multivendor

### 📡 Protocolos Suportados:
- **ICMP Ping**: Medição de latência (ms) e status de conectividade.
- **TCP Check**: Verificação de portas de serviços (ex: 80, 443, 22, 3306, 5432).
- **HTTP / HTTPS**: Verificação de código de retorno (200 OK) e tempo de resposta web.
- **DNS**: Validação de resolução de nomes de domínio (A records).

### 📊 Agente SNMP Multivendor (`Backend/snmp/`):
- **Linux (UCD-SNMP-MIB)**: Leitura de CPU (`ssCpuIdle`), RAM Real (`memTotalReal`, `memAvailReal`), Disco (`/`) e Tráfego de Rede.
- **Windows (HOST-RESOURCES-MIB)**: Leitura de CPU (`hrProcessorLoad`), RAM (`hrStorageSize`, `hrStorageUsed` para `Virtual/Physical Memory`), Disco (`C:\`) e Tráfego de Interfaces.
- **Ativos de Rede (Cisco / Mikrotik)**: Leitura de estatísticas de tráfego de interface e contadores de bytes.

---

## 5. Descoberta Automática de Rede e Importação

- **Varredura de Sub-rede**: Endpoint `/network/discover` faz varredura na faixa declarada (ex: `10.0.1.0/24`) identificando todos os endereços IP ativos.
- **Importação Inteligente (`/network/import`)**:
  - Cadastra os ativos descobertos no banco de dados.
  - Força a habilitação do monitoramento SNMP (`snmp_enabled = True`) e community (`netspot`) por padrão.
  - Caso o host já existia inativo no banco, **reativa o ativo e restaura a coleta SNMP automaticamente**.

---

## 6. Métricas NOC, SLA, Jitter e Score de Saúde

- **Health Score (0 a 100%)**: Avaliação ponderada da saúde do host baseada na disponibilidade do Ping, serviços TCP, resposta HTTP e consumo de recursos (CPU/RAM/Disco).
- **Disponibilidade SLA (%)**: Cálculo do tempo de uptime percentual nas janelas de 10 minutos, 1 hora, 24 horas e 30 dias.
- **Jitter (ms)**: Medição da variação de latência entre as checagens sucessivas para identificar instabilidade na rede.
- **Análise de Tendência**: Classificação automática da estabilidade (`Estável`, `Degradação`, `Recuperação`).

---

## 7. Política de Retenção e Limpeza de Dados

- **Configuração via `.env`**: Parâmetro `NETSPOT_RETENTION_DAYS` define o tempo de retenção do histórico (ex: `30` para 30 dias).
- **Desativação Flexível**: Definir `NETSPOT_RETENTION_DAYS=0` **desativa** a rotina de purga, mantendo o histórico de métricas indefinidamente.
- **Execução Automática**: Limpeza periódica em background que remove registros antigos das tabelas de resultados, métricas SNMP, alertas e histórico de incidentes sem impactar o desempenho do banco.

---

## 8. Gestão de Alertas, Incidentes e N8N / Telegram

- **Gestão Automática de Incidentes**: Abertura de incidente quando um host entra em estado `DOWN` ou `DEGRADED`, e fechamento automático com cálculo do tempo total de indisponibilidade quando o host retorna ao estado `UP`.
- **Integração N8N & Telegram**: Envio de payloads JSON via webhook para o N8N, que formata e despacha alertas estilizados diretamente para grupos do Telegram.

---

## 9. Interface Frontend SPA (UX & UI)

### 🎨 Design System e Layout:
- **Tema Dark Glassmorphism**: Interface moderna desenvolvida em HTML5 e Vanilla CSS com tipografia Inter/Roboto, efeitos de transparência e bordas suaves.
- **Grid de 3 Cards por Linha**: Organização visual fixada em **exatamente 3 colunas no Desktop**, ajustando-se responsivamente para 2 colunas em tablets e 1 coluna em smartphones.
- **Remoção Otimista Instantânea**: Ao excluir ou mover um host para a lixeira, o card sofre um desvanecimento suave em 200ms e é removido instantaneamente da tela, atualizando o painel de resumo e estatísticas do topo em paralelo.
- **Cartões 3D Flip**: Alternância de faces dos cards de host para exibição de métricas rápidas, gráficos de latência em tempo real, indicadores SNMP (CPU, RAM, Disco, Tráfego) e histórico detalhado.

---

## 10. Ambiente de Laboratório Kathará (40+ Nós)

- Documentado em [`kathara.md`](file:///home/Crispim/Desktop/Documents/TCC%20-%20NetSpot/kathara.md).
- **Simulação em Larga Escala**: Suporte à criação de 40+ dispositivos virtuais Kathará distribuídos em 4 sub-redes roteadas (`10.0.1.0/24`, `10.0.2.0/24`, `10.0.3.0/24`, `192.168.100.0/24`).
- **Injeção de Falhas**: Simulação de queda de link, aumento de latência/perda de pacotes via `tc (Traffic Control)` e sobrecarga de hardware via `stress-ng`.

---

## 11. Suíte de Testes Automatizados (Pytest)

- Localizada no diretório [`Backend/tests/`](file:///home/Crispim/Desktop/Documents/TCC%20-%20NetSpot/Backend/tests/).
- **31 Testes Automatizados (100% PASSED)**:
  - `test_checker.py`: Checadores de Ping, TCP, HTTP e DNS.
  - `test_metrics.py`: Algoritmos de Health Score, SLA, Jitter e Tendências.
  - `test_retention.py`: Regras da política de retenção de dados.
  - `test_snmp.py`: Parsers e conversores SNMP Multivendor.
  - `test_api_routes.py`: Endpoints RESTful e integração HTTP.
  - `test_models_schemas.py`: Validação de DTOs e entidades SQLAlchemy.
  - `test_self_healing.py`: Validação dos pools de autocura, Circuit Breaker, DLQ e Anti-Flapping.

Comandos para rodar a suíte:
```bash
docker exec -e PYTHONPATH=. netspot-backend python -m pytest Backend/tests -v
```

---
*NetSpot - Sistema Inteligente de Monitoramento de Rede (NOC Lite)*
