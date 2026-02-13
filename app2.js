const API = "http://127.0.0.1:8000";
const charts = {};
// ======================
// Cadastrar Host (POST)
// ======================
document.getElementById("hostForm").addEventListener("submit", async (e) => {
    e.preventDefault();

    // Selecionando os elementos de forma explícita (mais seguro)
    const nameInput = document.getElementById("name");
    const addressInput = document.getElementById("address");
    const portInput = document.getElementById("port");

    const data = {
        name: nameInput.value,
        address: addressInput.value,
        port: portInput.value ? parseInt(portInput.value) : null
    };

    try {
        const response = await fetch(`${API}/host/create`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            // Limpa o formulário após sucesso
            nameInput.value = "";
            addressInput.value = "";
            portInput.value = "";
            loadHosts();
        } else {
            const errorData = await response.json();
            alert("Erro ao cadastrar: " + (errorData.detail || "Erro desconhecido"));
        }
    } catch (err) {
        console.error("Erro na requisição:", err);
        alert("Não foi possível conectar ao servidor.");
    }
});

// ======================
// Listar e Atualizar Hosts
// ======================
async function loadHosts() {
    const div = document.getElementById("hosts");
    
    try {
        const res = await fetch(`${API}/hosts/list`);
        const hosts = await res.json();
        div.innerHTML = "";
        hosts.forEach(h => {
            let card = document.getElementById(`card-${h.name}`);

            // DEFINIÇÃO DE CORES
            let statusColor = "bg-secondary";
            if (h.status === "UP") statusColor = "bg-success";
            else if (h.status === "DOWN") statusColor = "bg-danger";
            else if (h.status === "DEGRADED") statusColor = "bg-warning";

            // SE O CARD NÃO EXISTE, CRIA A ESTRUTURA
            if (!card) {
                card = document.createElement("div");
                card.className = "card";
                card.id = `card-${h.name}`;

            card.innerHTML = `
                <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>${h.name}</strong> 
                        <span class="status-indicator ${statusColor}"></span>
                        <small>(${h.address}${h.port ? ':' + h.port : ''})</small>
                    </div>
                    <div class="button-group" style="display: flex; gap: 10px;">
                        <button class="history-btn"
                            onclick="toggleHistory('${h.name}')">
                            Ver histórico
                        </button>
                        <button class="latency-btn"
                            onclick="toggleLatencyChart('${h.name}')">
                            Ver gráfico de latência
                        </button>
                        <div id="edit-form-${h.name}" class="hidden mini-form">
                            <input id="edit-name-${h.name}" value="${h.name}" placeholder="Nome">
                            <input id="edit-ip-${h.name}" value="${h.address}" placeholder="Endereço">
                            <input id="edit-port-${h.name}" value="${h.port ?? ''}" placeholder="Porta">

                            <button onclick="saveHost('${h.name}')">
                                Salvar
                            </button>
                        </div>
                        <button onclick="toggleEditForm('${h.name}')">
                            Editar
                        </button>
                        <button class="delete-btn"
                            onclick="softDeleteHost('${h.name}')">
                            Deletar
                        </button>
                    </div>
                </div>
                
                <div id="result-${h.name}" style="margin-top: 10px; font-size: 0.9em;">
                    <i>Atualizando...</i>
                </div>
                <div id="chart-container-${h.name}" class="hidden" style="margin-top: 10px;">
                    <canvas id="chart-${h.name}" height="120"></canvas>
                </div>
                <div id="history-${h.name}" class="history-box hidden"></div>

            `;

           div.appendChild(card);
            } else {
                // SE JÁ EXISTE, SÓ ATUALIZA A BOLINHA DE STATUS PRINCIPAL
                const indicator = card.querySelector(".status-indicator");
                indicator.className = `status-indicator ${statusColor}`;
            }

            // ATUALIZA OS DADOS DE PING/TCP
            checkHost(h.name);

            // SE O GRÁFICO ESTIVER ABERTO, ATUALIZA ELE TAMBÉM
            const container = document.getElementById("chart-container-" + h.name);
            if (container && !container.classList.contains("hidden")) {
                loadLatencyChart(h.name);
            }
        });
    } catch (err) {
        console.error("Erro ao carregar lista de hosts:", err);
    }
}

async function checkHost(name) {
    const box = document.getElementById("result-" + name);

    try {
        const res = await fetch(`${API}/host/check/${name}`, { method: "POST" });
        if (!res.ok) throw new Error();

        const data = await res.json();

        //bolinhas pra Ping e TCP
        const pingDot = (data.ping && data.ping.latency !== null) ? "bg-success" : "bg-danger";
        const tcpDot = (data.tcp && data.tcp.latency !== null) ? "bg-success" : "bg-danger";

        box.innerHTML = `
            <div>
                <span class="status-indicator ${pingDot}"></span>
                Ping: ${data.ping.latency ?? "N/A"} ms
            </div>
            ${data.tcp ? `
            <div>
                <span class="status-indicator ${tcpDot}"></span>
                TCP: ${data.tcp.latency ?? "N/A"} ms
            </div>` : ''}
        `;
    } catch (err) {
        box.innerHTML = "<small style='color:red'>Erro na verificação.</small>";
    }
}

async function loadHistory(name) {
    const box = document.getElementById("history-" + name);
    box.innerHTML = "Carregando histórico...";

    try {
        const res = await fetch(`${API}/host/history/${name}`);
        const data = await res.json();

        if (!data.checks.length) {
            box.innerHTML = "<small>Sem histórico ainda</small>";
            return;
        }

        box.innerHTML = data.checks.map(c => {
            const statusClass = c.success ? "line-success" : "line-error";
            const statusText = c.success ? "OK" : "FAIL";

            return `
                <div class="history-line ${statusClass}">
                    <span class="type-badge">[${c.type.toUpperCase()}]</span> 
                    <strong>${statusText}</strong> —
                    ${c.latency !== null ? c.latency + " ms" : "---"} —
                    <small>${new Date(c.timestamp).toLocaleTimeString()}</small>
                </div>
            `;
        }).join("");

    } catch {
        box.innerHTML = "Erro ao carregar histórico";
    }
}

async function toggleHistory(name) {
    const box = document.getElementById("history-" + name);

    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        return;
    }

    box.classList.remove("hidden");
    await loadHistory(name);
}
async function toggleLatencyChart(name) {
    const container = document.getElementById("chart-container-" + name);
    if (!container) return;

    if (container.classList.contains("hidden")) {
        container.classList.remove("hidden");
        await loadLatencyChart(name);
    } else {
        container.classList.add("hidden");
    }
}

function toggleEditForm(name) {
    const box = document.getElementById("edit-form-" + name);
    if (!box) return;

    box.classList.toggle("hidden");
}

async function saveHost(name) {
    const newName = document.getElementById("edit-name-" + name).value;
    const newIp   = document.getElementById("edit-ip-" + name).value;
    const newPort = document.getElementById("edit-port-" + name).value;

    const res = await fetch(`${API}/host/update/${name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: newName,
            address: newIp,
            port: newPort ? parseInt(newPort) : null
        })
    });

    if (res.ok) {
        await loadHosts();
    } else {
        alert("Erro ao salvar");
    }
}



async function loadLatencyChart(name) {
    if (charts[name]) charts[name].destroy();

    const res = await fetch(`${API}/host/history/${name}`);
    const data = await res.json();

    const ping = data.checks.filter(c => c.type === "ping");
    const tcp  = data.checks.filter(c => c.type === "tcp");

    const labels = ping.map(c =>
        new Date(c.timestamp).toLocaleTimeString()
    );

    const pingData = ping.map(c => c.latency);
    const tcpData  = tcp.map(c => c.latency);

    const ctx = document.getElementById("chart-" + name);

    if (!ctx) return;

    charts[name] = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Ping",
                    data: pingData
                },
                {
                    label: "TCP",
                    data: tcpData
                }
            ]
        },
        options: {
            responsive: true,
            animation: false
        }
    });
}

function showAlertCard(alert) {
    const box = document.getElementById("alert-container");

    const card = document.createElement("div");
    card.className = "alert-card";

    if (alert.new_status === "DOWN") 
        card.classList.add("alert-down");

    else if (alert.new_status === "UP") 
        card.classList.add("alert-up");

    else 
        card.classList.add("alert-degraded");

    card.innerHTML = `
        <strong>${alert.host_name}</strong><br>
        ${alert.old_status} → ${alert.new_status}
    `;

    box.appendChild(card);

    setTimeout(() => {
        card.remove();
    }, 6000);
}

let lastAlertTime = null;

async function checkAlerts() {
    const res = await fetch(`${API}/alerts/list`);
    const alerts = await res.json();

    alerts.forEach(a => {
        if (!lastAlertTime || a.timestamp > lastAlertTime) {
            showAlertCard(a);
            lastAlertTime = a.timestamp;
        }
    });
}

async function softDeleteHost(name) {

    if (!confirm("Remover host?")) return;

    try {
        const res = await fetch(`${API}/host/delete/${name}`, {
            method: "DELETE"
        });

        if (!res.ok) {
            const err = await res.json();
            alert("Erro ao remover: " + (err.detail || "erro"));
            return;
        }

        await loadHosts();

    } catch (e) {
        alert("Falha de conexão com API");
    }
}



// ======================
// Inicialização e Loop
// ======================

setInterval(loadHosts, 10000);
setInterval(checkAlerts, 5000);

document.getElementById("refreshBtn").addEventListener("click", loadHosts);
window.onload = loadHosts;