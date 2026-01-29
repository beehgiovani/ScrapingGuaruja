// Advanced Statistics Calculation
let lastProcessed = 0;
let lastUpdateTime = Date.now();

function updateAdvancedStats(stats) {
    // Calculate processing speed (lotes/min)
    const now = Date.now();
    const timeDiff = (now - lastUpdateTime) / 1000 / 60; // minutes
    const processedDiff = stats.processed - lastProcessed;

    if (timeDiff > 0 && processedDiff > 0) {
        const speed = Math.round(processedDiff / timeDiff);
        document.getElementById('statsSpeed').innerText = speed;
    } else {
        document.getElementById('statsSpeed').innerText = '-';
    }

    lastProcessed = stats.processed;
    lastUpdateTime = now;

    // Count active workers
    const activeWorkers = stats.workers ? stats.workers.filter(w => w.status === 'running').length : 0;
    document.getElementById('statsActiveWorkers').innerText = activeWorkers;

    // Calculate error rate
    const errorRate = stats.total > 0 ? ((stats.errors / stats.total) * 100).toFixed(1) : '0.0';
    document.getElementById('statsErrorRate').innerText = errorRate + '%';

    // ---------------------------------------------------------
    // CÁLCULO DE ETA (REGRA DE 3 - PROJEÇÃO REAL)
    // ---------------------------------------------------------
    // Exemplo do usuário:
    // Total Lotes (Inputs): 51495 (stats.total)
    // Já Processados (Base): 23560 (stats.processed_inputs)
    // Total Gerado (Lotes + Sublotes): 48951 (stats.processed)
    //
    // Projeção Total = (stats.total * stats.processed) / stats.processed_inputs
    // ---------------------------------------------------------

    let estimatedTotalItems = stats.total; // Fallback

    if (stats.processed_inputs && stats.processed_inputs > 0) {
        // Regra de 3 para projetar o total final de itens (lotes + desmembramentos)
        estimatedTotalItems = (stats.total * stats.processed) / stats.processed_inputs;
    }

    const remainingItems = Math.max(0, estimatedTotalItems - stats.processed);

    // Speed é calculado em ITENS por minuto (baseado na diferença de stats.processed)
    if (remainingItems > 0 && processedDiff > 0 && timeDiff > 0) {
        let speed = processedDiff / timeDiff; // itens/min

        // Evitar divisão por zero ou speed muito baixo que distorça ETA
        if (speed < 0.1) speed = 0.1;

        const etaMinutes = remainingItems / speed;

        let etaStr = "";
        if (etaMinutes < 60) {
            etaStr = `${Math.round(etaMinutes)}m`;
        } else {
            const etaHours = Math.floor(etaMinutes / 60);
            const etaMins = Math.round(etaMinutes % 60);
            etaStr = `${etaHours}h ${etaMins}m`;
        }

        // Exibir ETA
        document.getElementById('statsETA').innerText = etaStr;

        // Opcional: Mostrar detalhes no title (tooltip)
        document.getElementById('statsETA').title = `Restam aprox ${Math.round(remainingItems)} de ${Math.round(estimatedTotalItems)} (proj)`;

    } else if (stats.processed_inputs >= stats.total && stats.total > 0) {
        document.getElementById('statsETA').innerText = 'Done';
    } else {
        // Se ainda não acabou (inputs < total) mas a previsão diz que já deveria (remaining <= 0),
        // mostra que está nos ajustes finais ou calculando
        document.getElementById('statsETA').innerText = 'Finalizing...';
        document.getElementById('statsETA').title = `Processados ${stats.processed_inputs} de ${stats.total} lotes base`;
    }

    // Proxy distribution (30 Webshare + 20 BrightData slots)
    document.getElementById('statsProxies').innerText = '30 WS + 20 BD';

    // Calculate data size (approximate from JSON files)
    // This would need server-side calculation, for now show placeholder
    document.getElementById('statsDataSize').innerText = '~' + Math.round(stats.success * 0.65) + ' MB';
}
