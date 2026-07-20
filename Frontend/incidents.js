const API = (window.location.protocol === "file:" || window.location.port === "5500" || window.location.port === "3000")
    ? "http://127.0.0.1:8000"
    : "/api";

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

    try {
        const response = await fetch(url, { ...options, headers });
        if (response.status === 401) {
            localStorage.clear();
            window.location.href = "login.html";
            return null;
        }
        return response;
    } catch (error) {
        console.error("Erro de conexão:", error);
        return null;
    }
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

/* ==========================================================================
   THEME TOGGLER MANAGER (LIGHT / DARK THEME)
   ========================================================================== */
(function initThemeManager() {
    const themeToggleBtn = document.getElementById("themeToggleBtn");
    
    // Ler o estado atual do tema
    const savedTheme = localStorage.getItem("theme");
    const isDark = savedTheme === "dark";
    
    // Atualizar o ícone de carregamento inicial
    updateThemeIcon(isDark);
    
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            const currentIsDark = document.documentElement.classList.toggle("dark-theme");
            localStorage.setItem("theme", currentIsDark ? "dark" : "light");
            updateThemeIcon(currentIsDark);
        });
    }
    
    function updateThemeIcon(isDarkState) {
        const icon = document.getElementById("themeToggleIcon");
        if (!icon) return;
        if (isDarkState) {
            // Desenhar ícone de Sol (Tema Escuro -> Clicar para mudar para Claro)
            icon.innerHTML = `<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l-1.42 1.42"/>`;
            icon.setAttribute("stroke", "currentColor");
            icon.setAttribute("stroke-width", "2");
            icon.setAttribute("stroke-linecap", "round");
            icon.setAttribute("stroke-linejoin", "round");
            icon.setAttribute("fill", "none");
        } else {
            // Desenhar ícone de Lua (Tema Claro -> Clicar para mudar para Escuro)
            icon.innerHTML = `<path d="M12 3a9 9 0 109 9 9.75 9.75 0 00-.67-3.4 6.78 6.78 0 01-7.93-7.93A9.75 9.75 0 0012 3z"/>`;
            icon.removeAttribute("stroke");
            icon.removeAttribute("stroke-width");
            icon.removeAttribute("stroke-linecap");
            icon.removeAttribute("stroke-linejoin");
            icon.setAttribute("fill", "currentColor");
        }
    }
})();
