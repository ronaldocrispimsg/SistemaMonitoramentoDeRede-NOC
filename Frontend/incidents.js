const API = "http://127.0.0.1:8000";

async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem("token");
    if (!token) {
        window.location.href = "login.html";
        return null;
    }

    const headers = {
        "Content-Type": "application/json",
        ...options.headers,
        "Authorization": `Bearer ${token}`,
    };

    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
        localStorage.clear();
        window.location.href = "login.html";
        return null;
    }
    return response;
}

function formatDateTime(value) {
    if (!value) return "N/A";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "N/A";
    return dt.toLocaleString("pt-BR");
}

let incidentsCache = [];

function setIncidentsState(message, type = "info") {
    const box = document.getElementById("incidentsList");
    if (!box) return;
    box.innerHTML = `<div class="ui-state ui-state-${type}">${message}</div>`;
}

function renderIncidents(items) {
    const box = document.getElementById("incidentsList");
    if (!box) return;

    if (!items.length) {
        setIncidentsState("Nenhum incidente encontrado.", "empty");
        return;
    }

    box.innerHTML = items.map((inc) => `
        <div class="incident-row">
            <div class="incident-row-main">
                <strong>${inc.host_name || "Host"}</strong>
                <small>${inc.status || "N/A"} • ${inc.incident_type || "GENERIC"}</small>
            </div>
            <div class="incident-row-meta">
                <small>Início: ${formatDateTime(inc.started_time)}</small>
                <small>Fim: ${formatDateTime(inc.ended_time)}</small>
                <small>Duração: ${inc.duration || "Em andamento"}</small>
            </div>
            <div class="incident-row-reason">${inc.reason_text || inc.reason || "Sem descrição"}</div>
        </div>
    `).join("");
}

function applySearch() {
    const term = String(document.getElementById("incidentsSearch")?.value || "").toLowerCase().trim();
    if (!term) {
        renderIncidents(incidentsCache);
        return;
    }
    const filtered = incidentsCache.filter((inc) =>
        String(inc.host_name || "").toLowerCase().includes(term)
    );
    renderIncidents(filtered);
}

async function loadIncidents() {
    setIncidentsState("Carregando incidentes...", "info");
    const res = await fetchWithAuth(`${API}/incidents/latest`);
    if (!res || !res.ok) {
        setIncidentsState("Não foi possível carregar os incidentes.", "error");
        return;
    }
    const data = await res.json();
    incidentsCache = Array.isArray(data) ? data : [];
    applySearch();
}

window.addEventListener("DOMContentLoaded", async () => {
    const searchInput = document.getElementById("incidentsSearch");
    if (searchInput) searchInput.addEventListener("input", applySearch);
    await loadIncidents();
});
