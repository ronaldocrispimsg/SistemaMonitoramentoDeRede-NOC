const API = "http://127.0.0.1:8000";
const charts = {};

if (Notification.permission !== "granted") {
    Notification.requestPermission();
}

const token = localStorage.getItem("token");
const isLoginPage = window.location.pathname.includes("login.html");


// se estiver logado e abrir login → vai pro dashboard
if (token && isLoginPage) {
    window.location.href = "index.html";
}

// se NÃO estiver logado e tentar acessar sistema → volta pro login
if (!token && !isLoginPage) {
    window.location.href = "login.html";
}

// ======================
// Helper: Requisições Autenticadas
// ======================
async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem("token");
    const headers = {
        "Content-Type": "application/json",
        ...options.headers,
        "Authorization": `Bearer ${token}`
    };

    try {
        const response = await fetch(url, { ...options, headers });
        
        if (!response || response.status === 401) {
            alert("Sessão expirada. Por favor, faça login novamente.");
            localStorage.clear();
            window.location.href = "login.html";
            return null;
        }
        
        return response;
    } catch (error) {
        console.error("Erro de conexão:", error);
        // Opcional: mostrar um aviso visual discreto na tela
        return null;
    }
}

// ======================
// Login
// ======================
const loginForm = document.getElementById("loginForm");

if (loginForm) {
    loginForm.onsubmit = async function(e) {
        e.preventDefault();
        const userVal = document.getElementById("username").value;
        const passVal = document.getElementById("password").value;

        try {
            const response = await fetch(`${API}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: userVal, password: passVal })
            });

            const data = await response.json();

            if (response.ok && data.access_token) {
                localStorage.setItem("token", data.access_token);
                localStorage.setItem("username", userVal); // Guardamos para usar na troca

                // VERIFICA SE PRECISA TROCAR SENHA
                if (data.must_change_password) {
                    document.getElementById("pwdModal").classList.remove("hidden");
                } else {
                    alert("Login realizado com sucesso!");
                    window.location.href="index.html";
                }
            } else {
                alert("Erro: " + (data.detail || "Credenciais inválidas"));
            }
        } catch (err) {
            alert("Não foi possível conectar ao servidor.");
        }
    };
}

async function submitChangePassword(){

    const newPwd = document.getElementById("new-pwd").value;
    const confirmPwd = document.getElementById("confirm-pwd").value;

    if(newPwd !== confirmPwd)
        return alert("Senhas não coincidem");

    const token = localStorage.getItem("token");

    const res = await fetch(`${API}/auth/first-password`,{
        method:"POST",
        headers:{ 
            "Content-Type":"application/json",
            "Authorization": "Bearer " + token
        },
        body:JSON.stringify({
            new_password:newPwd
        })
    });

    if(res.ok){
        alert("Senha alterada! Sistema Liberado.");
        window.location.href="index.html";
    }else{
        alert("Erro ao alterar senha");
    }
}

async function changePassword(){
    const currentPwd = document.getElementById("current-pwd").value;
    const newPwd = document.getElementById("new-pwd").value;
    const confirmPwd = document.getElementById("confirm-pwd").value;

    if (newPwd !== confirmPwd) return alert("As senhas não coincidem!");
    if (newPwd.length < 6) return alert("Senha muito curta!");

    const token = localStorage.getItem("token");

    const res = await fetch(`${API}/auth/change-password`,{
        method:"POST",
        headers:{
            "Content-Type":"application/json",
            "Authorization":"Bearer "+token
        },
        body: JSON.stringify({
            current_password:currentPwd,
            new_password:newPwd
        })
    });

    if(res.status === 403){
        alert("Conta bloqueada. Contate o administrador.");
    }

    if(res.ok){
        alert("Senha alterada com sucesso!");
        localStorage.removeItem("token");
        window.location.href = "login.html";
    }else{
        alert("Erro ao alterar senha");
    }

}
// ======================
// Cadastrar Host (POST)
// ======================
const hostForm = document.getElementById("hostForm");

if (hostForm) {
    hostForm.addEventListener("submit", async (e) => {
        e.preventDefault();

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
            const response = await fetchWithAuth(`${API}/host/create`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data)
            });

            if (!response) return;

            if (response.ok) {
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
}

// ======================
// Listar e Atualizar Hosts
// ======================
async function loadHosts() {
    const div = document.getElementById("hosts");
    if (!div) return;

    try {
        const res = await fetchWithAuth(`${API}/hosts/list`);
        if (!res) {
            div.innerHTML = "<p style='color:orange'>⚠ Não foi possível carregar os hosts.</p>";
            return;
        }

        const hosts = await res.json();
        div.innerHTML = "";

        hosts.forEach(h => {
            const card = document.createElement("div");
            card.className = "card";
            card.id = `card-${h.name}`;
            if (h.severity === "CRITICAL") {
                card.classList.add("card-critical");
            }

            let statusColor = "bg-secondary";
            if (h.status === "UP") statusColor = "bg-success";
            else if (h.status === "DOWN") statusColor = "bg-danger";
            else if (h.status === "DEGRADED") statusColor = "bg-warning";
            
            let sevClass = "sev-unknown";

            if (h.severity === "HEALTHY") sevClass = "sev-healthy";
            else if (h.severity === "WARNING") sevClass = "sev-warning";
            else if (h.severity === "DEGRADED") sevClass = "sev-degraded";
            else if (h.severity === "CRITICAL") sevClass = "sev-critical";

            const availability10m = h.availability_10m != null
                ? h.availability_10m.toFixed(2)
                : "N/A";

            card.innerHTML = `
                <div class="card-header">
                    <div class="host-main-info">
                        <strong class="host-title">${h.name}</strong>
                        <span class="status-indicator ${statusColor}"></span>
                        <small class="host-addr">(${h.address}${h.port ? ':' + h.port : ''})</small>
                        <br><small>Saúde: ${h.health_score ?? "N/A"}% <span class="severity-indicator ${sevClass}">✚</span></small>
                        <br><small>Disponibilidade: ${availability10m}%</small>
                        <br><small>Último check: ${formatCheckTime(h.last_check)}</small>
                        <br><small>Último SNMP: ${formatCheckTime(h.last_snmp_check)}</small>

                        <div class="metrics-section">
                            <div class="metrics-title">Rede</div>
                            <small>Taxa de sucesso (ping): ${h.sla_rolling_ping ?? "N/A"}%</small><br>
                            <small>Taxa de sucesso (tcp): ${h.sla_rolling_tcp ?? "N/A"}%</small><br>
                            <small>Taxa de sucesso (http): ${h.sla_rolling_http ?? "N/A"}%</small><br>
                            <small>Variação na latência (ping): ${h.jitter_ms_ping ?? "N/A"} ms</small><br>
                            <small>Variação na latência (tcp): ${h.jitter_ms_tcp ?? "N/A"} ms</small><br>
                            <small>Variação na latência (http): ${h.jitter_ms_http ?? "N/A"} ms</small><br>
                            <small>Tendência HTTP: ${trendIcon(h.trend_http)} ${h.trend_http ?? "N/A"}</small><br>
                            <small><b>Causa provável:</b> ${h.probable_cause ?? "Operação normal"}</small>
                        </div>

                        <div class="metrics-section snmp-section">
                            <div class="metrics-title">SNMP</div>
                            <div class="snmp-grid">
                                <div><small class="${metricClass(h.cpu_usage)}">CPU: ${h.cpu_usage ?? "N/A"}%</small></div>
                                <div><small class="${metricClass(h.ram_usage)}">RAM estimada: ${h.ram_usage ?? "N/A"}%</small></div>
                                <div><small class="${metricClass(h.disk_usage, 85, 95)}">Disco: ${h.disk_usage ?? "N/A"}%</small></div>
                                <div><small>Rede total: ${formatBps(h.network_traffic)}</small></div>
                                <div><small>Download (RX): ${formatBps(h.network_in_bps)}</small></div>
                                <div><small>Upload (TX): ${formatBps(h.network_out_bps)}</small></div>
                            </div>
                        </div>
                    </div>

                    <div class="button-group">
                        <button class="history-btn"
                            onclick="toggleHistory('${h.name}')">
                            Histórico
                        </button>
                        <button class="latency-btn"
                            onclick="toggleLatencyChart('${h.name}')">
                            Gráfico de latência
                        </button>
                        <button onclick="toggleSnmpChart('${h.name}')">
                            Gráfico SNMP
                        </button>
                        <button onclick="toggleAvailabilityChartType('${h.name}')">
                            Gráfico de disponibilidade por tipo
                        </button>
                        <button onclick="toggleAvailabilityChart('${h.name}')">
                            Gráfico de disponibilidade geral
                        </button>
                        <button onclick="toggleHeatmap(${h.id}, '${h.name}')">
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
                <div id="snmp-chart-box-${h.name}" class="hidden" style="margin-top: 10px;">
                    <canvas id="snmp-chart-${h.name}" height="120"></canvas>
                </div>
                <div id="availability-chart-type-box-${h.name}" class="hidden">
                    <canvas id="availability-chart-type-${h.name}" height="120"></canvas>
                </div>
                <div id="availability-chart-box-${h.name}" class="hidden">
                    <canvas id="availability-chart-${h.name}" height="120"></canvas>
                </div>
                <div id="history-${h.name}" class="history-box hidden"></div>
                <div id="heatmap-${h.id}" class="heatmap-box" hidden></div>
                
            `;

            div.appendChild(card);

            // ATUALIZA OS DADOS DE PING/TCP
            loadLastResult(h.name);

            // SE O GRÁFICO ESTIVER ABERTO, ATUALIZA ELE TAMBÉM
            const container = document.getElementById("chart-container-" + h.name);
            if (container && !container.classList.contains("hidden")) {
                loadLatencyChart(h.name);
            }
            const availBox = document.getElementById("availability-chart-box-" + h.name);
            if (availBox && !availBox.classList.contains("hidden")) {
                loadAvailability(h.name);
            }
        });
    } catch (err) {
        console.error("Erro ao carregar lista de hosts:", err);
    }
}

async function loadLastResult(name) {
    const box = document.getElementById("result-" + name);

    const res = await fetchWithAuth(`${API}/host/history/${name}`);
    
    if (!res || !res.ok) return;

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
            HTTP ${lastHttp.status_code ?? lastHttp.error ?? ""}: ${lastHttp.latency ?? "N/A"} ms
        </div>` : ''}
    `;
}

async function loadHistory(name) {
    const box = document.getElementById("history-" + name);
    box.innerHTML = "Carregando histórico...";

    try {
        const res = await fetchWithAuth(`${API}/host/history/${name}`);

        if (!res || !res.ok) return;

        const data = await res.json();

        if (!data.checks.length) {
            box.innerHTML = "<small>Sem histórico ainda</small>";
            return;
        }

        box.innerHTML = data.checks.map(c => {
            const statusClass = c.success ? "line-success" : "line-error";
            const statusText = c.success ? "OK" : "FAIL";
            const statusInfo = c.status_code ? `HTTP ${c.status_code ?? c.error ?? ""} — ` : "";
            return `
                <div class="history-line ${statusClass}">
                    <span class="type-badge">[${c.type.toUpperCase()}]</span> 
                    <strong>${statusText}</strong> —
                    ${statusInfo}
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

async function toggleHeatmap(hostId, hostName) {
    const box = document.getElementById(`heatmap-${hostId}`);
    if (!box) return;

    box.hidden = !box.hidden;

    if (box.hidden) return;

    const res = await fetchWithAuth(`${API}/metrics/heatmap/${hostId}`);
    if (!res) return;

    const data = await res.json();

    renderHeatmap(box, data, hostName);
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

async function toggleSnmpChart(name) {
    const box = document.getElementById("snmp-chart-box-" + name);
    if (!box) return;

    if (box.classList.contains("hidden")) {
        box.classList.remove("hidden");
        await loadSnmpChart(name);
    } else {
        box.classList.add("hidden");
    }
}

async function toggleAvailabilityChartType(name) {

    const box = document.getElementById("availability-chart-type-box-" + name);

    if (!box) return;

    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        return;
    }

    box.classList.remove("hidden");
    loadAvailabilityChartType(name);
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

function formatBps(value) {
    if (value === null || value === undefined) return "N/A";

    const bps = Number(value);

    if (bps < 1000) return `${bps.toFixed(2)} bps`;
    if (bps < 1000_000) return `${(bps / 1000).toFixed(2)} Kbps`;
    if (bps < 1000_000_000) return `${(bps / 1000_000).toFixed(2)} Mbps`;

    return `${(bps / 1000_000_000).toFixed(2)} Gbps`;
}

function metricClass(value, warn = 80, critical = 95) {
    if (value === null || value === undefined) return "metric-neutral";
    if (value >= critical) return "metric-critical";
    if (value >= warn) return "metric-warn";
    return "metric-ok";
}

function formatCheckTime(value) {
    if (!value) return "N/A";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "N/A";
    return dt.toLocaleTimeString();
}

function trendIcon(trend) {
    if (trend === "UP") return "↑";
    if (trend === "DOWN") return "↓";
    return "→";
}

async function submitModalEdit() {
    const newName = document.getElementById("modal-name").value;
    const newIp = document.getElementById("modal-ip").value;
    const newPort = document.getElementById("modal-port").value;
    const newHttp = document.getElementById("modal-http-url").value;

    const res = await fetchWithAuth(`${API}/host/update/${currentEditHost}`, {
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
    const chartKey = `latency-${name}`;

    if (charts[chartKey]) {
        charts[chartKey].destroy();
    }
    const res = await fetchWithAuth(`${API}/host/history/${name}`);
    
    if (!res || !res.ok) return;

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

    charts[chartKey] = new Chart(ctx, {
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

async function loadSnmpChart(name) {
    const chartKey = `snmp-${name}`;

    if (charts[chartKey]) {
        charts[chartKey].destroy();
    }

    const res = await fetchWithAuth(`${API}/metrics/snmp/${name}`);
    if (!res || !res.ok) return;

    const data = await res.json();
    const points = data.points || [];

    const labels = points.map(p => new Date(p.timestamp).toLocaleTimeString());
    const cpu = points.map(p => p.cpu);
    const ram = points.map(p => p.ram);
    const disk = points.map(p => p.disk);
    const rx = points.map(p => p.network_in_bps);
    const tx = points.map(p => p.network_out_bps);

    const ctx = document.getElementById("snmp-chart-" + name);
    if (!ctx) return;

    charts[chartKey] = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "CPU (%)",
                    data: cpu,
                    borderColor: "#ef4444",
                    backgroundColor: "#ef444433",
                    yAxisID: "y_percent",
                    tension: 0.3
                },
                {
                    label: "RAM (%)",
                    data: ram,
                    borderColor: "#f59e0b",
                    backgroundColor: "#f59e0b33",
                    yAxisID: "y_percent",
                    tension: 0.3
                },
                {
                    label: "Disco (%)",
                    data: disk,
                    borderColor: "#8b5cf6",
                    backgroundColor: "#8b5cf633",
                    yAxisID: "y_percent",
                    tension: 0.3
                },
                {
                    label: "Download (RX)",
                    data: rx,
                    borderColor: "#2563eb",
                    backgroundColor: "#2563eb33",
                    yAxisID: "y_bps",
                    tension: 0.3
                },
                {
                    label: "Upload (TX)",
                    data: tx,
                    borderColor: "#14b8a6",
                    backgroundColor: "#14b8a633",
                    yAxisID: "y_bps",
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            animation: false,
            scales: {
                y_percent: {
                    type: "linear",
                    position: "left",
                    min: 0,
                    max: 100,
                    title: {
                        display: true,
                        text: "Uso (%)"
                    }
                },
                y_bps: {
                    type: "linear",
                    position: "right",
                    title: {
                        display: true,
                        text: "Tráfego (bps)"
                    },
                    grid: {
                        drawOnChartArea: false
                    }
                }
            }
        }
    });
}

function renderHeatmap(container, payload, hostName) {
    const rows = Array.isArray(payload) ? payload : (payload?.data || []);
    const checkType = Array.isArray(payload) ? "auto" : (payload?.check_type || "auto");

    if (!rows.length) {
        container.innerHTML = "<p>Sem dados para heatmap.</p>";
        return;
    }

    let html = `<h4>Heatmap de Latência - ${hostName} (${String(checkType).toUpperCase()})</h4>`;
    html += `<div class="heatmap-grid">`;

    for (const item of rows.slice(-100)) {
        let cls = "heat-low";
        const latency = item.latency ?? 0;

        if (!item.success) {
            cls = "heat-fail";
        } else if (latency > 300) {
            cls = "heat-high";
        } else if (latency > 100) {
            cls = "heat-medium";
        }

        const title = `${checkType} | Latência: ${item.latency ?? "N/A"} ms | ${item.timestamp}`;
        html += `<div class="heat-cell ${cls}" title="${title}"></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}

async function loadAvailabilityChartType(name) {

    const res = await fetchWithAuth(`${API}/hosts/metrics/availability/type/${name}`);
    if (!res || !res.ok) return;

    const data = await res.json();

    const ping = data.ping || [];
    const tcp  = data.tcp || [];
    const http = data.http || [];

    const base = ping.length ? ping : (tcp.length ? tcp : http);

    const labels = base.map(p =>
        new Date(p.timestamp).toLocaleTimeString()
    );

    const pingValues = ping.map(p => p.availability);
    const tcpValues  = tcp.map(p => p.availability);
    const httpValues = http.map(p => p.availability);

    const ctx = document.getElementById("availability-chart-type-" + name);
    if (!ctx) return;

    const chartKey = `availability-type-${name}`;

    if (charts[chartKey]) {
        charts[chartKey].destroy();
    }

    charts[chartKey] = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Disponibilidade Ping (%)",
                    data: pingValues,
                    borderColor: '#2ecc71',
                    backgroundColor: '#2ecc7133',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: "Disponibilidade TCP (%)",
                    data: tcpValues,
                    borderColor: "#3498db",
                    backgroundColor: '#3498db33',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: "Disponibilidade HTTP (%)",
                    data: httpValues,
                    borderColor: "#f39c12",
                    backgroundColor: '#f39c1233',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            animation: false,
            responsive: true,
            scales: {
                y: { min: 0, max: 100 }
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
    const res = await fetchWithAuth(`${API}/alerts/list`);
    if (!res) return;

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
        const res = await fetchWithAuth(`${API}/host/delete/${name}`, {
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

async function toggleAvailabilityChart(name) {
    const box = document.getElementById(`availability-chart-box-${name}`);
    if (!box) return;

    if (box.classList.contains("hidden")) {
        box.classList.remove("hidden");
        await loadAvailability(name);
    } else {
        box.classList.add("hidden");
    }
}

async function loadAvailability(name) {
    const chartId = `availability-chart-${name}`;
    const ctx = document.getElementById(chartId);
    if (!ctx) return;

    try {
        const response = await fetchWithAuth(`${API}/hosts/metrics/availability/host/${name}`);
        
        if (!response || !response.ok) return;

        const data = await response.json();

        const labels = data.map(p => new Date(p.timestamp).toLocaleTimeString());
        const values = data.map(p => p.availability);

        // Destruir se já existir para evitar bugs visuais ao passar o mouse
        const chartKey = `availability-${name}`;

        if (charts[chartKey]) {
            charts[chartKey].destroy();
        }

        charts[chartKey] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Disponibilidade Host (%)',
                    data: values,
                    borderColor: '#2ecc71',
                    backgroundColor: '#2ecc7133',
                    tension: 0.3,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: { min: 0, max: 100 }
                }
            }
        });
    } catch (err) {
        console.error("Erro ao carregar disponibilidade:", err);
    }
}

async function loadTimeline() {
    const container = document.getElementById("incidentTimeline");
    if (!container) return;

    try {
        const res = await fetchWithAuth(`${API}/incidents/latest`);
        if (!res || !res.ok) return;

        const incidents = await res.json();
        
        container.innerHTML = incidents.map(inc => {
            const isClosed = inc.status === "CLOSED";
            const itemClass = isClosed ? "text-success" : "text-danger";
            const timeStr = new Date(inc.started_time).toLocaleString();
            const durationStr = inc.duration ? `(Duração: ${(inc.duration / 60).toFixed(1)} min)` : "(Ainda aberto)";

            return `
                <div class="timeline-item ${itemClass}">
                    <strong>${inc.host_name}</strong> - 
                    <span>${isClosed ? "RECUPERADO" : "INDISPONÍVEL"}</span>
                    <br>
                    <small>${timeStr} ${durationStr}</small>
                    <p style="margin: 4px 0 0 0; font-size: 0.85em; color: #666;">${inc.reason}</p>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error("Erro ao carregar timeline:", err);
    }
}

async function loadDashboardSummary() {
    const box = document.getElementById("dashboardSummary");
    if (!box) return;

    const res = await fetchWithAuth(`${API}/dashboard/summary`);
    if (!res || !res.ok) return;

    const data = await res.json();

    box.innerHTML = `
        <div class="summary-card">
            <small>Hosts monitorados</small>
            <strong>${data.total_hosts ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>UP</small>
            <strong>${data.up ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Degradados</small>
            <strong>${data.degraded ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>DOWN</small>
            <strong>${data.down ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Incidentes abertos</small>
            <strong>${data.open_incidents ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Saúde média</small>
            <strong>${data.average_health != null ? `${data.average_health}%` : "N/A"}</strong>
        </div>
        <div class="summary-card summary-card-wide">
            <small>Pior latência</small>
            <strong>${data.worst_latency_host ? `${data.worst_latency_host.host} (${data.worst_latency_host.value_ms} ms)` : "N/A"}</strong>
        </div>
        <div class="summary-card summary-card-wide">
            <small>Maior CPU / RAM</small>
            <strong>${data.top_cpu_host ? `${data.top_cpu_host.host} (${data.top_cpu_host.value}%)` : "N/A"} | ${data.top_ram_host ? `${data.top_ram_host.host} (${data.top_ram_host.value}%)` : "N/A"}</strong>
        </div>
    `;
}

function filterHosts() {
    const searchTerm = document.getElementById("searchInput").value.toLowerCase();
    const statusFilter = document.getElementById("statusFilter").value;
    const cards = document.querySelectorAll(".card");

    cards.forEach(card => {
        const hostName = card.querySelector(".host-title").innerText.toLowerCase();
        const hostAddr = card.querySelector(".host-addr").innerText.toLowerCase();
        const indicator = card.querySelector(".status-indicator");
        
        const matchesSearch = hostName.includes(searchTerm) || hostAddr.includes(searchTerm);
        const matchesStatus = statusFilter === "all" || indicator.classList.contains(statusFilter);

        if (matchesSearch && matchesStatus) {
            card.style.display = "block";
        } else {
            card.style.display = "none";
        }
    });
}

// ======================
// Inicialização e Loop
// ======================

setInterval(loadHosts, 5000);
setInterval(loadTimeline, 15000);
setInterval(checkAlerts, 5000);
setInterval(loadDashboardSummary, 10000);

const refreshBtn = document.getElementById("refreshBtn");
if (refreshBtn) {
    refreshBtn.addEventListener("click", loadHosts);
}

window.onload = () => {
    loadDashboardSummary();
    loadHosts();
    loadTimeline();
};

window.onclick = function(event) {
        const modal = document.getElementById("editModal");
        if (event.target === modal) {
            closeModal();
        }
    };

const changePwdBtn = document.getElementById("changePasswordBtn");

if(changePwdBtn){
    changePwdBtn.onclick = () =>{
        document.getElementById("changePwdModal").classList.remove("hidden");
    }
}

function closeChangePwdModal(){
    document.getElementById("changePwdModal").classList.add("hidden");
}

const logoutBtn = document.getElementById("logoutBtn");

if (logoutBtn) {
    logoutBtn.onclick = () => {
        localStorage.removeItem("token");
        window.location.href = "login.html";
    };
};
