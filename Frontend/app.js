const API = "http://127.0.0.1:8000";

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

        // Usamos uma estratégia de atualização para não "piscar" a tela
        div.innerHTML = "";

        hosts.forEach(h => {
            const card = document.createElement("div");
            card.className = "card";
            card.id = `card-${h.name}`;

            // Lógica simples para definir a cor da bolinha do status geral
            let statusColor = "bg-secondary";
            if (h.status === "UP") statusColor = "bg-success";
            else if (h.status === "DOWN") statusColor = "bg-danger";
            else if (h.status === "DEGRADED") statusColor = "bg-warning";

            card.innerHTML = `
                <div class="card-header">
                    <div>
                        <strong>${h.name}</strong> 
                        <span class="status-indicator ${statusColor}"></span>
                        <small>(${h.address}${h.port ? ':' + h.port : ''})</small>
                    </div>

                    <button class="history-btn"
                        onclick="toggleHistory('${h.name}')">
                        Ver histórico
                    </button>
                </div>
               
                <div id="result-${h.name}" style="margin-top: 10px; font-size: 0.9em;">
                    <i>Atualizando...</i>
                </div>
                <div id="history-${h.name}" class="history-box hidden"></div>
            `;

            div.appendChild(card);
            
            // Chama o check individual imediatamente para cada host
            checkHost(h.name);
        });
    } catch (err) {
        div.innerHTML = "<p style='color:red'>Erro ao carregar lista de hosts.</p>";
    }
}

async function checkHost(name) {
    const box = document.getElementById("result-" + name);

    try {
        const res = await fetch(`${API}/host/check/${name}`, { method: "POST" });
        if (!res.ok) throw new Error();

        const data = await res.json();

        // Define as bolinhas para Ping e TCP
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
        const res = await fetch(`${API}/host/history/${name}`, {
            method: "GET"
        });

        const data = await res.json();

        if (!data.checks.length) {
            box.innerHTML = "<small>Sem histórico ainda</small>";
            return;
        }

        box.innerHTML = data.checks.map(c => `
            <div class="history-line">
                [${c.type}] 
                ${c.success ? "OK" : "FAIL"} —
                ${c.latency ?? "-"} ms —
                ${new Date(c.timestamp).toLocaleTimeString()}
            </div>
        `).join("");

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
    loadHistory(name);
}


// ======================
// Inicialização e Loop
// ======================

// Atualiza a cada 2 segundos (2000ms)
setInterval(loadHosts, 10000);

document.getElementById("refreshBtn").addEventListener("click", loadHosts);
window.onload = loadHosts;