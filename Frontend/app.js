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
    const httpUrlInput = document.getElementById("http_url");
    
    const data = {
        name: nameInput.value,
        address: addressInput.value,
        port: portInput.value ? parseInt(portInput.value) : null,
        http_url: httpUrlInput.value
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
            httpUrlInput.value = "";
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

            let statusColor = "bg-secondary";
            if (h.status === "UP") statusColor = "bg-success";
            else if (h.status === "DOWN") statusColor = "bg-danger";
            else if (h.status === "DEGRADED") statusColor = "bg-warning";
            
            let sevClass = "sev-unknown";

            if (h.severity === "HEALTHY") sevClass = "sev-healthy";
            else if (h.severity === "WARNING") sevClass = "sev-warning";
            else if (h.severity === "DEGRADED") sevClass = "sev-degraded";
            else if (h.severity === "CRITICAL") sevClass = "sev-critical";

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
                        </br><small>Saúde: ${h.health_score}%<span class="severity-indicator ${sevClass}">✚</span></small>
                        </br><small>Taxa de sucesso (ping): ${h.sla_rolling_ping ?? "N/A"}%</small>
                        </br><small>Variacao na latencia (ping): ${h.jitter_ms_ping ?? "N/A"}ms</small>
                        </br><small>Taxa de sucesso (tcp): ${h.sla_rolling_tcp ?? "N/A"}%</small>
                        </br><small>Variacao na latencia (tcp): ${h.jitter_ms_tcp ?? "N/A"}ms</small>
                        </br><small>Taxa de sucesso (http): ${h.sla_rolling_http ?? "N/A"}%</small>
                        </br><small>Variacao na latencia (http): ${h.jitter_ms_http ?? "N/A"}ms</small>
                        </br><small>Tendencia (http): ${h.trend_http ?? "N/A"}</small>
                    </div>
                    <div class="button-group" style="display: flex; gap: 10px;">
                        <button class="history-btn"
                            onclick="toggleHistory('${h.name}')">
                            Histórico
                        </button>
                        <button class="latency-btn"
                            onclick="toggleLatencyChart('${h.name}')">
                            Gráfico de latência
                        </button>
                        <button onclick="toggleSLAChart('${h.name}')">
                            Gráfico de SLA
                        </button>
                        <button onclick="toggleHeatmap('${h.name}')">
                            Heatmap
                        </button>
                        <button onclick="openEditModal('${h.name}', '${h.address}', '${h.port ?? ""}', '${h.http_url ?? ""}')">
                            Editar
                        </button>
                        <button class="delete-btn" onclick="softDeleteHost('${h.name}')">
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
                <div id="sla-chart-box-${h.name}" class="hidden">
                    <canvas id="sla-chart-${h.name}" height="120"></canvas>
                </div>
                <div id="history-${h.name}" class="history-box hidden"></div>
                <div id="heatmap-${h.name}" class="hidden heatmap-box"></div>

            `;

            div.appendChild(card);
            
            } else {
                // SE JÁ EXISTE, SÓ ATUALIZA A BOLINHA DE STATUS PRINCIPAL
                const indicator = card.querySelector(".status-indicator");
                indicator.className = `status-indicator ${statusColor}`;
            }
            
            // ATUALIZA OS DADOS DE PING/TCP
            loadLastResult(h.name);

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

async function loadLastResult(name) {
    const box = document.getElementById("result-" + name);

    const res = await fetch(`${API}/host/history/${name}`);
    const data = await res.json();

    const lastPing = data.checks.find(c => c.type === "ping");
    const lastTcp  = data.checks.find(c => c.type === "tcp");
    const lastHttp = data.checks.find(c => c.type === "http");

    const pingDot = lastPing?.success ? "bg-success" : "bg-danger";
    const tcpDot  = lastTcp?.success ? "bg-success" : "bg-danger";
    const httpDot = lastHttp?.success ? "bg-success" : "bg-danger";

    box.innerHTML = `
        <div>
            <span class="status-indicator ${pingDot}"></span>
            Ping: ${lastPing?.latency ?? "N/A"} ms
        </div>
        ${lastTcp ? `
        <div>
            <span class="status-indicator ${tcpDot}"></span>
            TCP: ${lastTcp.latency ?? "N/A"} ms
        </div>` : ''}
        ${lastHttp ? `
        <div>
            <span class="status-indicator ${httpDot}"></span>
            HTTP: ${lastHttp.latency ?? "N/A"} ms ${lastHttp.status_code ?? lastHttp.error ?? ""}
        </div>` : ''}
    `;
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

async function toggleSLAChart(name) {

    const box = document.getElementById("sla-chart-box-" + name);

    if (!box) return;

    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        return;
    }

    box.classList.remove("hidden");
    loadSLAChart(name);
}


async function toggleHeatmap(name) {
    const box = document.getElementById("heatmap-" + name);

    if (!box) return;

    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        return;
    }

    box.classList.remove("hidden");
    await loadHeatmap(name);
}

let currentEditHost = null;

function openEditModal(name, ip, port, httpUrl) {
    currentEditHost = name;

    document.getElementById("modal-name").value = name;
    document.getElementById("modal-ip").value = ip;
    document.getElementById("modal-port").value = port;
    document.getElementById("modal-http-url").value = httpUrl || "";

    document.getElementById("editModal").classList.remove("hidden");
}

function closeModal() {
    document.getElementById("editModal").classList.add("hidden");
}

async function submitModalEdit() {
    const newName = document.getElementById("modal-name").value;
    const newIp = document.getElementById("modal-ip").value;
    const newPort = document.getElementById("modal-port").value;
    const newHttp = document.getElementById("modal-http-url").value;

    const res = await fetch(`${API}/host/update/${currentEditHost}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            address: newIp,
            port: newPort ? parseInt(newPort) : null,
            http_url: newHttp || null
        })
    });

    if (res.ok) {
        closeModal();
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
    const http = data.checks.filter(c => c.type === "http");

    const labels = ping.map(c =>
        new Date(c.timestamp).toLocaleTimeString()
    );

    const pingData = ping.map(c => c.latency);
    const tcpData  = tcp.map(c => c.latency);
    const httpData = http.map(c => c.latency);

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
                ,{
                    label: "HTTP",
                    data: httpData
                }
            ]
        },
        options: {
            responsive: true,
            animation: false
        }
    });
}

async function loadSLAChart(name) {

    const res = await fetch(`${API}/host/sla_chart/${name}`);
    const data = await res.json();

    const ping = data.ping || [];
    const tcp  = data.tcp || [];
    const http = data.http || [];

    // labels baseadas no ping (principal)
    const labels = ping.map(p =>
        new Date(p.time).toLocaleTimeString()
    );

    const pingValues = ping.map(p => p.sla);
    const tcpValues  = tcp.map(p => p.sla);
    const httpValues = http.map(p => p.sla);

    const ctx = document.getElementById("sla-chart-" + name);

    // destruir chart antigo se existir
    if (charts["sla-" + name]) {
        charts["sla-" + name].destroy();
    }

    charts["sla-" + name] = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "SLA Ping %",
                    data: pingValues
                },
                {
                    label: "SLA TCP %",
                    data: tcpValues
                },
                {
                    label: "SLA HTTP %",
                    data: httpValues
                }
            ]
        },
        options: {
            animation: false,
            responsive: true,
            scales: {
                y: {
                    min: 0,
                    max: 100
                }
            }
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

async function loadHeatmap(name) {

    const res = await fetch(`${API}/host/heatmap/${name}`);
    const data = await res.json();

    const box = document.getElementById("heatmap-" + name);
    box.innerHTML = "";

    data.forEach(p => {
        const d = document.createElement("div");
        d.className = "heat-cell";

        if (p.latency == null)
            d.style.background = "#444";
        else if (p.latency < 50)
            d.style.background = "#2ecc71";
        else if (p.latency < 150)
            d.style.background = "#f1c40f";
        else
            d.style.background = "#e74c3c";

        d.title = p.time + " → " + p.latency + " ms";

        box.appendChild(d);
    });
}


// ======================
// Inicialização e Loop
// ======================

setInterval(loadHosts, 10000);
setInterval(checkAlerts, 5000);

document.getElementById("refreshBtn").addEventListener("click", loadHosts);
window.onload = loadHosts;

window.onclick = function(event) {
        const modal = document.getElementById("editModal");
        if (event.target === modal) {
            closeModal();
        }
    };
