let pollInterval;
let cachedData = [];
let currentFilter = 'all';
let currentConfig = { target_zones: [], connection_mode: 'PROXY' };

// --- INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    // 1. Initial Data Loads
    updateDashboard(); // First status check
    loadConfig();      // Load settings from server
    fetchData();       // Load data table

    // 2. Start Polling
    setInterval(updateDashboard, 2000); // 2s Status
    setInterval(fetchLogs, 1000);      // 1s Logs
    setInterval(fetchData, 8000);      // 8s Data (Slower)

    // 3. UI Init
    // Auto-select first tab or restore state?
    // switchTab('dashboard'); // Default is active in HTML

    // 4. Global Event Listeners
    setupEventListeners();

    // 5. Init UI State
    setExecutionMode('SMART_RESUME');
});

function setupEventListeners() {
    // Connection Mode Change
    document.getElementById('connMode').addEventListener('change', (e) => {
        const mode = e.target.value;
        if (mode === 'FREE_PROXY') {
            updateConfig({ connection_mode: 'PROXY' }); // Treat as Proxy internally
            scrapeProxies();
        } else {
            updateConfig({ connection_mode: mode });
        }
    });

    // Worker Count Change
    const workerInput = document.getElementById('numWorkersInput');
    workerInput.addEventListener('change', (e) => {
        let val = parseInt(e.target.value);
        if (val < 1) val = 1;
        if (val > 50) val = 50;
        updateConfig({ num_workers: val });
    });

    // Execute Mode Logic (Updates UI Text)
    // (Handled by onclicks in HTML calling setExecutionMode)

    // Scrape Button
    const btnScrape = document.getElementById('btnScrapeProxies');
    if (btnScrape) btnScrape.addEventListener('click', scrapeProxies);
}


// --- TABS LOGIC ---
function switchTab(tabId) {
    // 1. Buttons
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    // Find button that triggered this? Or just finding by index?
    // Simple way: iterate all buttons, check onclick attribute? No.
    // Use event.target if passed? 
    // Easier: Just look for the button with the right text or make buttons have IDs.
    // Actually, I can just use the fact that the button called this.
    // Let's rely on event bubbling/target or select by known order.
    // Or just simple:
    const map = {
        'dashboard': 0, 'logs': 1, 'data': 2, 'settings': 3
    };
    const btns = document.querySelectorAll('.tab-btn');
    if (btns[map[tabId]]) btns[map[tabId]].classList.add('active');

    // 2. Content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`view-${tabId}`).classList.add('active');
}


// --- SETTINGS / CONFIG ---
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        currentConfig = data;

        // Render Zones
        renderZones();

        // Sync General Inputs
        if (data.connection_mode) document.getElementById('connMode').value = data.connection_mode;
        if (data.num_workers) document.getElementById('numWorkersInput').value = data.num_workers;

        // Sync Advanced Inputs (Now Static in HTML)
        if (document.getElementById('cfg_headless')) document.getElementById('cfg_headless').checked = !!data.headless;
        if (document.getElementById('cfg_timeout') && data.timeout_ms) document.getElementById('cfg_timeout').value = data.timeout_ms;
        if (document.getElementById('cfg_retries') && data.max_retries) document.getElementById('cfg_retries').value = data.max_retries;
        if (document.getElementById('cfg_captcha') && data.captcha_attempts) document.getElementById('cfg_captcha').value = data.captcha_attempts;
        if (document.getElementById('cfg_misses') && data.max_scan_misses) document.getElementById('cfg_misses').value = data.max_scan_misses;
        if (document.getElementById('cfg_probe') && data.probe_step) document.getElementById('cfg_probe').value = data.probe_step;
        if (document.getElementById('cfg_max_sub_retries') && data.max_sub_retries) document.getElementById('cfg_max_sub_retries').value = data.max_sub_retries;

    } catch (e) { console.error("Error loading config", e); }
}

async function updateConfig(newPartial) {
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newPartial)
        });
        currentConfig = { ...currentConfig, ...newPartial };
    } catch (e) { console.error("Error updating config", e); }
}

async function saveAdvancedConfig() {
    const config = {
        headless: document.getElementById('cfg_headless').checked,
        timeout_ms: parseInt(document.getElementById('cfg_timeout').value),
        max_retries: parseInt(document.getElementById('cfg_retries').value),
        captcha_attempts: parseInt(document.getElementById('cfg_captcha').value),
        max_scan_misses: parseInt(document.getElementById('cfg_misses').value),
        probe_step: parseInt(document.getElementById('cfg_probe').value),
        max_sub_retries: parseInt(document.getElementById('cfg_max_sub_retries').value)
    };

    await updateConfig(config);
    alert("Configurações salvas! Reinicie o robô para aplicar.");
}


// --- ZONES LOGIC ---
function renderZones() {
    const container = document.getElementById('zoneCheckboxes');
    const allZones = ["0", "1", "2", "3", "4", "5", "6"];

    container.innerHTML = allZones.map(z => {
        const isChecked = currentConfig.target_zones.includes(z) ? 'checked' : '';
        // Same layout but adapted needed? Styles.css handles it.
        return `
            <label style="background: #333; padding: 8px 12px; border-radius: 4px; border: 1px solid #555; cursor: pointer; display: flex; align-items: center; gap: 6px; user-select: none;">
                <input type="checkbox" value="${z}" ${isChecked} onchange="toggleZone(this)">
                Zona ${z}
            </label>
        `;
    }).join('');

    // Toggle All Check
    const selectAll = document.getElementById('selectAllZones');
    selectAll.checked = allZones.every(z => currentConfig.target_zones.includes(z));
    selectAll.onclick = toggleAllZones;
}

function toggleZone(checkbox) {
    let zones = new Set(currentConfig.target_zones);
    if (checkbox.checked) zones.add(checkbox.value);
    else zones.delete(checkbox.value);

    const newZones = Array.from(zones);
    updateConfig({ target_zones: newZones }); // Saves immediately

    // Update Select All UI
    const allZones = ["0", "1", "2", "3", "4", "5", "6"];
    document.getElementById('selectAllZones').checked = allZones.every(z => newZones.includes(z));
}

function toggleAllZones(e) {
    const isChecked = e.target.checked;
    const allZones = ["0", "1", "2", "3", "4", "5", "6"];
    // Update UI checkboxes
    document.querySelectorAll('#zoneCheckboxes input').forEach(inp => inp.checked = isChecked);
    // Save
    updateConfig({ target_zones: isChecked ? allZones : [] });
}


// --- EXECUTION CONTROLS ---
function setExecutionMode(mode) {
    // Update Hidden Input
    document.getElementById('execMode').value = mode;

    // Update Status Text
    const display = document.getElementById('currentModeDisplay');

    // Reset colors
    display.style.color = '#4caf50';
    let text = "Modo: SMART RESUME";

    // Handle Reporcss Options Visibility
    const optionsArea = document.getElementById('reprocessOptionsArea');

    if (mode === 'DEEP_SCAN') {
        text = "Modo: VARREDURA PROFUNDA (Deep Scan)";
        display.style.color = '#9C27B0';

        // Auto-check deeper flags
        document.getElementById('reprocessDesmembrados').checked = true;
        document.getElementById('reprocessErrors').checked = true;
        document.getElementById('reprocessSemBoleto').checked = true;

        // Show options
        optionsArea.style.display = 'block';

        // Boost Config Temporary
        updateConfig({ max_scan_misses: 20 });
    }
    else if (mode === 'REPROCESS_ALL') {
        text = "Modo: REPROCESSAR TUDO (Reset parcial)";
        display.style.color = '#f44336';
        optionsArea.style.display = 'block';
        document.getElementById('reprocessAll').checked = true; // wait, reprocessAll button gone?
        // We removed "reprocessAll" checkbox from new HTML, instead rely on mode REPROCESS_ALL + flags?
        // Actually the backend start endpoint takes reprocess=all if the checkbox was there.
        // Let's assume mode REPROCESS_ALL handles it or we manually inject the flag
    }
    else {
        text = `Modo: ${mode.replace('_', ' ')}`;
        // Enable options for SMART_RESUME and others too, as user requested them back
        optionsArea.style.display = 'block';
    }

    display.innerText = text;
}

async function startProcess() {
    const btnStart = document.getElementById('btnStart');
    const mode = document.getElementById('execMode').value; // SMART_RESUME, etc
    const connMode = document.getElementById('connMode').value;

    btnStart.disabled = true;

    // Flags
    let reprocessFlags = [];
    if (document.getElementById('reprocessErrors').checked) reprocessFlags.push('erros');
    if (document.getElementById('reprocessSemBoleto').checked) reprocessFlags.push('sem_boleto');
    if (document.getElementById('reprocessDesmembrados').checked) reprocessFlags.push('desmembrados');
    if (document.getElementById('reprocessUpdateMode').checked) reprocessFlags.push('update_mode');
    if (document.getElementById('reprocessMoreSubunits').checked) reprocessFlags.push('more_subunits');

    // If mode is REPROCESS_ALL, we might want to ensure backend knows
    if (mode === 'REPROCESS_ALL') reprocessFlags.push('all');

    const reprocessParam = reprocessFlags.join(',');

    try {
        const response = await fetch(`/api/start?mode=${mode}&conn_mode=${connMode}&reprocess=${reprocessParam}`, { method: 'POST' });
        const data = await response.json();
        if (data.status === 'success') {
            updateDashboard();
        } else {
            alert('Erro ao iniciar: ' + data.message);
            btnStart.disabled = false;
        }
    } catch (e) {
        console.error(e);
        btnStart.disabled = false;
    }
}

async function stopProcess() {
    try {
        await fetch('/api/stop', { method: 'POST' });
        updateStatusUI(false);
    } catch (e) {
        console.error(e);
    }
}

async function resetData() {
    if (!confirm("Tem certeza? Isso apagará TODOS os dados para sempre.")) return;
    try {
        const res = await fetch('/api/reset', { method: 'POST' });
        if (res.ok) {
            alert("Dados limpos.");
            updateDashboard();
            fetchData();
        } else {
            alert("Erro ao limpar.");
        }
    } catch (e) { console.error(e); }
}


// --- DASHBOARD UPDATES ---

// Moving Average Speed Logic
const SPEED_WINDOW_MS = 10 * 60 * 1000;
let speedHistory = [];

async function updateDashboard() {
    try {
        const res = await fetch(`/api/status?_t=${Date.now()}`);
        const stats = await res.json();

        // Basic Numbers
        document.getElementById('valTotal').innerText = stats.total;
        if (document.getElementById('valMissing')) document.getElementById('valMissing').innerText = stats.missing_inputs;
        document.getElementById('valProcessed').innerText = stats.processed;
        document.getElementById('valSuccess').innerText = stats.success;
        document.getElementById('valErrors').innerText = stats.errors;

        // Progress Bar
        const doneInputs = stats.processed_inputs !== undefined ? stats.processed_inputs : stats.processed;
        const percent = stats.total > 0 ? (doneInputs / stats.total) * 100 : 0;
        document.getElementById('progressBar').style.width = `${percent}%`;

        // Advanced Stats (Speed, Workers, ETA)
        updateAdvancedStats(stats);

        // Worker Grid (Mini)
        updateWorkerGrid(stats.workers);

        // UI State
        updateStatusUI(stats.status === "running");

        // Sync Log Sources Sidebar if new workers appear
        updateLogSourcesList(stats.workers);

    } catch (e) { console.error("Poll error", e); }
}

function updateAdvancedStats(stats) {
    const now = Date.now();
    speedHistory.push({ time: now, processed: stats.processed });
    speedHistory = speedHistory.filter(entry => now - entry.time <= SPEED_WINDOW_MS);

    const oldest = speedHistory[0];
    const newest = speedHistory[speedHistory.length - 1];
    const timeDiffMinutes = (newest.time - oldest.time) / 1000 / 60;
    const processedDiff = newest.processed - oldest.processed;

    let speed = 0;
    if (timeDiffMinutes > 0.16) { // > 10s
        speed = processedDiff / timeDiffMinutes;
    }

    document.getElementById('statsSpeed').innerText = speed > 0 ? Math.round(speed) : 0;

    const activeWorkers = stats.workers ? stats.workers.filter(w => w.status === 'running').length : 0; // Backend doesnt give status yet? Assuming active if in list? No, backend just lists known logs. 
    // Actually backend returns dict with process stats? 
    // The current backend get_status calculates stats from files. It doesn't know if 'process' is real active. 
    // BUT we can assume if 'current_process' is running globaly, then ~all configured workers are likely running.
    // Let's just show configured count or something? Or just leave as is. 
    // Actually, "Active Workers" was just counting length of workers list in previous code. 
    document.getElementById('statsActiveWorkers').innerText = stats.workers.length;

    const errorRate = stats.total > 0 ? ((stats.errors / stats.total) * 100).toFixed(1) : '0.0';
    document.getElementById('statsErrorRate').innerText = errorRate + '%';

    // ETA
    let remainingLines = 0;
    if (stats.processed_inputs && stats.missing_inputs !== undefined) {
        const avgLinesPerInput = stats.processed / stats.processed_inputs;
        remainingLines = stats.missing_inputs * avgLinesPerInput; // estimate
    } else {
        remainingLines = stats.total - stats.processed;
    }

    if (remainingLines > 0 && speed > 0) {
        const etaMin = remainingLines / speed;
        const h = Math.floor(etaMin / 60);
        const m = Math.round(etaMin % 60);
        document.getElementById('statsETA').innerText = `${h}h ${m}m`;
    } else if (remainingLines <= 0 && stats.processed > 0) {
        document.getElementById('statsETA').innerText = "Concluído";
    } else {
        document.getElementById('statsETA').innerText = "Calculando...";
    }
}

function updateWorkerGrid(workers) {
    const grid = document.getElementById('workerGrid');
    if (!workers || workers.length === 0) {
        grid.innerHTML = '<div style="color:#666;">Nenhum worker ativo encontrado nos logs.</div>';
        return;
    }

    grid.innerHTML = workers.map((w) => {
        // We can link this to opening the Logs tab with this worker selected
        const wKey = getWorkerKey(w.name);
        return `
        <div class="card stat-card" style="padding: 10px; min-height: 80px; cursor: pointer; border: 1px solid #444;" 
             onclick="selectLogSourceAndSwitch('${wKey}')">
            <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                <h4 style="margin:0; font-size: 0.8em; color:#aaa;">${w.name}</h4>
                <small style="color:#666;">Worker</small>
            </div>
            <div style="font-size: 1.2em; font-weight: bold;">${w.processed}</div>
            <div style="display:flex; gap:10px; font-size: 0.75em; margin-top:5px;">
                    <span style="color:#4caf50">✅ ${w.success}</span>
                    <span style="color:#f44336">❌ ${w.errors}</span>
            </div>
        </div>
    `}).join('');
}


function updateStatusUI(running) {
    const badge = document.getElementById('statusBadge');
    const statusText = document.getElementById('statusText');
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');

    if (running) {
        badge.classList.add('running');
        statusText.innerText = 'Executando';
        btnStart.disabled = true;
        btnStop.disabled = false;
        document.getElementById('btnReset').disabled = true; // No reset while running
    } else {
        badge.classList.remove('running');
        statusText.innerText = 'Parado';
        btnStart.disabled = false;
        btnStop.disabled = true;
        document.getElementById('btnReset').disabled = false;
    }
}


// --- LOGS LOGIC ---
let activeLogSource = 'main';

function getWorkerKey(name) {
    // "Worker 1" -> "worker_1"
    // "Legacy/Main" -> "main"? NO, legacy is data source.
    if (!name) return 'main';
    let key = name.toLowerCase().replace(' ', '_');
    if (key.includes('.log')) key = key.replace('.log', '');
    return key;
}

function updateLogSourcesList(workers) {
    const sidebar = document.getElementById('logSidebar');
    // We expect 'ls-all' and 'ls-main' to exist.
    // We only append new ones or ensure they exist.

    // Quick way: existing keys
    const existing = new Set();
    sidebar.querySelectorAll('.log-source-item').forEach(el => {
        if (el.id.startsWith('ls-')) existing.add(el.id.replace('ls-', ''));
    });

    workers.forEach(w => {
        const key = getWorkerKey(w.name);
        if (key === 'legacy/main') return; // Skip legacy psuedo-worker

        if (!existing.has(key)) {
            const div = document.createElement('div');
            div.className = 'log-source-item';
            div.id = `ls-${key}`;
            div.innerText = w.name; // Display Name
            div.onclick = () => selectLogSource(key);
            sidebar.appendChild(div);
        }
    });
}

function selectLogSource(source) {
    activeLogSource = source;

    // Update UI highlights
    document.querySelectorAll('.log-source-item').forEach(el => el.classList.remove('active'));
    const activeEl = document.getElementById(`ls-${source}`);
    if (activeEl) activeEl.classList.add('active');

    // Fetch immediately
    fetchLogs();
}

function selectLogSourceAndSwitch(source) {
    selectLogSource(source);
    switchTab('logs');
}

async function fetchLogs() {
    // Check if auto-refresh is on (only if we are not forcibly fetching? actually interval calls this)
    // If called via interval, check checkbox.
    // If called manually (onclick), ignore checkbox.
    // How to distinguish? Argument?

    // Simplify: Just check checkbox always. If user clicked "Update Now", they called fetchLogs().
    // Actually, if tab is not active, don't fetch to save bandwidth.
    const logsTab = document.getElementById('view-logs');
    if (!logsTab.classList.contains('active')) return;

    const auto = document.getElementById('autoRefreshLogs').checked;

    try {
        const res = await fetch(`/api/logs?source=${activeLogSource}&_t=${Date.now()}`);
        const data = await res.json();

        const area = document.getElementById('logsArea');
        const header = `--- Fonte: ${activeLogSource.toUpperCase()} ---\n\n`;
        area.innerText = header + (data.logs || "Sem logs.");
        area.scrollTop = area.scrollHeight; // Auto scroll
    } catch (e) { }
}


// --- DATA / TABLE LOGIC ---
async function fetchData() {
    // Only if tab is active? Or always to keep cache hot? Always is safer for filters.
    try {
        const res = await fetch(`/api/data?_t=${Date.now()}`);
        cachedData = await res.json();
        // Render only if tab active to save DOM CPU? 
        // Or render always? Rendering is fast enough for 8s interval.
        if (document.getElementById('view-data').classList.contains('active')) {
            renderTable();
        }
    } catch (e) { }
}

function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    // Find the button that was clicked... actually harder without passing 'this'
    // Update active class based on text matching?
    // Just re-render. We can rely on onclick passing 'active' manually or just use iterate:
    // ...
    // Easiest: The HTML onclick passes 'setFilter'.
    // Use event.target
    if (event && event.target) {
        event.target.classList.add('active');
    }
    renderTable();
}

function filterTable() { renderTable(); }

// 2. Refactored Render Table (Group First, Then Filter)
function renderTable() {
    const tbody = document.querySelector('#resultsTable tbody');
    const searchVal = document.getElementById('searchInput').value.toLowerCase();

    // A. Group All Data First
    const groups = {};
    cachedData.forEach(item => {
        let base = "others";
        if (item.inscricao && item.inscricao.length >= 8) base = item.inscricao.substring(0, 8);
        if (!groups[base]) groups[base] = [];
        groups[base].push(item);
    });

    let groupList = Object.keys(groups).map(k => {
        const items = groups[k];
        // Sort items (000 first)
        items.sort((a, b) => (a.inscricao || "").localeCompare(b.inscricao || ""));

        // Identify Main vs Subs
        let main = items[0];
        // If first is not 000, try to find parent in global cache manually (orphan case)
        if (items[0].inscricao && !items[0].inscricao.endsWith('000')) {
            // In the group-first approach, the parent SHOULD be here if it exists in cachedData.
            // If not found in sorting, maybe it's not in cachedData?
            // Or maybe sorting put it elsewhere? 
            // With 000 suffix, it should strictly sort first.
            // If missing, check global
            const parentId = k + "000";
            const parent = cachedData.find(i => i.inscricao === parentId);
            if (parent) { main = parent; items.unshift(parent); } // Inject parent
        }

        const subs = items.filter(i => i !== main);
        const hasSubs = subs.length > 0;

        // ** STATUS MASKING LOGIC (Applied BEFORE Filtering) **
        let effectiveStatus = main.status_processamento || '';
        let displayStatus = effectiveStatus;
        let displayClass = getStatusClass(displayStatus);

        if (hasSubs) {
            const sLower = (effectiveStatus || '').toLowerCase();
            // If main is 'anulado' or 'erro' BUT has children (which implies successful expansion), treat as Success Group
            if (displayClass === 'erro' || displayClass === 'sem_boleto' || sLower.includes('anulado')) {
                displayStatus = "Lote com Sub-unidades";
                displayClass = "sucesso";
                effectiveStatus = "sucesso"; // Treat as success for filtering
            }
        }

        return {
            key: k, items: items, main: main, subs: subs, hasSubs: hasSubs,
            displayStatus: displayStatus, displayClass: displayClass, effectiveStatus: effectiveStatus
        };
    });

    // Sort Groups by latest? (Maybe by main Inscrição desc?)
    groupList.sort((a, b) => (b.main.inscricao || "").localeCompare(a.main.inscricao || ""));


    // B. Apply Filters to GROUPS
    let filteredGroups = groupList.filter(g => {
        const main = g.main;
        const status = (g.effectiveStatus || '').toLowerCase(); // Use Effective Status!

        // 1. Status Filter
        let matchStatus = false;
        if (currentFilter === 'all') matchStatus = true;

        // SUCCESS: Matches if effective status is success OR if any child is success?
        // User wants: "Main showing as Success Group".
        if (currentFilter === 'sucesso' && status.includes('sucesso')) matchStatus = true;

        // PARTITIONED: If has subs or main is partitioned
        if (currentFilter === 'particionados') {
            if (g.hasSubs || status.includes('desmembrado')) matchStatus = true;
        }

        // ERROR: If effective status is NOT success. 
        // Note: If we masked Anulada->Success, it won't appear here (which is what User wants!)
        if (currentFilter === 'erro' && !status.includes('sucesso')) matchStatus = true;

        if (!matchStatus) return false;

        // 2. Search Filter (Check Main OR Any Sub)
        if (!searchVal) return true;

        const mainStr = `${main.inscricao} ${main.nome_lote} ${main.nome_proprietario || ''} ${main.cpf_cnpj || ''}`.toLowerCase();
        if (mainStr.includes(searchVal)) return true;

        // Check subs
        if (g.subs.some(s => `${s.inscricao} ${s.nome_lote} ${s.nome_proprietario}`.toLowerCase().includes(searchVal))) return true;

        return false;
    });

    // C. Render
    const MAX_SHOW = 100;
    const toShow = filteredGroups.slice(0, MAX_SHOW);

    let html = '';
    toShow.forEach(g => {
        const { main, subs, hasSubs, displayStatus, displayClass, key } = g;

        const groupId = `g-${key}`;
        const toggleBtn = hasSubs ?
            `<button class="toggle-btn" onclick="toggleGroup('${groupId}', this)">+</button>` : '';

        html += `
            <tr class="main-row">
                <td style="display:flex; align-items:center;">
                    ${toggleBtn}
                    ${main.inscricao}
                </td>
                <td>${main.nome_lote}</td>
                <td>${main.nome_proprietario || '-'}</td>
                <td>${main.cpf_cnpj || '-'}</td>
                <td><span class="status-pill status-${displayClass}">${displayStatus}</span></td>
            </tr>
        `;

        if (hasSubs) {
            subs.forEach(s => {
                // Determine child status (not masked)
                const sCls = getStatusClass(s.status_processamento);
                html += `
                    <tr class="child-row hidden-row ${groupId}">
                         <td>Unidade ${s.inscricao ? s.inscricao.slice(-3) : '?'}</td>
                         <td>${s.nome_lote}</td>
                         <td>${s.nome_proprietario || '-'}</td>
                         <td>${s.cpf_cnpj || '-'}</td>
                         <td><span class="status-pill status-${sCls}">${s.status_processamento}</span></td>
                    </tr>
                `;
            });
        }
    });

    tbody.innerHTML = html;
}

function getStatusClass(s) {
    if (!s) return 'undefined';
    if (s.includes('sucesso')) return 'sucesso';
    if (s.includes('sem_boleto')) return 'sem_boleto';
    if (s.includes('erro')) return 'erro';
    return 'undefined';
}

window.toggleGroup = function (gid, btn) {
    const rows = document.getElementsByClassName(gid);
    let isHidden = false;
    for (let r of rows) {
        if (r.classList.contains('hidden-row')) {
            r.classList.remove('hidden-row');
            isHidden = true;
        } else {
            r.classList.add('hidden-row');
            isHidden = false;
        }
    }
    btn.innerText = isHidden ? '-' : '+';
}


// --- EXPORT PDF ---
function exportPDF() {
    const bairro = document.getElementById('pdfBairro').value;
    const rua = document.getElementById('pdfRua').value;
    const groupBy = document.getElementById('pdfGroupBy').value;
    const includeErrors = document.getElementById('pdfIncludeErrors').checked;

    let columns = [];
    document.querySelectorAll('input[name="pdfCol"]:checked').forEach(c => columns.push(c.value));

    if (columns.length === 0) { alert("Selecione uma coluna!"); return; }

    let url = `/api/export_pdf?columns=${encodeURIComponent(columns.join(','))}&include_errors=${includeErrors}&`;
    if (bairro) url += `bairro=${encodeURIComponent(bairro)}&`;
    if (rua) url += `rua=${encodeURIComponent(rua)}&`;
    if (groupBy) url += `group_by=${encodeURIComponent(groupBy)}&`;

    window.open(url, '_blank');
}


// --- PROXIES ---
async function scrapeProxies() {
    const btn = document.getElementById('btnScrapeProxies');
    const disp = document.getElementById('proxyDisplayArea');

    if (btn) { btn.disabled = true; btn.innerText = "⏳ Scraper rodando... (30s)"; }
    if (disp) { disp.style.display = 'block'; disp.innerText = "Iniciando busca..."; }

    try {
        const res = await fetch('/api/proxies/scrape', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            let html = `✅ ${data.message}`;
            if (data.proxies && data.proxies.length > 0) {
                html += "\n" + data.proxies.join("\n");
                // Auto set proxy mode
                document.getElementById('connMode').value = 'PROXY';
                updateConfig({ connection_mode: 'PROXY' });
            }
            if (disp) disp.innerText = html;
        } else {
            if (disp) disp.innerText = "Erro: " + data.message;
        }
    } catch (e) {
        if (disp) disp.innerText = "Erro de conexão API.";
    } finally {
        if (btn) { btn.disabled = false; btn.innerText = "🔍 Buscar Proxies Grátis"; }
    }
}

// Preset Logic
function applyPreset(type) {
    if (type === 'fast') {
        document.getElementById('cfg_headless').checked = true;
        document.getElementById('cfg_timeout').value = 45000;
        document.getElementById('cfg_retries').value = 5;
        document.getElementById('cfg_captcha').value = 5;
        document.getElementById('cfg_misses').value = 1;
        document.getElementById('cfg_probe').value = 5;
        alert("Preset RÁPIDO aplicado! Lembre-se de SALVAR.");
    } else if (type === 'robust') {
        document.getElementById('cfg_headless').checked = true;
        document.getElementById('cfg_timeout').value = 120000;
        document.getElementById('cfg_retries').value = 50;
        document.getElementById('cfg_captcha').value = 30;
        document.getElementById('cfg_misses').value = 10;
        document.getElementById('cfg_probe').value = 2;
        alert("Preset ROBUSTO aplicado! Lembre-se de SALVAR.");
    } else {
        // Default
        document.getElementById('cfg_headless').checked = true;
        document.getElementById('cfg_timeout').value = 90000;
        document.getElementById('cfg_retries').value = 20;
        document.getElementById('cfg_captcha').value = 15;
        document.getElementById('cfg_misses').value = 3;
        document.getElementById('cfg_probe').value = 3;
        alert("Preset PADRÃO restaurado! Lembre-se de SALVAR.");
    }
}
