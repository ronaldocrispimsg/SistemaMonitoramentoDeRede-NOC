const API = "http://127.0.0.1:8000";
const charts = {};
const MAX_POINTS_PER_SERIES = 100;

if (Notification.permission !== "granted") {
    Notification.requestPermission();
}

const token = localStorage.getItem("token");
const isLoginPage = window.location.pathname.includes("login.html");

// se estiver logado e abrir login → vai pro dashboard
if (token && isLoginPage) {
    window.location.href = "dashboard.html";
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
    if (!token) {
        if (!isLoginPage) {
            localStorage.clear();
            window.location.href = "login.html";
        }
        return null;
    }

    const headers = {
        "Content-Type": "application/json",
        ...options.headers,
        "Authorization": `Bearer ${token}`
    };

    try {
        const response = await fetch(url, { ...options, headers });
        
        if (!response || response.status === 401) {
            if (!isLoginPage) {
                alert("Sessão expirada. Por favor, faça login novamente.");
            }
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
                    window.location.href="dashboard.html";
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
        window.location.href="dashboard.html";
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
        const openStateByHost = {};
        div.querySelectorAll(".card").forEach((card) => {
            const id = card.id || "";
            if (!id.startsWith("card-")) return;
            const hostName = id.slice(5);
            openStateByHost[hostName] = {
                historyOpen: !document.getElementById(`history-${hostName}`)?.classList.contains("hidden"),
                latencyOpen: !document.getElementById(`chart-container-${hostName}`)?.classList.contains("hidden"),
                snmpOpen: !document.getElementById(`snmp-chart-box-${hostName}`)?.classList.contains("hidden"),
                availabilityTypeOpen: !document.getElementById(`availability-chart-type-box-${hostName}`)?.classList.contains("hidden"),
                availabilityOpen: !document.getElementById(`availability-chart-box-${hostName}`)?.classList.contains("hidden")
            };
        });

        const res = await fetchWithAuth(`${API}/hosts/list`);
        if (!res) {
            div.innerHTML = "<p style='color:orange'>⚠ Não foi possível carregar os hosts.</p>";
            return;
        }

        const hosts = await res.json();
        div.innerHTML = "";

        for (const h of hosts) {
            const card = document.createElement("div");
            card.className = "card";
            card.id = `card-${h.name}`;

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
            const snmpConfigured = [
                h.cpu_usage,
                h.ram_usage,
                h.disk_usage,
                h.network_traffic,
                h.network_in_bps,
                h.network_out_bps
            ].some((value) => value !== null && value !== undefined);
            const snmpStatusHtml = !snmpConfigured
                ? `<small class="snmp-tag snmp-tag-off">SNMP: não configurado</small>`
                : "";
            const snmpSectionHtml = snmpConfigured ? `
                        <div class="metrics-section snmp-section">
                            <div class="metrics-title">SNMP</div>
                            <div class="snmp-grid">
                                <div class="snmp-metric-card">
                                    <div class="snmp-metric-head">
                                        <small>CPU</small>
                                        <small class="${metricClass(h.cpu_usage)}">${metricPercent(h.cpu_usage)}</small>
                                    </div>
                                    <div class="metric-bar"><span class="metric-fill ${metricClass(h.cpu_usage)}" style="width:${metricBarWidth(h.cpu_usage)}%"></span></div>
                                </div>
                                <div class="snmp-metric-card">
                                    <div class="snmp-metric-head">
                                        <small>RAM estimada</small>
                                        <small class="${metricClass(h.ram_usage)}">${metricPercent(h.ram_usage)}</small>
                                    </div>
                                    <div class="metric-bar"><span class="metric-fill ${metricClass(h.ram_usage)}" style="width:${metricBarWidth(h.ram_usage)}%"></span></div>
                                </div>
                                <div class="snmp-metric-card">
                                    <div class="snmp-metric-head">
                                        <small>Disco</small>
                                        <small class="${metricClass(h.disk_usage, 85, 95)}">${metricPercent(h.disk_usage)}</small>
                                    </div>
                                    <div class="metric-bar"><span class="metric-fill ${metricClass(h.disk_usage, 85, 95)}" style="width:${metricBarWidth(h.disk_usage)}%"></span></div>
                                </div>
                                <div><small>Rede total: ${formatBps(h.network_traffic)}</small></div>
                                <div><small>Download (RX): ${formatBps(h.network_in_bps)}</small></div>
                                <div><small>Upload (TX): ${formatBps(h.network_out_bps)}</small></div>
                            </div>
                        </div>
            ` : "";
            const snmpButtonHtml = snmpConfigured ? `
                        <button onclick="toggleSnmpChart('${h.name}')">
                            Gráfico SNMP
                        </button>
            ` : "";
            const snmpChartBoxHtml = snmpConfigured ? `
                <div id="snmp-chart-box-${h.name}" class="chart-box hidden" style="margin-top: 10px;">
                    <div class="chart-title">Histórico SNMP</div>
                    <canvas id="snmp-chart-${h.name}" height="120"></canvas>
                </div>
            ` : "";

            card.innerHTML = `
                <div class="card-header">
                    <div class="host-main-info">
                        <div class="host-top-line">
                            <div class="host-title-wrap">
                                <span class="status-indicator ${statusColor}"></span>
                                <strong class="host-title">
                                    ${h.name}
                                    <small class="host-addr">(${h.address}${h.port ? ':' + h.port : ''})</small>
                                </strong>
                            </div>
                        </div>

                        <div class="host-meta-grid">
                            <small>Saúde: ${h.health_score ?? "N/A"}% <span class="severity-indicator ${sevClass}">✚</span></small>
                            <small>Disponibilidade: ${availability10m}%</small>
                            <small>Último check: ${formatCheckTime(h.last_check)}</small>
                            <small>Último SNMP: ${formatCheckTime(h.last_snmp_check)}</small>
                        </div>

                        <div class="metrics-section">
                            <div class="metrics-title">Rede</div>
                            <div class="network-split">
                                <div class="network-col">
                                    <small><b>Taxa de sucesso</b></small>
                                    <small>Ping: ${h.sla_rolling_ping ?? "N/A"}%</small>
                                    <small>TCP: ${h.sla_rolling_tcp ?? "N/A"}%</small>
                                    <small>HTTP: ${h.sla_rolling_http ?? "N/A"}%</small>
                                </div>
                                <div class="network-col">
                                    <small><b>Variação na latência</b></small>
                                    <small>Ping: ${h.jitter_ms_ping ?? "N/A"} ms</small>
                                    <small>TCP: ${h.jitter_ms_tcp ?? "N/A"} ms</small>
                                    <small>HTTP: ${h.jitter_ms_http ?? "N/A"} ms</small>
                                </div>
                            </div>
                            <small>Tendência HTTP: ${trendIcon(h.trend_http)} ${h.trend_http ?? "N/A"}</small><br>
                            <small><b>Causa provável:</b> ${h.probable_cause ?? "Operação normal"}</small>
                            ${snmpStatusHtml}
                        </div>
                        ${snmpSectionHtml}
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
                        ${snmpButtonHtml}
                        <button onclick="toggleAvailabilityChartType('${h.name}')">
                            Gráfico de disponibilidade por tipo
                        </button>
                        <button onclick="toggleAvailabilityChart('${h.name}')">
                            Gráfico de disponibilidade geral
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
                <div id="chart-container-${h.name}" class="chart-box hidden" style="margin-top: 10px;">
                    <div class="chart-title">Latência por tipo</div>
                    <canvas id="chart-${h.name}" height="120"></canvas>
                </div>
                ${snmpChartBoxHtml}
                <div id="availability-chart-type-box-${h.name}" class="chart-box hidden">
                    <div class="chart-title">Disponibilidade por tipo</div>
                    <canvas id="availability-chart-type-${h.name}" height="120"></canvas>
                </div>
                <div id="availability-chart-box-${h.name}" class="chart-box hidden">
                    <div class="chart-title">Disponibilidade geral</div>
                    <canvas id="availability-chart-${h.name}" height="120"></canvas>
                </div>
                <div id="history-${h.name}" class="history-box hidden"></div>
                
            `;

            div.appendChild(card);

            // ATUALIZA OS DADOS DE PING/TCP
            loadLastResult(h.name);

            // Restaura estado aberto para não "reiniciar" visual a cada refresh.
            const state = openStateByHost[h.name];
            if (state?.historyOpen) {
                const historyBox = document.getElementById(`history-${h.name}`);
                if (historyBox) {
                    historyBox.classList.remove("hidden");
                    loadHistory(h.name);
                }
            }

            if (state?.latencyOpen) {
                const container = document.getElementById("chart-container-" + h.name);
                if (container) {
                    container.classList.remove("hidden");
                    loadLatencyChart(h.name);
                }
            }

            if (state?.snmpOpen) {
                const snmpBox = document.getElementById("snmp-chart-box-" + h.name);
                if (snmpBox) {
                    snmpBox.classList.remove("hidden");
                    loadSnmpChart(h.name);
                }
            }

            if (state?.availabilityTypeOpen) {
                const typeBox = document.getElementById("availability-chart-type-box-" + h.name);
                if (typeBox) {
                    typeBox.classList.remove("hidden");
                    loadAvailabilityChartType(h.name);
                }
            }

            if (state?.availabilityOpen) {
                const availBox = document.getElementById("availability-chart-box-" + h.name);
                if (availBox) {
                    availBox.classList.remove("hidden");
                    loadAvailability(h.name);
                }
            }

        }

        // Reaplica filtro após rerender para manter UX estável.
        const searchInput = document.getElementById("searchInput");
        const statusFilter = document.getElementById("statusFilter");
        if (searchInput?.value || (statusFilter && statusFilter.value !== "all")) {
            filterHosts();
        }
    } catch (err) {
        console.error("Erro ao carregar lista de hosts:", err);
    }
}

async function loadHostsQuick() {
    try {
        const div = document.getElementById("hosts");
        if (!div) return;
        const hasCards = div.querySelectorAll(".card").length > 0;
        if (!hasCards) {
            await loadHosts();
            return;
        }

        const res = await fetchWithAuth(`${API}/hosts/list`);
        if (!res || !res.ok) return;
        const hosts = await res.json();

        for (const h of hosts) {
            const resultBox = document.getElementById(`result-${h.name}`);
            if (resultBox) {
                loadLastResult(h.name);
            }

            const availBox = document.getElementById("availability-chart-box-" + h.name);
            if (availBox && !availBox.classList.contains("hidden")) {
                loadAvailability(h.name);
            }

            const latencyBox = document.getElementById("chart-container-" + h.name);
            if (latencyBox && !latencyBox.classList.contains("hidden")) {
                loadLatencyChart(h.name);
            }

            const snmpBox = document.getElementById("snmp-chart-box-" + h.name);
            if (snmpBox && !snmpBox.classList.contains("hidden")) {
                loadSnmpChart(h.name);
            }
        }
    } catch (err) {
        console.error("Erro ao atualizar dados dos hosts:", err);
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

    const pingLikelyFirewallBlocked =
        !!lastPing &&
        !lastPing.success &&
        ((!!lastTcp && lastTcp.success) || (!!lastHttp && lastHttp.success));

    const pingDot = pingLikelyFirewallBlocked
        ? "bg-secondary"
        : (lastPing?.success ? "bg-success" : "bg-danger");
    const tcpDot  = lastTcp?.success ? "bg-success" : "bg-danger";
    const httpDot = lastHttp?.success ? "bg-success" : "bg-danger";

    const pingLatencyText = pingLikelyFirewallBlocked
        ? "N/A (Bloqueado pelo firewall)"
        : `${lastPing?.latency ?? "N/A"} ms`;

    box.innerHTML = `
        <div>
            <span class="status-indicator ${pingDot}"></span>
            Ping: ${pingLatencyText}
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
                    <small>${formatApiTime(c.timestamp)}</small>
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

function metricPercent(value) {
    if (value === null || value === undefined) return "N/A";
    const n = Number(value);
    if (Number.isNaN(n)) return "N/A";
    return `${n.toFixed(1)}%`;
}

function metricBarWidth(value) {
    if (value === null || value === undefined) return 0;
    const n = Number(value);
    if (Number.isNaN(n)) return 0;
    return Math.max(0, Math.min(100, n));
}

function takeLast(items, limit = MAX_POINTS_PER_SERIES) {
    if (!Array.isArray(items)) return [];
    if (items.length <= limit) return items;
    return items.slice(items.length - limit);
}

function chartCommonOptions(yMin = null, yMax = null, yLabel = "") {
    const yScale = {
        title: {
            display: !!yLabel,
            text: yLabel
        }
    };
    if (yMin !== null && yMin !== undefined) yScale.min = yMin;
    if (yMax !== null && yMax !== undefined) yScale.max = yMax;

    return {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            y: yScale,
            x: {}
        }
    };
}

function showChartEmpty(boxId, canvasId, message) {
    const box = document.getElementById(boxId);
    const canvas = document.getElementById(canvasId);
    if (!box || !canvas) return;

    canvas.style.display = "none";
    let empty = box.querySelector(".chart-empty");
    if (!empty) {
        empty = document.createElement("div");
        empty.className = "chart-empty";
        box.appendChild(empty);
    }
    empty.textContent = message;
}

function clearChartEmpty(boxId, canvasId) {
    const box = document.getElementById(boxId);
    const canvas = document.getElementById(canvasId);
    if (!box || !canvas) return;

    const empty = box.querySelector(".chart-empty");
    if (empty) empty.remove();
    canvas.style.display = "block";
}

function getDatasetHiddenMap(chart) {
    const map = {};
    (chart.data?.datasets || []).forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        map[ds.label] = meta?.hidden === true || ds.hidden === true;
    });
    return map;
}

function updateOrCreateChart(chartKey, canvasEl, config) {
    const current = charts[chartKey];

    if (!current) {
        charts[chartKey] = new Chart(canvasEl, config);
        return;
    }

    if (current.canvas !== canvasEl) {
        current.destroy();
        charts[chartKey] = new Chart(canvasEl, config);
        return;
    }

    const hiddenMap = getDatasetHiddenMap(current);
    (config.data.datasets || []).forEach((ds) => {
        if (Object.prototype.hasOwnProperty.call(hiddenMap, ds.label)) {
            ds.hidden = hiddenMap[ds.label];
        }
    });

    current.config.type = config.type;
    current.config.plugins = config.plugins || [];
    current.data.labels = config.data.labels || [];
    current.data.datasets = config.data.datasets || [];
    current.options = config.options || {};
    current.update("none");
}

function parseApiDate(value) {
    if (!value) return null;

    if (typeof value === "string") {
        const hasTimezone = /[zZ]|[+\-]\d{2}:\d{2}$/.test(value);
        const normalized = hasTimezone ? value : `${value}Z`;
        const dt = new Date(normalized);
        if (!Number.isNaN(dt.getTime())) return dt;
    }

    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return null;
    return dt;
}

function formatApiTime(value) {
    const dt = parseApiDate(value);
    if (!dt) return "N/A";
    return dt.toLocaleTimeString("pt-BR");
}

function formatApiDateTime(value) {
    const dt = parseApiDate(value);
    if (!dt) return "N/A";
    return dt.toLocaleString("pt-BR");
}

function formatCheckTime(value) {
    return formatApiTime(value);
}

function trendIcon(trend) {
    if (trend === "UP") return "↑";
    if (trend === "DOWN") return "↓";
    return "→";
}

function formatMetric(value, suffix = "", digits = 2) {
    if (value === null || value === undefined) return "N/A";
    const num = Number(value);
    if (Number.isNaN(num)) return "N/A";
    return `${num.toFixed(digits)}${suffix}`;
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
    const res = await fetchWithAuth(`${API}/host/history/${name}`);
    
    if (!res || !res.ok) return;

    const data = await res.json();

    const ping = takeLast(data.checks.filter(c => c.type === "ping"));
    const tcp  = takeLast(data.checks.filter(c => c.type === "tcp"));
    const http = takeLast(data.checks.filter(c => c.type === "http"));

    const labels = ping.map(c => formatApiTime(c.timestamp));

    const pingData = ping.map(c => c.latency);
    const tcpData  = tcp.map(c => c.latency);
    const httpData = http.map(c => c.latency);
    const ctx = document.getElementById("chart-" + name);
    const containerId = "chart-container-" + name;
    const canvasId = "chart-" + name;

    if (!ctx) return;
    if (!ping.length && !tcp.length && !http.length) {
        showChartEmpty(containerId, canvasId, "Sem dados de latência para este host.");
        return;
    }
    clearChartEmpty(containerId, canvasId);

    updateOrCreateChart(chartKey, ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Ping",
                    data: pingData,
                    borderColor: "#22c55e",
                    backgroundColor: "#22c55e33",
                    tension: 0.3
                },
                {
                    label: "TCP",
                    data: tcpData,
                    borderColor: "#3b82f6",
                    backgroundColor: "#3b82f633",
                    tension: 0.3
                }
                ,{
                    label: "HTTP",
                    data: httpData,
                    borderColor: "#f59e0b",
                    backgroundColor: "#f59e0b33",
                    tension: 0.3
                }
            ]
        },
        options: chartCommonOptions(null, null, "Latência (ms)")
    });
}

async function loadSnmpChart(name) {
    const chartKey = `snmp-${name}`;

    const res = await fetchWithAuth(`${API}/metrics/snmp/${name}`);
    if (!res || !res.ok) return;

    const data = await res.json();
    const points = takeLast(data.points || []);
    const boxId = "snmp-chart-box-" + name;
    const canvasId = "snmp-chart-" + name;

    if (!points.length) {
        showChartEmpty(boxId, canvasId, "Sem histórico SNMP para este host.");
        return;
    }
    clearChartEmpty(boxId, canvasId);

    const labels = points.map(p => formatApiTime(p.timestamp));
    const cpu = points.map(p => p.cpu);
    const ram = points.map(p => p.ram);
    const disk = points.map(p => p.disk);
    const rx = points.map(p => p.network_in_bps);
    const tx = points.map(p => p.network_out_bps);

    const ctx = document.getElementById("snmp-chart-" + name);
    if (!ctx) return;

    updateOrCreateChart(chartKey, ctx, {
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
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            if (ctx.dataset.yAxisID === "y_percent") {
                                const value = Number(ctx.parsed.y);
                                return `${ctx.dataset.label}: ${Number.isFinite(value) ? value.toFixed(2) : "N/A"}%`;
                            }
                            return `${ctx.dataset.label}: ${formatBps(ctx.parsed.y)}`;
                        }
                    }
                }
            },
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
                    display: false,
                    grid: {
                        drawOnChartArea: false
                    }
                }
            }
        }
    });
}

async function loadAvailabilityChartType(name) {

    const res = await fetchWithAuth(`${API}/hosts/metrics/availability/type/${name}`);
    if (!res || !res.ok) return;

    const data = await res.json();

    const ping = takeLast(data.ping || []);
    const tcp  = takeLast(data.tcp || []);
    const http = takeLast(data.http || []);

    const base = ping.length ? ping : (tcp.length ? tcp : http);

    const labels = base.map(p => formatApiTime(p.timestamp));

    const pingValues = ping.map(p => p.availability);
    const tcpValues  = tcp.map(p => p.availability);
    const httpValues = http.map(p => p.availability);

    const ctx = document.getElementById("availability-chart-type-" + name);
    if (!ctx) return;

    const chartKey = `availability-type-${name}`;

    if (!labels.length) {
        showChartEmpty(
            "availability-chart-type-box-" + name,
            "availability-chart-type-" + name,
            "Sem dados de disponibilidade por tipo."
        );
        return;
    }
    clearChartEmpty("availability-chart-type-box-" + name, "availability-chart-type-" + name);

    updateOrCreateChart(chartKey, ctx, {
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
        options: chartCommonOptions(null, null, "Disponibilidade (%)")
    });
}

function formatStatusLabel(status) {
    const normalized = String(status || "").toUpperCase();
    if (normalized === "UP" || normalized === "UP_RECOVERED") return "Online";
    if (normalized === "DOWN") return "Offline";
    if (normalized === "DEGRADED") return "Degradado";
    if (normalized === "CRITICAL") return "Crítico";
    if (normalized === "UNKNOWN") return "Desconhecido";
    return status ?? "Desconhecido";
}

function alertSeverityClass(severity) {
    const normalized = String(severity || "").toUpperCase();
    if (normalized === "HEALTHY") return "alert-sev-healthy";
    if (normalized === "WARNING") return "alert-sev-warning";
    if (normalized === "DEGRADED") return "alert-sev-degraded";
    if (normalized === "CRITICAL") return "alert-sev-critical";
    return "alert-sev-unknown";
}

function showAlertCard(alert) {
    const box = document.getElementById("alert-container");
    if (!box) return;

    const card = document.createElement("div");
    card.className = `alert-card ${alertSeverityClass(alert.severity)}`;

    const fromValue = alert.old_status ?? "N/A";
    const toValue = alert.new_status ?? "N/A";
    const fromLabel = formatStatusLabel(fromValue);
    const toLabel = formatStatusLabel(toValue);
    const transitionText = `${fromLabel} → ${toLabel}`;
    const rawTransitionText = `${fromValue} → ${toValue}`;
    const showRawTransition = String(fromValue).includes(".") || String(toValue).includes(".") || String(alert.alert_type || "").toUpperCase() === "DNS_CHANGE";

    card.innerHTML = `
        <div class="alert-header">
            <strong>${alert.host_name}</strong>
        </div>
        <div class="alert-subtitle">
            ${showRawTransition ? rawTransitionText : transitionText}
        </div>
        <div class="alert-subtitle">
            ${alert.host_address}${alert.host_port ? `:${alert.host_port}` : ""} | ${alert.alert_type ?? "STATUS_CHANGE"}
        </div>
        <div class="alert-subtitle">
            ${formatApiDateTime(alert.timestamp)}
        </div>
    `;

    box.appendChild(card);

    setTimeout(() => {
        card.remove();
    }, 12000);
}

function triggerAllFrontendAlerts() {
    const nowIso = new Date().toISOString();
    const samples = [
        {
            host_name: "youtube",
            host_address: "youtube.com",
            host_port: 443,
            alert_type: "DNS_CHANGE",
            old_status: "172.217.29.174",
            new_status: "['172.217.30.142']",
            severity: "HEALTHY",
            timestamp: nowIso
        },
        {
            host_name: "ifnmg",
            host_address: "ifnmg.edu.br",
            host_port: 443,
            alert_type: "DNS_TTL_LOW",
            old_status: "ttl",
            new_status: "45",
            severity: "WARNING",
            timestamp: nowIso
        },
        {
            host_name: "google",
            host_address: "google.com",
            host_port: 443,
            alert_type: "STATUS_CHANGE",
            old_status: "UP",
            new_status: "DEGRADED",
            severity: "DEGRADED",
            timestamp: nowIso
        },
        {
            host_name: "Meu PC",
            host_address: "192.168.0.10",
            host_port: 80,
            alert_type: "HEALTH_CRITICAL",
            old_status: "DEGRADED",
            new_status: "DOWN",
            severity: "CRITICAL",
            timestamp: nowIso
        },
        {
            host_name: "gateway",
            host_address: "10.0.0.1",
            host_port: null,
            alert_type: "UP_RECOVERED",
            old_status: "DOWN",
            new_status: "UP_RECOVERED",
            severity: "HEALTHY",
            timestamp: nowIso
        }
    ];

    samples.forEach((sample, idx) => {
        setTimeout(() => showAlertCard(sample), idx * 450);
    });
}

window.triggerAllFrontendAlerts = triggerAllFrontendAlerts;

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

        const limited = takeLast(data);
        const labels = limited.map(p => formatApiTime(p.timestamp));
        const values = limited.map(p => p.availability);

        const chartKey = `availability-${name}`;

        if (!labels.length) {
            showChartEmpty(
                "availability-chart-box-" + name,
                "availability-chart-" + name,
                "Sem dados de disponibilidade."
            );
            return;
        }
        clearChartEmpty("availability-chart-box-" + name, "availability-chart-" + name);

        updateOrCreateChart(chartKey, ctx, {
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
                ...chartCommonOptions(null, null, "Disponibilidade (%)")
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
            const timeStr = formatApiDateTime(inc.started_time);
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
            <small>Online</small>
            <strong>${data.up ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Degradados</small>
            <strong>${data.degraded ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Offline</small>
            <strong>${data.down ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Incidentes abertos</small>
            <strong>${data.open_incidents ?? 0}</strong>
        </div>
        <div class="summary-card">
            <small>Incidentes fechados</small>
            <strong>${data.closed_incidents ?? 0}</strong>
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

if (!isLoginPage) {
    setInterval(loadHostsQuick, 5000);
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
}

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
