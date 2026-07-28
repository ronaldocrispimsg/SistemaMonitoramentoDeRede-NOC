# 🧪 Planejamento de Laboratório Experimental com Kathará no NetSpot

Este documento apresenta a análise de viabilidade, arquitetura da topologia e metodologia experimental para a simulação de uma rede corporativa/acadêmica em larga escala (40+ dispositivos) utilizando a ferramenta **Kathará**, validando o protótipo **NetSpot (NOC Lite)** no âmbito do Trabalho de Conclusão de Curso (TCC - IFNMG Campus Januária).

---

## 🏛️ 1. Análise de Viabilidade Técnica e Desempenho

O **Kathará** é uma ferramenta de emulação de redes baseada em **containers Docker leves** (sucessora do Netkit/Marionnet). Diferente de hipervisores tradicionais (como KVM/QEMU no GNS3 ou EVE-NG) que inicializam instâncias completas de sistemas operacionais exigindo gigabytes de memória por nó, o Kathará compartilha o kernel do host.

### 📊 Estimativa de Carga Computacional:

* **Consumo por Nó Kathará (Debian/Alpine com SNMPD e ferramentas de rede)**: $\approx 15\text{ MB a } 25\text{ MB de RAM}$ por nó ocioso.
* **Carga de 40 Nós Kathará**:
  $$\text{RAM dos 40 Nós Simulados} \approx 40 \times 20\text{ MB} = 800\text{ MB de RAM}$$
* **Carga da Infraestrutura NetSpot (5 Containers)**:
  * PostgreSQL 15: $\approx 150\text{ MB}$
  * RabbitMQ Broker: $\approx 180\text{ MB}$
  * Backend FastAPI (Python 3.11): $\approx 120\text{ MB}$
  * N8N Automation: $\approx 350\text{ MB}$
  * Frontend Nginx: $\approx 20\text{ MB}$
  * **Total NetSpot**: $\approx 820\text{ MB a } 1.2\text{ GB}$
* **Consumo Global Estimado do Laboratório**: **~2.0 GB a 3.0 GB de RAM Total**.

> **Conclusão de Viabilidade**: O experimento com 40 computadores e múltiplos roteadores roda com folga em qualquer computador pessoal com 8 GB ou 16 GB de RAM.

---

## 🌐 2. Arquitetura da Topologia de Rede Simulada

A topologia simulada representa um ambiente corporativo/acadêmico dividido em **4 Sub-redes Roteadas**:

```text
                               +-----------------------------+
                               |     NetSpot Server (NOC)    |
                               | (192.168.100.2 / Backend)   |
                               +--------------+--------------+
                                              |
                                     +--------+--------+
                                     | Roteador Core   |
                                     |  (Kathará Router)|
                                     +----+---+---+----+
                                          |   |   |
         +--------------------------------+   |   +--------------------------------+
         |                                    |                                    |
+--------+--------+                  +--------+--------+                  +--------+--------+
| Roteador Lab 1  |                  | Roteador Lab 2  |                  | Roteador Servid. |
|  (10.0.1.1/24)  |                  |  (10.0.2.1/24)  |                  |  (10.0.3.1/24)  |
+--------+--------+                  +--------+--------+                  +--------+--------+
         |                                    |                                    |
   (15 Clientes)                        (15 Clientes)                        (10 Servidores)
   - PC-01 a PC-15                      - PC-16 a PC-30                      - Web, DNS, DB
   - Agente SNMP (MIBs)                 - Agente SNMP (MIBs)                 - Agente SNMP (MIBs)
```

---

## 🔬 3. Cenários de Testes Práticos e Simulação de Falhas

Com o Kathará, é possível injetar anomalias controladas de forma determinística para avaliar o comportamento do NetSpot:

### 🚨 Cenário A: Queda Abrupta de Nó (Estado DOWN)
* **Ação**: Interrupção forçada do container (`kathara vclean -n pc12` ou parada do serviço no nó).
* **Métrica Aferida**: Tempo até a abertura do incidente no PostgreSQL e envio do alerta preventivo via API do Telegram.
* **Meta**: Tempo Médio de Detecção ($\text{MTTD} < 30\text{ segundos}$).

### ⚠️ Cenário B: Instabilidade e Latência Elevada (Estado DEGRADED)
* **Ação**: Injeção de latência e perda de pacotes no enlace do nó Kathará via `tc` (Traffic Control):
  ```bash
  tc qdisc add dev eth0 root netem delay 250ms loss 12%
  ```
* **Métrica Aferida**: Reclassificação do **Health Score (0 a 100)** e cálculo de **Jitter (ms)** em tempo real no Dashboard.

### ⚡ Cenário C: Sobrecarga de Recursos Físicos (Preventivo SNMP)
* **Ação**: Execução do utilitário `stress-ng` dentro de um nó Kathará para elevar o uso de CPU acima de 90%:
  ```bash
  stress-ng --cpu 4 --timeout 60s
  ```
* **Métrica Aferida**: Coleta da OID SNMP de CPU (`hrProcessorLoad` / `ssCpuIdle`), alteração do indicador visual de uso de hardware e disparo de alerta preventivo antes do travamento total do dispositivo.

---

## 🎯 4. Estratégia Metodológica para a Defesa do TCC

Para garantir o rigor acadêmico, a metodologia do TCC combinará duas vertentes complementares:

1. **Escala Simulada Controlada (Kathará)**:
   * **Objetivo**: Testar a capacidade do motor de polling do NetSpot frente a 40+ dispositivos e cenários complexos de roteamento/degradação.
   * **Entregável**: Gráficos de estresse, tempo de reação e consumo computacional do servidor de monitoramento.
2. **Ambiente Físico Real (Laboratório 2 do IFNMG)**:
   * **Objetivo**: Validação com 20 computadores físicos em produção durante os horários de monitoria da disciplina de Administração de Redes.
   * **Entregável**: Validação de usabilidade, tráfego real de alunos e avaliação por administradores de rede locais.

---

## 🚀 5. Como Executar o Laboratório Kathará e Integrar com o NetSpot

1. **Instalar o Kathará no Linux:**
   ```bash
   sudo apt-get install kathara
   ```
2. **Iniciar o Kathará:**
   ```bash
   kathara lstart
   ```
3. **Automação da Conexão de Rede NetSpot <-> Kathará:**
   A integração é **100% automática** ao iniciar o NetSpot via `docker compose up -d`:
   * O `docker-compose.yml` conecta automaticamente os containers `netspot-backend` e `netspot-n8n` à rede `bridge` padrão do Docker.
   * O `Backend` instala as dependências (`iproute2`, `snmp`) na imagem e injeta automaticamente as rotas estáticas (`10.0.0.0/16` e `100.0.0.0/16 via 172.17.0.2`) ao inicializar o FastAPI.
4. **Execução Manual da Conexão (Caso necessário):**
   Se o Kathará for iniciado *após* os containers do NetSpot, basta rodar o script de automação fornecido:
   ```bash
   ./scripts/setup_kathara_network.sh
   ```
5. Executar os cenários de simulação e registrar as métricas.

