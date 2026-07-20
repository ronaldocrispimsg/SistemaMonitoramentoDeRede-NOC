const API = (window.location.protocol === "file:" || window.location.port === "5500" || window.location.port === "3000")
    ? "http://127.0.0.1:8000"
    : "/api";
const charts = {};
const MAX_POINTS_PER_SERIES = 100;
let authRedirectScheduled = false;
let lastUserInteractionAt = 0;

//

const POLLING_INTERVALS = {
    visible: { lightMs: 5000, heavyMs: 20000 },
    hidden: { lightMs: 30000, heavyMs: 120000 }
};

const pollingState = {
    lightTimer: null,
    heavyTimer: null,
    runningTasks: new Set()
};

const recentAlertCache = new Map();
const ALERT_DEDUP_WINDOW_MS = 45000;
const SEEN_ALERTS_STORAGE_KEY = "netspot_seen_alerts_v1";
const MAX_SEEN_ALERTS = 200;
const INCIDENT_TYPE_LABELS = {
    DNS_FAILURE: "Falha DNS",
    SERVICE_DEGRADED: "Serviço degradado",
    SERVICE_DOWN: "Serviço indisponível",
    GENERIC: "Incidente operacional"
};
const ALERT_TYPE_LABELS = {
    DNS_TTL_LOW: "TTL DNS baixo",
    DNS_CHANGE: "Mudança de DNS",
    HEALTH_CRITICAL: "Saúde crítica",
    STATUS_CHANGE: "Mudança de status",
    UP_RECOVERED: "Recuperação",
    DNS_FAILURE: "Falha DNS",
    SERVICE_DOWN: "Serviço indisponível",
    SERVICE_DEGRADED: "Serviço degradado"
};

function loadSeenAlertKeys() {
    try {
        const raw = localStorage.getItem(SEEN_ALERTS_STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.filter((v) => typeof v === "string").slice(-MAX_SEEN_ALERTS);
    } catch (err) {
        return [];
    }
}

let seenAlertKeysList = loadSeenAlertKeys();
const seenAlertKeysSet = new Set(seenAlertKeysList);
let seenAlertsBootstrapped = seenAlertKeysList.length > 0;

function persistSeenAlertKeys() {
    try {
        localStorage.setItem(SEEN_ALERTS_STORAGE_KEY, JSON.stringify(seenAlertKeysList.slice(-MAX_SEEN_ALERTS)));
    } catch (err) {
        // Ignora falha de storage para não quebrar o fluxo de alertas.
    }
}

function rememberSeenAlert(alertKey) {
    if (seenAlertKeysSet.has(alertKey)) return;
    seenAlertKeysSet.add(alertKey);
    seenAlertKeysList.push(alertKey);
    if (seenAlertKeysList.length > MAX_SEEN_ALERTS) {
        const overflow = seenAlertKeysList.length - MAX_SEEN_ALERTS;
        const removed = seenAlertKeysList.splice(0, overflow);
        removed.forEach((k) => seenAlertKeysSet.delete(k));
    }
}

if (Notification.permission !== "granted") {
    Notification.requestPermission();
}

const token = localStorage.getItem("token");
const isLoginPage = window.location.pathname.includes("login.html");

function ensureToastContainer() {
    let container = document.getElementById("toastContainer");
    if (!container) {
        container = document.createElement("div");
        container.id = "toastContainer";
        container.className = "toast-container";
        document.body.appendChild(container);
    }
    return container;
}

function showToast(type, message, duration = 3200) {
    const container = ensureToastContainer();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type || "info"}`;
    toast.textContent = message;
    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("show"));

    setTimeout(() => {
        toast.classList.remove("show");
        toast.classList.add("hide");
        setTimeout(() => toast.remove(), 240);
    }, duration);
}

function setInlineState(element, message, type = "info") {
    if (!element) return;
    element.className = `ui-state ui-state-${type}`;
    element.textContent = message;
}

function touchUserInteraction() {
    lastUserInteractionAt = Date.now();
}

function isUserActivelyInteracting(windowMs = 3500) {
    return Date.now() - lastUserInteractionAt < windowMs;
}

function hasBlockingUiOpen() {
    const openModal = document.querySelector(".modal:not(.hidden)");
    return Boolean(openModal);
}

function shouldDeferHeavyRefresh() {
    return hasBlockingUiOpen() || isUserActivelyInteracting();
}

async function runTaskOnce(taskName, taskFn) {
    if (pollingState.runningTasks.has(taskName)) return;
    pollingState.runningTasks.add(taskName);
    try {
        await taskFn();
    } finally {
        pollingState.runningTasks.delete(taskName);
    }
}

async function runLightRefresh() {
    await Promise.all([
        runTaskOnce("hosts-quick", loadHostsQuick),
        runTaskOnce("alerts", checkAlerts),
        runTaskOnce("summary", loadDashboardSummary)
    ]);
}

async function runHeavyRefresh() {
    if (shouldDeferHeavyRefresh()) return;
    await Promise.all([
        runTaskOnce("hosts-full", loadHosts),
        runTaskOnce("trash", loadTrashHosts)
    ]);
}

function clearDashboardPolling() {
    if (pollingState.lightTimer) {
        clearInterval(pollingState.lightTimer);
        pollingState.lightTimer = null;
    }
    if (pollingState.heavyTimer) {
        clearInterval(pollingState.heavyTimer);
        pollingState.heavyTimer = null;
    }
}

function startDashboardPolling() {
    if (isLoginPage) return;
    clearDashboardPolling();

    const visibilityMode = document.hidden ? "hidden" : "visible";
    const config = POLLING_INTERVALS[visibilityMode];

    pollingState.lightTimer = setInterval(runLightRefresh, config.lightMs);
    pollingState.heavyTimer = setInterval(runHeavyRefresh, config.heavyMs);
}

function stopDashboardPolling() {
    clearDashboardPolling();
}

function resumeDashboardPolling() {
    startDashboardPolling();
}

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
            if (!isLoginPage && !authRedirectScheduled) {
                authRedirectScheduled = true;
                showToast("warning", "Sessão expirada. Faça login novamente.", 1400);
                localStorage.clear();
                setTimeout(() => {
                    window.location.href = "login.html";
                }, 900);
            } else if (!isLoginPage) {
                localStorage.clear();
                window.location.href = "login.html";
            }
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
        const submitBtn = loginForm.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn ? submitBtn.textContent : "Entrar";

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "Entrando...";
            submitBtn.classList.add("is-loading");
        }

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
                    showToast("info", "Troca de senha obrigatória para continuar.");
                    document.getElementById("pwdModal").classList.remove("hidden");
                } else {
                    showToast("success", "Login realizado com sucesso.");
                    setTimeout(() => {
                        window.location.href = "dashboard.html";
                    }, 600);
                }
            } else {
                const detail = String(data.detail || "Credenciais inválidas");
                if (detail.toLowerCase().includes("bloquead")) {
                    showToast("error", detail);
                } else {
                    showToast("error", "Credenciais inválidas.");
                }
            }
        } catch (err) {
            showToast("error", "Não foi possível conectar ao servidor.");
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalBtnText;
                submitBtn.classList.remove("is-loading");
            }
        }
    };
}

async function submitChangePassword(){

    const newPwd = document.getElementById("new-pwd").value;
    const confirmPwd = document.getElementById("confirm-pwd").value;

    if(newPwd !== confirmPwd) {
        showToast("warning", "As senhas não coincidem.");
        return;
    }

    const token = localStorage.getItem("token");

    try {
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
            showToast("success", "Senha alterada com sucesso.");
            setTimeout(() => {
                window.location.href = "dashboard.html";
            }, 700);
        }else{
            showToast("error", "Erro ao alterar senha.");
        }
    } catch (error) {
        showToast("error", "Não foi possível conectar ao servidor.");
    }
}

async function changePassword(){
    const currentPwd = document.getElementById("current-pwd").value;
    const newPwd = document.getElementById("new-pwd").value;
    const confirmPwd = document.getElementById("confirm-pwd").value;

    if (newPwd !== confirmPwd) {
        showToast("warning", "As senhas não coincidem.");
        return;
    }
    if (newPwd.length < 6) {
        showToast("warning", "Senha muito curta.");
        return;
    }

    const token = localStorage.getItem("token");

    try {
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
            showToast("error", "Conta bloqueada. Contate o administrador.");
            return;
        }

        if(res.ok){
            showToast("success", "Senha alterada com sucesso.");
            localStorage.removeItem("token");
            setTimeout(() => {
                window.location.href = "login.html";
            }, 700);
        }else{
            showToast("error", "Erro ao alterar senha.");
        }
    } catch (error) {
        showToast("error", "Não foi possível conectar ao servidor.");
    }

}
// ======================
// Cadastrar Host (POST)
// ======================
const hostForm = document.getElementById("hostForm");
const portsContainer = document.getElementById("portsContainer");
const addPortBtn = document.getElementById("addPortBtn");

function addPortInput(container, value = "", removable = false, placeholder = "Porta") {
    if (!container) return;
    const row = document.createElement("div");
    row.className = "port-input-row";

    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = "65535";
    input.placeholder = placeholder;
    input.className = "port-input";
    input.value = value === null || value === undefined ? "" : String(value);
    row.appendChild(input);

    if (removable) {
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-port-btn";
        removeBtn.title = "Remover porta";
        removeBtn.textContent = "−";
        removeBtn.addEventListener("click", () => row.remove());
        row.appendChild(removeBtn);
    }

    container.appendChild(row);
}

function resetCreatePorts() {
    if (!portsContainer) return;
    portsContainer.innerHTML = "";
    addPortInput(portsContainer, "", false, "Porta");
    addPortInput(portsContainer, "", false, "Porta");
    addPortInput(portsContainer, "", false, "Porta");
}

function setModalPorts(ports) {
    const container = document.getElementById("modalPortsContainer");
    if (!container) return;
    container.innerHTML = "";

    const normalized = Array.isArray(ports)
        ? ports
            .map((p) => Number(p))
            .filter((p) => Number.isInteger(p) && p >= 1 && p <= 65535)
        : [];

    if (normalized.length === 0) {
        addPortInput(container, "", false, "Porta");
        addPortInput(container, "", false, "Porta");
        addPortInput(container, "", false, "Porta");
        return;
    }

    while (normalized.length < 3) normalized.push("");
    normalized.forEach((value, index) => addPortInput(container, value, index >= 3, "Porta"));
}

function collectPorts(container) {
    if (!container) return [];
    const raw = Array.from(container.querySelectorAll(".port-input"))
        .map((input) => String(input.value || "").trim())
        .filter((value) => value !== "");

    const seen = new Set();
    const valid = [];
    for (const value of raw) {
        const port = Number(value);
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
            throw new Error(`Porta inválida: ${value}`);
        }
        if (seen.has(port)) continue;
        seen.add(port);
        valid.push(port);
    }
    valid.sort((a, b) => a - b);
    return valid;
}

function parseHostPorts(host) {
    if (Array.isArray(host?.ports)) {
        return host.ports
            .map((p) => Number(p))
            .filter((p) => Number.isInteger(p) && p >= 1 && p <= 65535);
    }

    if (typeof host?.tcp_ports === "string" && host.tcp_ports.trim()) {
        try {
            const parsed = JSON.parse(host.tcp_ports);
            if (Array.isArray(parsed)) {
                return parsed
                    .map((p) => Number(p))
                    .filter((p) => Number.isInteger(p) && p >= 1 && p <= 65535);
            }
        } catch (_err) {}
    }

    const singlePort = Number(host?.port);
    if (Number.isInteger(singlePort) && singlePort >= 1 && singlePort <= 65535) {
        return [singlePort];
    }

    return [];
}

if (addPortBtn && portsContainer) {
    addPortBtn.addEventListener("click", () => addPortInput(portsContainer, "", true));
    resetCreatePorts();
}

if (hostForm) {
    hostForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const nameInput = document.getElementById("name");
        const addressInput = document.getElementById("address");
        const httpUrlInput = document.getElementById("http_url");
        const httpEnabledInput = document.getElementById("http_enabled");
        const snmpEnabledInput = document.getElementById("snmp_enabled");
        let ports = [];
        try {
            ports = collectPorts(portsContainer);
        } catch (err) {
            showToast("error", err.message || "Lista de portas inválida.");
            return;
        }

        const data = {
            name: nameInput.value,
            address: addressInput.value,
            ports,
            port: ports.length ? ports[0] : null,
            url: httpUrlInput.value || null,
            http_url: httpUrlInput.value || null,
            http_enabled: !!httpEnabledInput?.checked,
            snmp_enabled: !!snmpEnabledInput?.checked
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
                httpUrlInput.value = "";
                if (httpEnabledInput) httpEnabledInput.checked = true;
                if (snmpEnabledInput) snmpEnabledInput.checked = false;
                resetCreatePorts();
                loadHosts();
                loadTrashHosts();
                showToast("success", "Host cadastrado com sucesso.");
            } else {
                const errorData = await response.json();
                showToast("error", "Erro ao cadastrar: " + (errorData.detail || "Erro desconhecido"));
            }
        } catch (err) {
            console.error("Erro na requisição:", err);
            showToast("error", "Não foi possível conectar ao servidor.");
        }
    });
}

let discoveredLanHosts = [];

function renderDiscoveredLanHosts() {
    const listBox = document.getElementById("networkDiscoveryList");
    const infoBox = document.getElementById("networkDiscoveryInfo");
    if (!listBox || !infoBox) return;

    if (!Array.isArray(discoveredLanHosts) || discoveredLanHosts.length === 0) {
        infoBox.textContent = "";
        listBox.innerHTML = "<small>Nenhum host encontrado.</small>";
        return;
    }

    const selectableCount = discoveredLanHosts.filter((h) => !h.already_exists).length;
    infoBox.textContent = `${discoveredLanHosts.length} host(s) encontrado(s) • ${selectableCount} disponível(is) para importação`;
    listBox.innerHTML = discoveredLanHosts.map((host) => {
        const disabled = host.already_exists ? "disabled" : "";
        const checked = host.already_exists ? "" : "checked";
        const hostnameText = host.hostname ? ` • ${host.hostname}` : "";
        return `
            <label class="network-discovery-item">
                <div class="network-discovery-meta">
                    <strong>${host.name}</strong>
                    <small>${host.address}${hostnameText}</small>
                </div>
                <div>
                    ${host.already_exists ? '<span class="network-exists-badge">já cadastrado</span>' : ""}
                    <input type="checkbox" class="discover-host-check" data-id="${host.id}" ${disabled} ${checked}>
                </div>
            </label>
        `;
    }).join("");
}

async function discoverNetworkHosts() {
    const subnetInput = document.getElementById("discoverSubnet");
    const discoverBtn = document.getElementById("discoverBtn");
    const resultBox = document.getElementById("networkImportResult");
    if (!subnetInput || !discoverBtn) return;

    const subnet = String(subnetInput.value || "").trim();
    if (!subnet) {
        if (resultBox) setInlineState(resultBox, "Informe uma subnet no formato CIDR.", "warning");
        showToast("warning", "Informe uma subnet no formato CIDR.");
        return;
    }

    discoverBtn.disabled = true;
    discoverBtn.textContent = "Descobrindo...";
    if (resultBox) setInlineState(resultBox, "Executando descoberta...", "info");

    try {
        const res = await fetchWithAuth(`${API}/network/discover`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ subnet })
        });
        if (!res) return;

        const data = await res.json();
        if (!res.ok) {
            if (resultBox) setInlineState(resultBox, data.detail || "Erro na descoberta de rede.", "error");
            showToast("error", data.detail || "Erro na descoberta de rede.");
            return;
        }

        discoveredLanHosts = Array.isArray(data.hosts) ? data.hosts : [];
        renderDiscoveredLanHosts();
        if (resultBox) setInlineState(resultBox, "Descoberta concluída. Selecione os hosts para importar.", "success");
        showToast("success", `Descoberta concluída: ${data.found ?? discoveredLanHosts.length} host(s).`);
    } catch (err) {
        console.error("Erro na descoberta de rede:", err);
        if (resultBox) setInlineState(resultBox, "Falha ao executar descoberta de rede.", "error");
        showToast("error", "Falha ao executar descoberta de rede.");
    } finally {
        discoverBtn.disabled = false;
        discoverBtn.textContent = "Descobrir rede";
    }
}

function isValidIpv4Cidr(value) {
    const text = String(value || "").trim();
    const [ip, prefix] = text.split("/");
    if (!ip || prefix === undefined || text.split("/").length !== 2) return false;
    const prefixNum = Number(prefix);
    if (!Number.isInteger(prefixNum) || prefixNum < 0 || prefixNum > 32) return false;
    const octets = ip.split(".");
    if (octets.length !== 4) return false;
    return octets.every((octet) => {
        if (!/^\d{1,3}$/.test(octet)) return false;
        const n = Number(octet);
        return n >= 0 && n <= 255;
    });
}

async function preloadDiscoverySubnet() {
    const subnetInput = document.getElementById("discoverSubnet");
    if (!subnetInput) return;
    if (String(subnetInput.value || "").trim()) return;

    try {
        const res = await fetchWithAuth(`${API}/network/default-subnet`);
        if (!res || !res.ok) {
            console.warn("Não foi possível detectar subnet automática.");
            return;
        }
        const data = await res.json();
        const subnet = String(data?.subnet || "").trim();
        if (isValidIpv4Cidr(subnet) && !String(subnetInput.value || "").trim()) {
            subnetInput.value = subnet;
        }
    } catch (err) {
        console.warn("Falha no preload da subnet automática:", err);
    }
}

async function importSelectedLanHosts() {
    const checks = Array.from(document.querySelectorAll(".discover-host-check:checked"));
    const selected = checks
        .map((check) => {
            const id = check.getAttribute("data-id");
            return discoveredLanHosts.find((h) => h.id === id);
        })
        .filter(Boolean)
        .map((host) => ({
            name: host.name,
            address: host.address
        }));

    if (!selected.length) {
        showToast("warning", "Selecione ao menos um host para importar.");
        return;
    }

    const importBtn = document.getElementById("importSelectedBtn");
    const resultBox = document.getElementById("networkImportResult");
    if (importBtn) {
        importBtn.disabled = true;
        importBtn.textContent = "Importando...";
    }

    try {
        const res = await fetchWithAuth(`${API}/network/import`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hosts: selected })
        });
        if (!res) return;

        const data = await res.json();
        if (!res.ok) {
            showToast("error", data.detail || "Erro ao importar hosts selecionados.");
            return;
        }

        if (resultBox) {
            setInlineState(
                resultBox,
                `Solicitados: ${data.requested} • Criados: ${data.created} • Ignorados: ${data.skipped}`,
                "success"
            );
        }

        const createdAddresses = new Set(
            (Array.isArray(data.results) ? data.results : [])
                .filter((r) => r.created)
                .map((r) => r.address)
        );
        discoveredLanHosts = discoveredLanHosts.map((host) =>
            createdAddresses.has(host.address) ? { ...host, already_exists: true } : host
        );
        renderDiscoveredLanHosts();
        await loadHosts();
        showToast("success", `${data.created} host(s) importado(s) com sucesso.`);
    } catch (err) {
        console.error("Erro ao importar hosts:", err);
        showToast("error", "Falha ao importar hosts selecionados.");
    } finally {
        if (importBtn) {
            importBtn.disabled = false;
            importBtn.textContent = "Adicionar selecionados";
        }
    }
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
            div.innerHTML = "<div class='ui-state ui-state-warning'>Não foi possível carregar os hosts.</div>";
            return;
        }

        const hosts = await res.json();
        if (!Array.isArray(hosts) || hosts.length === 0) {
            div.innerHTML = "<div class='ui-state ui-state-empty'>Nenhum host cadastrado ainda.</div>";
            return;
        }
        div.innerHTML = "";

        for (const h of hosts) {
            const card = document.createElement("div");
            const hostPorts = parseHostPorts(h);
            const hostAddressLabel = `${h.address}`;
            const tcpPortsLabel = hostPorts.length ? hostPorts.join(", ") : "Nenhuma";
            const httpEnabled = !!h.http_enabled;
            const webCheckBadge = httpEnabled
                ? `<span class="web-check-badge web-check-on">Ativo</span>`
                : `<span class="web-check-badge web-check-off">Inativo</span>`;
            const httpProtocolLabel = httpEnabled
                ? (h.http_protocol ? String(h.http_protocol).toUpperCase() : "Aguardando")
                : "-";
            const visualState = hostVisualState(h);
            const monitorFlag = hostMonitorFlag(h);
            const causeClass = probableCauseClass(h);
            const incidentBadgeHtml = h.has_open_incident
                ? `<span class="incident-badge" title="Existe incidente aberto para este host">INCIDENTE ABERTO</span>`
                : "";
            card.className = `card ${visualState.cardClass}`;
            card.id = `card-${h.name}`;
            card.dataset.face = "1";

            let statusColor = "bg-secondary";
            if (h.status === "UP") statusColor = "bg-success";
            else if (h.status === "DOWN") statusColor = "bg-danger";
            else if (h.status === "DEGRADED") statusColor = "bg-warning";
            
            let sevClass = "sev-unknown";

            if (h.severity === "HEALTHY") sevClass = "sev-healthy";
            else if (h.severity === "WARNING") sevClass = "sev-warning";
            else if (h.severity === "DEGRADED") sevClass = "sev-degraded";
            else if (h.severity === "CRITICAL") sevClass = "sev-critical";
            const severityIndicatorHtml = h.icmp_blocked_but_service_up
                ? ""
                : `<span class="severity-indicator ${sevClass}">✚</span>`;

            const availability10m = h.availability_10m != null
                ? h.availability_10m.toFixed(2)
                : "N/A";
            const totalTrafficBps = Number(h.network_traffic) || 0;
            const downloadTrafficBps = Number(h.network_in_bps) || 0;
            const uploadTrafficBps = Number(h.network_out_bps) || 0;
            const maxTrafficBps = Math.max(totalTrafficBps, downloadTrafficBps, uploadTrafficBps, 1);
            const totalTrafficBar = calcRelativeBarWidth(totalTrafficBps, maxTrafficBps);
            const downloadTrafficBar = calcRelativeBarWidth(downloadTrafficBps, maxTrafficBps);
            const uploadTrafficBar = calcRelativeBarWidth(uploadTrafficBps, maxTrafficBps);
            const snmpConfigured = [
                h.cpu_usage,
                h.ram_usage,
                h.disk_usage,
                h.network_traffic,
                h.network_in_bps,
                h.network_out_bps
            ].some((value) => value !== null && value !== undefined);
            const snmpStatusHtml = !snmpConfigured
                ? `<small class="snmp-tag snmp-tag-off snmp-empty-message">SNMP: não configurado</small>`
                : "";
            const snmpSectionHtml = snmpConfigured ? `
                        <div class="metrics-section snmp-section">
                            <div class="snmp-header">
                                <div class="snmp-title">SNMP</div>
                                <div class="snmp-subtitle">Métricas estimadas via OIDs</div>
                            </div>
                            <div class="snmp-kpi-grid">
                                <div class="snmp-kpi-card">
                                    <div class="snmp-kpi-head">
                                        <small class="snmp-kpi-label" title="CPU">CPU</small>
                                        <small class="snmp-kpi-value ${metricClass(h.cpu_usage)}">${metricPercent(h.cpu_usage)}</small>
                                    </div>
                                    <div class="snmp-kpi-bar"><span class="snmp-kpi-fill ${metricClass(h.cpu_usage)}" style="width:${metricBarWidth(h.cpu_usage)}%"></span></div>
                                </div>
                                <div class="snmp-kpi-card">
                                    <div class="snmp-kpi-head">
                                        <small class="snmp-kpi-label" title="RAM">RAM</small>
                                        <small class="snmp-kpi-value ${metricClass(h.ram_usage)}">${metricPercent(h.ram_usage)}</small>
                                    </div>
                                    <div class="snmp-kpi-bar"><span class="snmp-kpi-fill ${metricClass(h.ram_usage)}" style="width:${metricBarWidth(h.ram_usage)}%"></span></div>
                                </div>
                                <div class="snmp-kpi-card">
                                    <div class="snmp-kpi-head">
                                        <small class="snmp-kpi-label" title="Disco">Disco</small>
                                        <small class="snmp-kpi-value ${metricClass(h.disk_usage)}">${metricPercent(h.disk_usage)}</small>
                                    </div>
                                    <div class="snmp-kpi-bar"><span class="snmp-kpi-fill ${metricClass(h.disk_usage)}" style="width:${metricBarWidth(h.disk_usage)}%"></span></div>
                                </div>
                            </div>
                            <div class="snmp-traffic-panel">
                                <div class="snmp-traffic-row">
                                    <small class="snmp-traffic-label" title="Tráfego de Rede">Tráfego de Rede</small>
                                    <div class="snmp-mini-bar"><span style="width:${totalTrafficBar}%"></span></div>
                                    <small class="snmp-traffic-value">${formatBps(h.network_traffic)}</small>
                                </div>
                                <div class="snmp-traffic-row">
                                    <small class="snmp-traffic-label" title="Download (RX)">Download (RX)</small>
                                    <div class="snmp-mini-bar"><span style="width:${downloadTrafficBar}%"></span></div>
                                    <small class="snmp-traffic-value">${formatBps(h.network_in_bps)}</small>
                                </div>
                                <div class="snmp-traffic-row">
                                    <small class="snmp-traffic-label" title="Upload (TX)">Upload (TX)</small>
                                    <div class="snmp-mini-bar"><span style="width:${uploadTrafficBar}%"></span></div>
                                    <small class="snmp-traffic-value">${formatBps(h.network_out_bps)}</small>
                                </div>
                            </div>
                        </div>
            ` : "";
            const snmpChartBoxHtml = snmpConfigured ? `
                <div id="snmp-chart-box-${h.name}" class="chart-box hidden" style="margin-top: 10px;">
                    <div class="chart-title">Histórico SNMP</div>
                    <canvas id="snmp-chart-${h.name}" height="120"></canvas>
                </div>
            ` : "";

            card.innerHTML = `
                <!-- Header: identificação + indicadores rápidos -->
                <div class="host-card-header">
                    <div class="host-top-line">
                        <div class="host-title-wrap">
                            <span class="status-indicator ${statusColor}"></span>
                            <strong class="host-title">
                                ${h.name}
                                <small class="host-addr">(${hostAddressLabel})</small>
                            </strong>
                        </div>
                        <div class="host-top-actions">
                            <span class="host-monitor-flag ${monitorFlag.className}" title="Estado de monitoramento">${monitorFlag.label}</span>
                            ${incidentBadgeHtml}
                            <button
                                class="host-delete-btn"
                                type="button"
                                title="Excluir host"
                                aria-label="Excluir host"
                                onclick='softDeleteHost(${h.id}, ${JSON.stringify(h.name)})'
                            >✕</button>
                        </div>
                    </div>

                    <div class="host-meta-grid">
                        <div class="host-meta-item"><small>Saúde</small><strong>${h.health_score ?? "N/A"}% ${severityIndicatorHtml}</strong></div>
                        <div class="host-meta-item"><small>Disponibilidade</small><strong>${availability10m}%</strong></div>
                        <div class="host-meta-item"><small>Último check</small><strong>${formatCheckTime(h.last_check)}</strong></div>
                        <div class="host-meta-item"><small>Último SNMP</small><strong>${formatCheckTime(h.last_snmp_check)}</strong></div>
                    </div>
                </div>

                <div class="face-nav">
                    <button class="face-nav-btn face-prev-btn hidden" type="button" title="Face anterior" aria-label="Face anterior" onclick="prevHostFace('${h.name}')">${iconSvg("arrow_left")}</button>
                    <div class="icon-actions">
                        <button class="icon-btn" type="button" title="Histórico" aria-label="Histórico" onclick="toggleHistory('${h.name}')">${iconSvg("history")}</button>
                        <button class="icon-btn" type="button" title="Gráfico de latência" aria-label="Gráfico de latência" onclick="toggleLatencyChart('${h.name}')">${iconSvg("latency")}</button>
                        ${snmpConfigured ? `<button class="icon-btn" type="button" title="Gráfico SNMP" aria-label="Gráfico SNMP" onclick="toggleSnmpChart('${h.name}')">${iconSvg("snmp")}</button>` : ""}
                        <button class="icon-btn" type="button" title="Disponibilidade por tipo" aria-label="Disponibilidade por tipo" onclick="toggleAvailabilityChartType('${h.name}')">${iconSvg("availability_type")}</button>
                        <button class="icon-btn" type="button" title="Disponibilidade geral" aria-label="Disponibilidade geral" onclick="toggleAvailabilityChart('${h.name}')">${iconSvg("availability")}</button>
                        <button class="icon-btn" type="button" title="Editar host" aria-label="Editar host" onclick='openEditModal(${JSON.stringify(h.name)}, ${JSON.stringify(h.address)}, ${JSON.stringify(hostPorts)}, ${JSON.stringify(h.http_url || "")}, ${h.http_enabled ? "true" : "false"}, ${h.snmp_enabled ? "true" : "false"})'>${iconSvg("edit")}</button>
                    </div>
                    <button class="face-nav-btn face-next-btn" type="button" title="Próxima face" aria-label="Próxima face" onclick="nextHostFace('${h.name}')">${iconSvg("arrow_right")}</button>
                </div>

                <!-- Body: três colunas (Resumo | Rede | SNMP) -->
                <div class="host-card-body compact host-faces-wrap">
                    <div class="host-col host-col-summary host-face active" data-face="1">
                        <div class="host-section-card">
                            <div class="metrics-title">Resumo</div>
                            <div class="host-summary-list">
                                <small><b>Portas TCP monitoradas:</b> ${tcpPortsLabel}</small>
                                <small><b>Check Web:</b> ${webCheckBadge}</small>
                                <small><b>Protocolo resolvido:</b> ${httpProtocolLabel}</small>
                                <small><b>Saúde:</b> ${h.health_score ?? "N/A"}%</small>
                                <small><b>Disponibilidade:</b> ${availability10m}%</small>
                                <small><b>Tendência HTTP:</b> ${trendIcon(h.trend_http)} ${h.trend_http ?? "N/A"}</small>
                                <small><b>Causa provável:</b></small>
                                <small class="cause-pill ${causeClass}">${h.probable_cause ?? "Operação normal"}</small>
                            </div>
                        </div>
                    </div>

                    <div class="host-col host-col-network host-face" data-face="2">
                        <div class="host-section-card">
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
                            <div class="host-checks-section">
                                <div class="metrics-title">Últimos checks</div>
                                <div id="result-${h.name}" class="host-last-checks">
                                    <i>Atualizando...</i>
                                </div>
                            </div>
                            <div class="tcp-ports-section">
                                <div class="metrics-title">Portas TCP monitoradas</div>
                                <div id="tcp-ports-status-${h.name}" class="tcp-ports-status">
                                    <small class="tcp-ports-empty">Atualizando...</small>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="host-col host-col-snmp host-face" data-face="3">
                        ${snmpConfigured ? snmpSectionHtml : `
                            <div class="host-section-card snmp-section snmp-empty">
                                <div class="snmp-header">
                                    <div class="snmp-title">SNMP</div>
                                    <div class="snmp-subtitle">Métricas estimadas via OIDs</div>
                                </div>
                                <div class="snmp-empty-body">
                                    ${snmpStatusHtml}
                                </div>
                            </div>
                        `}
                    </div>
                </div>

                <div id="chart-container-${h.name}" class="chart-box hidden" style="margin-top: 10px;">
                    <div class="chart-title">Latência dos checks</div>
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
            loadLastResult(
                h.name,
                hostPorts,
                httpEnabled,
                h.http_protocol,
                h.http_latency,
                h.tcp_http_port_latency,
                h.tcp_https_port_latency,
                h.tcp_http_port_ok,
                h.tcp_https_port_ok
            );
            updateHostFace(h.name, 1);

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
                loadLastResult(
                    h.name,
                    parseHostPorts(h),
                    !!h.http_enabled,
                    h.http_protocol,
                    h.http_latency,
                    h.tcp_http_port_latency,
                    h.tcp_https_port_latency,
                    h.tcp_http_port_ok,
                    h.tcp_https_port_ok
                );
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

function tcpFailureLabel(error) {
    const text = String(error || "").toLowerCase();
    if (!text) return "falha";
    if (text.includes("timeout")) return "timeout";
    if (text.includes("refused") || text.includes("unreachable")) return "indisponível";
    return "falha";
}

function renderTcpPortsStatus(hostName, checks, expectedPorts = []) {
    const box = document.getElementById(`tcp-ports-status-${hostName}`);
    if (!box) return;

    const tcpChecks = Array.isArray(checks) ? checks.filter((c) => c.type === "tcp") : [];
    const latestByPort = new Map();
    for (const item of tcpChecks) {
        const port = Number(item.tcp_port);
        if (!Number.isInteger(port)) continue;
        if (!latestByPort.has(port)) latestByPort.set(port, item);
    }

    const ports = Array.from(
        new Set(expectedPorts.filter((p) => Number.isInteger(Number(p))).map((p) => Number(p)))
    ).sort((a, b) => a - b);

    if (!ports.length) {
        box.innerHTML = "<small class='tcp-ports-empty'>Sem portas TCP configuradas.</small>";
        return;
    }

    box.innerHTML = ports.map((port) => {
        const item = latestByPort.get(port);
        const ok = !!item?.success;
        const dot = ok ? "bg-success" : "bg-danger";
        const rightText = item
            ? (ok ? `${item.latency ?? "N/A"} ms` : tcpFailureLabel(item.error))
            : "sem dados";
        return `
            <div class="tcp-port-item">
                <span class="status-indicator ${dot}"></span>
                <span class="tcp-port-label">TCP ${port}:</span>
                <span class="tcp-port-meta">${rightText}</span>
            </div>
        `;
    }).join("");
}

async function loadLastResult(
    name,
    expectedPorts = [],
    httpEnabled = true,
    httpProtocol = null,
    httpLatency = null,
    tcpHttpPortLatency = null,
    tcpHttpsPortLatency = null,
    tcpHttpPortOk = null,
    tcpHttpsPortOk = null
) {
    const box = document.getElementById("result-" + name);
    if (!box) return;

    const res = await fetchWithAuth(`${API}/host/history/${name}`);
    
    if (!res || !res.ok) return;

    const data = await res.json();
    renderTcpPortsStatus(name, data.checks, expectedPorts);

    const lastPing = data.checks.find(c => c.type === "ping");
    const lastHttp = httpEnabled ? data.checks.find(c => c.type === "http") : null;

    const pingLikelyFirewallBlocked =
        !!lastPing &&
        !lastPing.success &&
        (!!lastHttp && lastHttp.success);

    const pingDot = pingLikelyFirewallBlocked
        ? "bg-secondary"
        : (lastPing?.success ? "bg-success" : "bg-danger");
    const webDot = httpEnabled
        ? (lastHttp?.success ? "bg-success" : "bg-danger")
        : "bg-secondary";

    const pingLatencyText = pingLikelyFirewallBlocked
        ? "indisponível"
        : (lastPing ? (lastPing.success ? `${lastPing?.latency ?? "sem dados"} ms` : tcpFailureLabel(lastPing.error)) : "sem dados");
    const resolvedProtocol = String(httpProtocol || "").toUpperCase();
    const protocolLabel = resolvedProtocol === "HTTPS" || resolvedProtocol === "HTTP"
        ? resolvedProtocol
        : "Web";
    const protocolValue = !httpEnabled
        ? "inativo"
        : (httpLatency !== null && httpLatency !== undefined
            ? `${httpLatency} ms`
            : "Aguardando");

    const formatAuxTcp = (enabled, latency, okFlag) => {
        if (!enabled) return "-";
        if (latency !== null && latency !== undefined) return `${latency} ms`;
        if (okFlag === false) return "falha";
        if (okFlag === true) return "sem dados";
        return "Aguardando";
    };

    const portaHttpText = formatAuxTcp(httpEnabled, tcpHttpPortLatency, tcpHttpPortOk);
    const portaHttpsText = formatAuxTcp(httpEnabled, tcpHttpsPortLatency, tcpHttpsPortOk);

    box.innerHTML = `
        <div>
            <span class="status-indicator ${pingDot}"></span>
            Ping: ${pingLatencyText}
        </div>
        <div>
            <span class="status-indicator ${webDot}"></span>
            ${httpEnabled ? protocolLabel : "Web"}: ${httpEnabled ? protocolValue : "Inativo"}
        </div>
        <div>
            <span class="status-indicator ${webDot}"></span>
            HTTP (TCP 80): ${portaHttpText}
        </div>
        <div>
            <span class="status-indicator ${webDot}"></span>
            HTTPS (TCP 443): ${portaHttpsText}
        </div>
    `;
}

async function loadHistory(name) {
    const box = document.getElementById("history-" + name);
    if (!box) return;
    box.innerHTML = "<div class='ui-state ui-state-info'>Carregando histórico...</div>";

    try {
        const res = await fetchWithAuth(`${API}/host/history/${name}`);

        if (!res || !res.ok) return;

        const data = await res.json();

        const checks = Array.isArray(data.checks) ? data.checks.slice(0, 20) : [];

        if (!checks.length) {
            box.innerHTML = "<div class='ui-state ui-state-empty'>Sem histórico ainda</div>";
            return;
        }

        const linesHtml = checks.map(c => {
            const statusClass = c.success ? "line-success" : "line-error";
            const statusText = c.success ? "OK" : "FAIL";
            const typeLabel = c.type === "tcp" && c.tcp_port
                ? `TCP ${c.tcp_port}`
                : c.type.toUpperCase();
            const detailParts = [];
            if (c.status_code) detailParts.push(`HTTP ${c.status_code}`);
            if (c.error) detailParts.push(c.error);
            detailParts.push(c.latency !== null ? `${c.latency} ms` : "---");
            const detailText = detailParts.join(" • ");
            return `
                <div class="history-line ${statusClass}">
                    <div class="history-line-top">
                        <span class="type-badge">${typeLabel}</span>
                        <span class="history-status">${statusText}</span>
                        <small class="history-time">${formatApiTime(c.timestamp)}</small>
                    </div>
                    <div class="history-line-bottom">
                        <span class="history-detail">${detailText}</span>
                    </div>
                </div>
            `;
        }).join("");

        box.innerHTML = `<div class="host-history-scroll">${linesHtml}</div>`;

    } catch {
        box.innerHTML = "<div class='ui-state ui-state-error'>Erro ao carregar histórico</div>";
    }
}

async function toggleHistory(name) {
    const box = document.getElementById("history-" + name);

    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        return;
    }

    closeHostExpandedPanels(name, box.id);
    box.classList.remove("hidden");
    await loadHistory(name);
}

async function toggleLatencyChart(name) {
    const container = document.getElementById("chart-container-" + name);
    if (!container) return;

    if (container.classList.contains("hidden")) {
        closeHostExpandedPanels(name, container.id);
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
        closeHostExpandedPanels(name, box.id);
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

    closeHostExpandedPanels(name, box.id);
    box.classList.remove("hidden");
    loadAvailabilityChartType(name);
}

let currentEditHost = null;

function openEditModal(name, ip, ports = [], httpUrl, httpEnabled = true, snmpEnabled = false) {
    currentEditHost = name;

    document.getElementById("modal-name").value = name;
    document.getElementById("modal-ip").value = ip || "";
    document.getElementById("modal-http-url").value = httpUrl || "";
    const modalHttpEnabled = document.getElementById("modal-http-enabled");
    if (modalHttpEnabled) {
        modalHttpEnabled.checked = !!httpEnabled;
    }
    const modalSnmpEnabled = document.getElementById("modal-snmp-enabled");
    if (modalSnmpEnabled) {
        modalSnmpEnabled.checked = !!snmpEnabled;
    }
    setModalPorts(ports);

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

function calcRelativeBarWidth(value, maxValue) {
    const current = Number(value);
    const max = Number(maxValue);
    if (!Number.isFinite(current) || current <= 0 || !Number.isFinite(max) || max <= 0) return 0;
    const ratio = (current / max) * 100;
    return Math.max(8, Math.min(100, ratio));
}

// Classificação visual para métricas percentuais (CPU/RAM/Disco): 0-59, 60-79, 80-100.
function metricClass(value, warn = 60, critical = 80) {
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
    const newHttp = document.getElementById("modal-http-url").value;
    const newHttpEnabled = !!document.getElementById("modal-http-enabled")?.checked;
    const newSnmpEnabled = !!document.getElementById("modal-snmp-enabled")?.checked;
    const modalPortsContainer = document.getElementById("modalPortsContainer");
    let ports = [];
    try {
        ports = collectPorts(modalPortsContainer);
    } catch (err) {
        showToast("error", err.message || "Lista de portas inválida.");
        return;
    }

    const res = await fetchWithAuth(`${API}/host/update/${currentEditHost}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            address: newIp,
            ports,
            port: ports.length ? ports[0] : null,
            url: newHttp || null,
            http_url: newHttp || null,
            http_enabled: newHttpEnabled,
            snmp_enabled: newSnmpEnabled
        })
    });

    if (res.ok) {
        closeModal();
        await loadHosts();
        showToast("success", "Host atualizado com sucesso.");
    } else {
        showToast("error", "Erro ao salvar alterações do host.");
    }
}

async function loadLatencyChart(name) {
    const chartKey = `latency-${name}`;
    const res = await fetchWithAuth(`${API}/host/history/${name}`);
    
    if (!res || !res.ok) return;

    const data = await res.json();
    const ctx = document.getElementById("chart-" + name);
    const containerId = "chart-container-" + name;
    const canvasId = "chart-" + name;

    if (!ctx) return;

    const checks = Array.isArray(data.checks) ? data.checks : [];
    const latencyChecks = checks.filter((c) => c.latency !== null && c.latency !== undefined);
    if (!latencyChecks.length) {
        showChartEmpty(containerId, canvasId, "Sem dados de latência para este host.");
        return;
    }
    clearChartEmpty(containerId, canvasId);

    const perSeries = new Map();
    for (const check of latencyChecks) {
        const type = String(check.type || "").toLowerCase();
        if (type === "tcp") {
            const tcpPort = Number(check.tcp_port);
            if (!Number.isInteger(tcpPort)) continue;
            const key = `tcp:${tcpPort}`;
            const label = `TCP ${tcpPort}`;
            if (!perSeries.has(key)) perSeries.set(key, { label, points: [] });
            perSeries.get(key).points.push(check);
            continue;
        }
        if (type === "ping") {
            if (!perSeries.has("ping")) perSeries.set("ping", { label: "Ping", points: [] });
            perSeries.get("ping").points.push(check);
            continue;
        }
        if (type === "http") {
            if (!perSeries.has("http")) perSeries.set("http", { label: "HTTP", points: [] });
            perSeries.get("http").points.push(check);
        }
    }

    const timestampKeys = Array.from(
        new Set(
            Array.from(perSeries.values()).flatMap((series) =>
                series.points.map((p) => String(p.timestamp))
            )
        )
    ).sort();

    const labels = timestampKeys.map((ts) => formatApiTime(ts));
    const colorByLabel = (label) => {
        if (label === "Ping") return { line: "#22c55e", fill: "#22c55e33" };
        if (label === "HTTP") return { line: "#f59e0b", fill: "#f59e0b33" };
        return { line: "#3b82f6", fill: "#3b82f633" };
    };

    const orderedSeries = Array.from(perSeries.values()).sort((a, b) => {
        const aTcp = a.label.startsWith("TCP ");
        const bTcp = b.label.startsWith("TCP ");
        if (aTcp && bTcp) {
            return Number(a.label.replace("TCP ", "")) - Number(b.label.replace("TCP ", ""));
        }
        if (aTcp) return 1;
        if (bTcp) return -1;
        return a.label.localeCompare(b.label);
    });

    const datasets = orderedSeries.map((series) => {
        const byTs = new Map(series.points.map((p) => [String(p.timestamp), p.latency]));
        const values = timestampKeys.map((ts) => (byTs.has(ts) ? byTs.get(ts) : null));
        const colors = colorByLabel(series.label);
        return {
            label: series.label,
            data: values,
            borderColor: colors.line,
            backgroundColor: colors.fill,
            tension: 0.3,
            spanGaps: true,
        };
    });

    updateOrCreateChart(chartKey, ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets
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

function hostVisualState(host) {
    if (host?.icmp_blocked_but_service_up) {
        return { cardClass: "card-state-up", badgeClass: "state-up", label: "UP" };
    }

    const status = String(host?.status || "").toUpperCase();
    const severity = String(host?.severity || "").toUpperCase();

    if (severity === "CRITICAL") {
        return { cardClass: "card-state-critical", badgeClass: "state-critical", label: "CRITICAL" };
    }
    if (status === "DOWN") {
        return { cardClass: "card-state-down", badgeClass: "state-down", label: "DOWN" };
    }
    if (status === "DEGRADED" || severity === "DEGRADED" || severity === "WARNING") {
        return { cardClass: "card-state-degraded", badgeClass: "state-degraded", label: "DEGRADED" };
    }
    return { cardClass: "card-state-up", badgeClass: "state-up", label: "UP" };
}

function probableCauseClass(host) {
    if (host?.icmp_blocked_but_service_up) return "cause-normal";

    const status = String(host?.status || "").toUpperCase();
    const severity = String(host?.severity || "").toUpperCase();
    if (severity === "CRITICAL" || status === "DOWN") return "cause-critical";
    if (status === "DEGRADED" || severity === "DEGRADED" || severity === "WARNING") return "cause-warning";
    return "cause-normal";
}

function hostMonitorFlag(host) {
    if (host?.active === false) return { label: "Pausado", className: "paused" };
    const status = String(host?.status || "").toUpperCase();
    if (status === "DOWN") return { label: "Em falha", className: "down" };
    if (status === "DEGRADED") return { label: "Degradado", className: "degraded" };
    return { label: "Monitorando", className: "running" };
}

function iconSvg(name) {
    const icons = {
        history: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5l3 2M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4"/></svg>`,
        latency: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18h16M6 16l3-5 3 3 4-7 2 3"/></svg>`,
        snmp: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h16M7 8h10M7 16h10"/></svg>`,
        availability_type: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18V8M12 18V6M19 18v-4"/></svg>`,
        availability: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 17l4-5 4 3 6-8"/></svg>`,
        edit: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4-1 9-9-3-3-9 9-1 4zm10-13l3 3"/></svg>`,
        trash: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4h6l1 2h4v2H4V6h4l1-2zm-2 6h2v8H7v-8zm4 0h2v8h-2v-8zm4 0h2v8h-2v-8z"/></svg>`,
        arrow_left: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 6l-6 6 6 6"/></svg>`,
        arrow_right: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 6l6 6-6 6"/></svg>`,
        close: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
    };
    return icons[name] || "";
}

function closeHostExpandedPanels(hostName, exceptId = null) {
    const panelIds = [
        `history-${hostName}`,
        `chart-container-${hostName}`,
        `snmp-chart-box-${hostName}`,
        `availability-chart-type-box-${hostName}`,
        `availability-chart-box-${hostName}`
    ];

    panelIds.forEach((panelId) => {
        if (exceptId && panelId === exceptId) return;
        const panel = document.getElementById(panelId);
        if (!panel) return;
        panel.classList.add("hidden");
    });
}

function updateHostFace(hostName, faceNumber) {
    const card = document.getElementById(`card-${hostName}`);
    if (!card) return;
    const faces = card.querySelectorAll(".host-face");
    if (!faces.length) return;

    const safeFace = Math.max(1, Math.min(3, Number(faceNumber) || 1));
    card.dataset.face = String(safeFace);

    faces.forEach((face) => {
        const n = Number(face.getAttribute("data-face"));
        face.classList.toggle("active", n === safeFace);
    });

    const prevBtn = card.querySelector(".face-prev-btn");
    const nextBtn = card.querySelector(".face-next-btn");
    if (prevBtn) prevBtn.classList.toggle("hidden", safeFace <= 1);
    if (nextBtn) nextBtn.classList.toggle("hidden", safeFace >= 3);
}

function nextHostFace(hostName) {
    const card = document.getElementById(`card-${hostName}`);
    const current = Number(card?.dataset?.face || 1);
    updateHostFace(hostName, current + 1);
}

function prevHostFace(hostName) {
    const card = document.getElementById(`card-${hostName}`);
    const current = Number(card?.dataset?.face || 1);
    updateHostFace(hostName, current - 1);
}

function alertSeverityClass(severity) {
    const normalized = String(severity || "").toUpperCase();
    if (normalized === "HEALTHY") return "alert-sev-healthy";
    if (normalized === "WARNING") return "alert-sev-warning";
    if (normalized === "DEGRADED") return "alert-sev-degraded";
    if (normalized === "CRITICAL") return "alert-sev-critical";
    return "alert-sev-unknown";
}

function incidentTypeLabel(incidentType) {
    const key = String(incidentType || "GENERIC").toUpperCase();
    return INCIDENT_TYPE_LABELS[key] || "Incidente operacional";
}

function alertTypeLabel(alertType) {
    const key = String(alertType || "").toUpperCase();
    return ALERT_TYPE_LABELS[key] || (alertType || "Alerta");
}

function alertDedupeKey(alert) {
    return [
        String(alert.host_name || "").toLowerCase(),
        String(alert.alert_type || "").toUpperCase(),
        String(alert.old_status || "").toUpperCase(),
        String(alert.new_status || "").toUpperCase()
    ].join("|");
}

function alertSeenKey(alert) {
    return [
        String(alert.host_name || "").toLowerCase(),
        String(alert.alert_type || "").toUpperCase(),
        String(alert.timestamp || ""),
        String(alert.old_status || "").toUpperCase(),
        String(alert.new_status || "").toUpperCase()
    ].join("|");
}

function shouldRenderAlertCard(alert) {
    const key = alertDedupeKey(alert);
    const now = Date.now();
    const lastShownAt = recentAlertCache.get(key) || 0;

    if (now - lastShownAt < ALERT_DEDUP_WINDOW_MS) {
        return false;
    }

    recentAlertCache.set(key, now);

    if (recentAlertCache.size > 250) {
        for (const [cacheKey, ts] of recentAlertCache.entries()) {
            if (now - ts > ALERT_DEDUP_WINDOW_MS * 3) {
                recentAlertCache.delete(cacheKey);
            }
        }
    }
    return true;
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
            ${alert.host_address}${alert.host_port ? `:${alert.host_port}` : ""} | ${alertTypeLabel(alert.alert_type ?? "STATUS_CHANGE")}
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
    if (!Array.isArray(alerts) || alerts.length === 0) return;

    if (!seenAlertsBootstrapped) {
        alerts.forEach((a) => rememberSeenAlert(alertSeenKey(a)));
        persistSeenAlertKeys();
        seenAlertsBootstrapped = true;
        lastAlertTime = alerts[0]?.timestamp || lastAlertTime;
        return;
    }

    const ordered = [...alerts].reverse();
    let newestSeen = lastAlertTime;
    let storageChanged = false;

    ordered.forEach((a) => {
        const seenKey = alertSeenKey(a);
        if (!newestSeen || a.timestamp > newestSeen) {
            newestSeen = a.timestamp;
        }
        if (seenAlertKeysSet.has(seenKey)) return;
        if (!shouldRenderAlertCard(a)) {
            rememberSeenAlert(seenKey);
            storageChanged = true;
            return;
        }
        showAlertCard(a);
        rememberSeenAlert(seenKey);
        storageChanged = true;
    });

    if (storageChanged) {
        persistSeenAlertKeys();
    }

    if (newestSeen && (!lastAlertTime || newestSeen > lastAlertTime)) {
        lastAlertTime = newestSeen;
    }
}

async function softDeleteHost(hostId, hostName) {

    if (!confirm(`Mover host "${hostName}" para a lixeira?`)) return;

    try {
        const res = await fetchWithAuth(`${API}/hosts/${hostId}/deactivate?host_name=${encodeURIComponent(hostName)}`, {
            method: "POST"
        });

        if (!res.ok) {
            const err = await res.json();
            showToast("error", "Erro ao mover para lixeira: " + (err.detail || "erro"));
            return;
        }

        await loadHosts();
        await loadTrashHosts();
        showToast("success", "Host movido para a lixeira.");

    } catch (e) {
        showToast("error", "Falha de conexão com a API.");
    }
}

async function loadTrashHosts() {
    const box = document.getElementById("trashHostsList");
    if (!box) return;

    try {
        const res = await fetchWithAuth(`${API}/hosts/trash`);
        if (!res || !res.ok) {
            box.innerHTML = "<small>Não foi possível carregar a lixeira.</small>";
            return;
        }

        const hosts = await res.json();
        if (!Array.isArray(hosts) || hosts.length === 0) {
            box.innerHTML = "<small>Nenhum host na lixeira.</small>";
            return;
        }

        box.innerHTML = hosts.map((host) => `
            <div class="trash-item">
                <div class="trash-meta">
                    <strong>${host.name}</strong>
                    <small>${host.address}${host.port ? `:${host.port}` : ""}</small>
                    <small>Desativado em: ${formatApiDateTime(host.deleted_at)}</small>
                </div>
                <div class="trash-actions">
                    <button onclick='restoreHost(${host.id}, ${JSON.stringify(host.name)})'>Restaurar</button>
                    <button class="danger-btn" onclick='hardDeleteHost(${host.id}, ${JSON.stringify(host.name)})'>Excluir permanentemente</button>
                </div>
            </div>
        `).join("");
    } catch (err) {
        box.innerHTML = "<small>Erro ao carregar lixeira.</small>";
    }
}

function openTrashModal() {
    const modal = document.getElementById("trashModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    runTaskOnce("trash", loadTrashHosts);
}

function closeTrashModal() {
    const modal = document.getElementById("trashModal");
    if (!modal) return;
    modal.classList.add("hidden");
}

function openSidebarMenu() {
    const menu = document.getElementById("sidebarMenu");
    const overlay = document.getElementById("sidebarOverlay");
    if (!menu || !overlay) return;
    menu.classList.remove("hidden");
    menu.setAttribute("aria-hidden", "false");
    overlay.classList.remove("hidden");
}

function closeSidebarMenu() {
    const menu = document.getElementById("sidebarMenu");
    const overlay = document.getElementById("sidebarOverlay");
    if (!menu || !overlay) return;
    menu.classList.add("hidden");
    menu.setAttribute("aria-hidden", "true");
    overlay.classList.add("hidden");
}

async function restoreHost(hostId, hostName) {
    if (!confirm(`Restaurar o host \"${hostName}\" da lixeira?`)) return;

    try {
        const res = await fetchWithAuth(`${API}/hosts/${hostId}/restore?host_name=${encodeURIComponent(hostName)}`, {
            method: "POST"
        });
        if (!res || !res.ok) {
            const err = res ? await res.json() : {};
            showToast("error", "Erro ao restaurar: " + (err.detail || "erro"));
            return;
        }

        await loadHosts();
        await loadTrashHosts();
        showToast("success", "Host restaurado com sucesso.");
    } catch (err) {
        showToast("error", "Falha de conexão com a API.");
    }
}

async function hardDeleteHost(hostId, hostName) {
    if (!confirm(`Excluir permanentemente o host \"${hostName}\"?\nEssa ação não pode ser desfeita.`)) return;

    try {
        const res = await fetchWithAuth(`${API}/hosts/${hostId}/hard-delete?host_name=${encodeURIComponent(hostName)}`, {
            method: "DELETE"
        });
        if (!res || !res.ok) {
            const err = res ? await res.json() : {};
            showToast("error", "Erro na exclusão permanente: " + (err.detail || "erro"));
            return;
        }

        await loadHosts();
        await loadTrashHosts();
        showToast("success", "Host excluído permanentemente.");
    } catch (err) {
        showToast("error", "Falha de conexão com a API.");
    }
}

async function toggleAvailabilityChart(name) {
    const box = document.getElementById(`availability-chart-box-${name}`);
    if (!box) return;

    if (box.classList.contains("hidden")) {
        closeHostExpandedPanels(name, box.id);
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
        if (!Array.isArray(incidents) || incidents.length === 0) {
            container.innerHTML = `<div class="timeline-empty">Sem incidentes recentes.</div>`;
            return;
        }

        const ordered = [...incidents].sort(
            (a, b) => new Date(b.started_time).getTime() - new Date(a.started_time).getTime()
        );

        container.innerHTML = ordered.map((inc) => {
            const isClosed = String(inc.status || "").toUpperCase() === "CLOSED";
            const incidentType = String(inc.incident_type || "").toUpperCase();
            let statusLabel = incidentTypeLabel(incidentType);
            if (!isClosed) {
                statusLabel = incidentTypeLabel(incidentType);
            } else {
                statusLabel = "Recuperado";
            }
            const badgeClass = isClosed ? "timeline-badge-closed" : "timeline-badge-open";
            const itemClass = isClosed ? "timeline-item-closed" : "timeline-item-open";
            const startedAt = formatApiDateTime(inc.started_time);
            const endedAt = inc.ended_time ? formatApiDateTime(inc.ended_time) : "Em andamento";
            const durationText = inc.duration
                ? `${Math.max(1, Math.round(inc.duration / 60))} min`
                : "Em andamento";
            const reasonText = inc.reason_text || inc.reason || "Sem causa provável informada.";

            return `
                <div class="timeline-item ${itemClass}">
                    <div class="timeline-item-top">
                        <strong class="timeline-host">${inc.host_name}</strong>
                        <span class="timeline-badge ${badgeClass}">${statusLabel}</span>
                    </div>
                    <div class="timeline-item-meta">
                        <small>Início: ${startedAt}</small>
                        <small>Fim: ${endedAt}</small>
                        <small>Duração: ${durationText}</small>
                    </div>
                    <p class="timeline-reason">${reasonText}</p>
                </div>
            `;
        }).join("");
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
    const searchInput = document.getElementById("searchInput");
    const statusInput = document.getElementById("statusFilter");
    if (!searchInput || !statusInput) return;

    const searchTerm = String(searchInput.value || "").toLowerCase();
    const statusFilter = String(statusInput.value || "all");
    const cards = document.querySelectorAll(".card");

    cards.forEach(card => {
        const hostTitleEl = card.querySelector(".host-title");
        const hostAddrEl = card.querySelector(".host-addr");
        const indicator = card.querySelector(".status-indicator");
        if (!hostTitleEl || !hostAddrEl || !indicator) return;

        const hostName = hostTitleEl.innerText.toLowerCase();
        const hostAddr = hostAddrEl.innerText.toLowerCase();
        
        const matchesSearch = hostName.includes(searchTerm) || hostAddr.includes(searchTerm);
        const matchesStatus = statusFilter === "all" || indicator.classList.contains(statusFilter);

        if (matchesSearch && matchesStatus) {
            card.style.display = "";
        } else {
            card.style.display = "none";
        }
    });
}

// ======================
// Inicialização e Loop
// ======================

if (!isLoginPage) {
    const modalAddPortBtn = document.getElementById("modalAddPortBtn");
    const modalPortsContainer = document.getElementById("modalPortsContainer");
    if (modalAddPortBtn && modalPortsContainer) {
        modalAddPortBtn.addEventListener("click", () => addPortInput(modalPortsContainer, "", true));
    }

    const openTrashBtn = document.getElementById("openTrashBtn");
    if (openTrashBtn) {
        openTrashBtn.addEventListener("click", openTrashModal);
    }

    const refreshBtn = document.getElementById("refreshBtn");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => runTaskOnce("hosts-full", loadHosts));
    }
    const refreshTrashBtn = document.getElementById("refreshTrashBtn");
    if (refreshTrashBtn) {
        refreshTrashBtn.addEventListener("click", () => runTaskOnce("trash", loadTrashHosts));
    }
    const discoverBtn = document.getElementById("discoverBtn");
    if (discoverBtn) {
        discoverBtn.addEventListener("click", discoverNetworkHosts);
    }
    const importSelectedBtn = document.getElementById("importSelectedBtn");
    if (importSelectedBtn) {
        importSelectedBtn.addEventListener("click", importSelectedLanHosts);
    }
    const openMenuBtn = document.getElementById("openMenuBtn");
    if (openMenuBtn) {
        openMenuBtn.addEventListener("click", openSidebarMenu);
    }
    const closeMenuBtn = document.getElementById("closeMenuBtn");
    if (closeMenuBtn) {
        closeMenuBtn.addEventListener("click", closeSidebarMenu);
    }
    const sidebarOverlay = document.getElementById("sidebarOverlay");
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener("click", closeSidebarMenu);
    }

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopDashboardPolling();
            startDashboardPolling();
            return;
        }
        resumeDashboardPolling();
        runLightRefresh();
        runHeavyRefresh();
    });

    ["pointerdown", "keydown", "input", "touchstart"].forEach((eventName) => {
        document.addEventListener(eventName, touchUserInteraction, { passive: true });
    });

    window.addEventListener("DOMContentLoaded", async () => {
        touchUserInteraction();
        await preloadDiscoverySubnet();
        renderDiscoveredLanHosts();
        await runTaskOnce("summary", loadDashboardSummary);
        await runTaskOnce("hosts-full", loadHosts);
        await runTaskOnce("trash", loadTrashHosts);
        await runTaskOnce("alerts", checkAlerts);
        startDashboardPolling();
    });
}

window.addEventListener("click", (event) => {
    const editModal = document.getElementById("editModal");
    const trashModal = document.getElementById("trashModal");
    const sidebarOverlay = document.getElementById("sidebarOverlay");
    const changePwdModal = document.getElementById("changePwdModal");

    if (event.target === editModal) closeModal();
    if (event.target === trashModal) closeTrashModal();
    if (event.target === sidebarOverlay) closeSidebarMenu();
    if (event.target === changePwdModal) closeChangePwdModal();
});

window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeModal();
    closeTrashModal();
    closeSidebarMenu();
    closeChangePwdModal();
});

const changePwdBtn = document.getElementById("changePasswordBtn");

if(changePwdBtn){
    changePwdBtn.onclick = () =>{
        document.getElementById("changePwdModal").classList.remove("hidden");
    }
}

function closeChangePwdModal(){
    const modal = document.getElementById("changePwdModal");
    if (modal) modal.classList.add("hidden");
}

const logoutBtn = document.getElementById("logoutBtn");

if (logoutBtn) {
    logoutBtn.onclick = () => {
        showToast("info", "Sessão encerrada.");
        localStorage.removeItem("token");
        setTimeout(() => {
            window.location.href = "login.html";
        }, 250);
    };
};
