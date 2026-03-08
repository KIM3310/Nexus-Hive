let currentChart = null;

// Ensure prompt chip updates input
window.setPrompt = function (text) {
    document.getElementById('nl-input').value = text;
};

document.addEventListener('DOMContentLoaded', () => {
    const askBtn = document.getElementById('ask-btn');
    const nlInput = document.getElementById('nl-input');
    const agentLogs = document.getElementById('agent-logs');
    const emptyState = document.getElementById('empty-state');
    const canvas = document.getElementById('biChart');
    const briefHeadline = document.getElementById('brief-headline');
    const briefBadge = document.getElementById('brief-badge');
    const briefSchema = document.getElementById('brief-schema');
    const briefModel = document.getElementById('brief-model');
    const briefDbReady = document.getElementById('brief-db-ready');
    const briefRetryBudget = document.getElementById('brief-retry-budget');
    const briefReviewFlow = document.getElementById('brief-review-flow');
    const briefOperatorRules = document.getElementById('brief-operator-rules');
    const briefAgentContract = document.getElementById('brief-agent-contract');
    const briefWatchouts = document.getElementById('brief-watchouts');
    const reviewPackHeadline = document.getElementById('reviewpack-headline');
    const reviewPackBadge = document.getElementById('reviewpack-badge');
    const reviewPackReady = document.getElementById('reviewpack-ready');
    const reviewPackRoutes = document.getElementById('reviewpack-routes');
    const reviewPackSchema = document.getElementById('reviewpack-schema');
    const reviewPackRetry = document.getElementById('reviewpack-retry');
    const reviewPackPromises = document.getElementById('reviewpack-promises');
    const reviewPackBoundary = document.getElementById('reviewpack-boundary');
    const reviewPackSequence = document.getElementById('reviewpack-sequence');
    const reviewPackWatchouts = document.getElementById('reviewpack-watchouts');

    // Add CSS generic dark theme to Chart.js
    Chart.defaults.color = '#8b92a5';
    Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.05)';

    function addLog(message, type = 'system') {
        const div = document.createElement('div');
        div.className = `log-entry ${type}`;

        const timestamp = document.createElement('span');
        timestamp.className = 'timestamp';
        const d = new Date();
        timestamp.innerText = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;

        const content = document.createElement('p');
        content.innerText = message;

        div.appendChild(timestamp);
        div.appendChild(content);

        agentLogs.appendChild(div);
        agentLogs.scrollTop = agentLogs.scrollHeight;
    }

    function renderBriefList(container, items) {
        container.innerHTML = '';
        items.forEach((item) => {
            const listItem = document.createElement('li');
            listItem.className = 'brief-list-item';
            listItem.innerText = item;
            container.appendChild(listItem);
        });
    }

    function renderAgentContract(container, items) {
        container.innerHTML = '';
        items.forEach((item) => {
            const listItem = document.createElement('li');
            listItem.className = 'brief-list-item';
            listItem.innerText = `${item.agent}: ${item.responsibility}`;
            container.appendChild(listItem);
        });
    }

    function renderReviewList(container, items) {
        container.innerHTML = '';
        items.forEach((item) => {
            const listItem = document.createElement('li');
            listItem.className = 'brief-list-item';
            listItem.innerText = item;
            container.appendChild(listItem);
        });
    }

    async function loadRuntimeBrief() {
        try {
            const response = await fetch('/api/runtime/brief');
            if (!response.ok) {
                throw new Error(`Runtime brief request failed with ${response.status}`);
            }

            const payload = await response.json();
            const diagnostics = payload.diagnostics || {};
            const reportContract = payload.report_contract || {};
            const evidenceCounts = payload.evidence_counts || {};

            briefHeadline.innerText = payload.headline || 'Runtime brief available.';
            briefBadge.innerText = (payload.status || 'unknown').toUpperCase();
            briefSchema.innerText = reportContract.schema || 'Unavailable';
            briefModel.innerText = payload.model || 'Unavailable';
            briefDbReady.innerText = diagnostics.db_ready ? 'Ready' : 'Degraded';
            briefRetryBudget.innerText = `${evidenceCounts.retry_budget || 0} retries`;

            renderBriefList(briefReviewFlow, payload.review_flow || []);
            renderBriefList(briefOperatorRules, reportContract.operator_rules || []);
            renderAgentContract(briefAgentContract, payload.agent_contract || []);
            renderBriefList(briefWatchouts, payload.watchouts || []);
        } catch (error) {
            console.error(error);
            briefHeadline.innerText = 'Runtime brief unavailable.';
            briefBadge.innerText = 'ERROR';
            briefSchema.innerText = 'Unavailable';
            briefModel.innerText = 'Unavailable';
            briefDbReady.innerText = 'Unknown';
            briefRetryBudget.innerText = 'Unknown';
            renderBriefList(briefReviewFlow, ['Review /health and /api/meta when the backend becomes available.']);
            renderBriefList(briefOperatorRules, ['No runtime rules loaded.']);
            renderAgentContract(briefAgentContract, []);
            renderBriefList(briefWatchouts, ['The backend runtime brief could not be loaded.']);
            addLog('Failed to load runtime brief surface.', 'error');
        }
    }

    async function loadReviewPack() {
        try {
            const response = await fetch('/api/review-pack');
            if (!response.ok) {
                throw new Error(`Review pack request failed with ${response.status}`);
            }

            const payload = await response.json();
            const proofBundle = payload.proof_bundle || {};
            const answerContract = payload.answer_contract || {};

            reviewPackHeadline.innerText = payload.headline || 'Review pack available.';
            reviewPackBadge.innerText = (payload.status || 'unknown').toUpperCase();
            reviewPackReady.innerText = proofBundle.warehouse_ready ? 'Auditable' : 'Degraded';
            reviewPackRoutes.innerText = `${(proofBundle.review_routes || []).length} routes`;
            reviewPackSchema.innerText = answerContract.schema || 'Unavailable';
            reviewPackRetry.innerText = `${proofBundle.retry_budget || 0} retries`;

            renderReviewList(reviewPackPromises, payload.executive_promises || []);
            renderReviewList(reviewPackBoundary, payload.trust_boundary || []);
            renderReviewList(reviewPackSequence, payload.review_sequence || []);
            renderReviewList(reviewPackWatchouts, payload.watchouts || []);
        } catch (error) {
            console.error(error);
            reviewPackHeadline.innerText = 'Executive review pack unavailable.';
            reviewPackBadge.innerText = 'ERROR';
            reviewPackReady.innerText = 'Unknown';
            reviewPackRoutes.innerText = 'Unavailable';
            reviewPackSchema.innerText = 'Unavailable';
            reviewPackRetry.innerText = 'Unavailable';
            renderReviewList(reviewPackPromises, ['No executive promises loaded.']);
            renderReviewList(reviewPackBoundary, ['No trust boundary loaded.']);
            renderReviewList(reviewPackSequence, ['Review /api/runtime/brief and /api/meta when the backend becomes available.']);
            renderReviewList(reviewPackWatchouts, ['The backend review pack could not be loaded.']);
            addLog('Failed to load executive review pack surface.', 'error');
        }
    }

    function renderChart(configData, dbData) {
        if (!dbData || dbData.length === 0) {
            addLog("No records returned to visualize.", "error");
            return;
        }

        const labels = dbData.map(row => {
            const val = row[configData.labels_key];
            // Format if it looks like a number but is acting as a label (e.g., categories)
            return val;
        });

        const dataPoints = dbData.map(row => {
            const val = row[configData.data_key];
            return parseFloat(val) || 0;
        });

        if (currentChart) {
            currentChart.destroy();
        }

        emptyState.style.display = 'none';
        canvas.style.display = 'block';

        const ctx = canvas.getContext('2d');

        // Define an enterprise gradient
        let bgGradient = ctx.createLinearGradient(0, 0, 0, 400);
        bgGradient.addColorStop(0, 'rgba(94, 106, 210, 0.8)');
        bgGradient.addColorStop(1, 'rgba(94, 106, 210, 0.1)');

        let borderColors = '#5e6ad2';

        if (configData.type === 'pie' || configData.type === 'doughnut') {
            // Give pie charts distinct colors
            borderColors = '#20222b';
            bgGradient = [
                '#5e6ad2', '#2ecd71', '#e74c3c', '#f39c12', '#9b59b6', '#34495e'
            ];
        }

        currentChart = new Chart(ctx, {
            type: configData.type || 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: configData.data_key.replace(/_/g, ' ').toUpperCase(),
                    data: dataPoints,
                    backgroundColor: bgGradient,
                    borderColor: borderColors,
                    borderWidth: 2,
                    borderRadius: configData.type === 'bar' ? 4 : 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { font: { family: "'Inter', sans-serif" } }
                    },
                    title: {
                        display: true,
                        text: configData.title || 'Data Visualization',
                        font: { size: 16, weight: '600', family: "'Inter', sans-serif" },
                        color: '#f2f4f7'
                    }
                },
                scales: (configData.type !== 'pie' && configData.type !== 'doughnut') ? {
                    y: { beginAtZero: true }
                } : {}
            }
        });

        addLog(`Chart rendered successfully using ${dbData.length} data points.`, 'success');
    }

    async function executeQuery() {
        const query = nlInput.value.trim();
        if (!query) return;

        askBtn.disabled = true;
        nlInput.disabled = true;
        askBtn.innerText = "THINKING...";

        // Clear old state safely
        agentLogs.innerHTML = '';
        addLog(`User Query: "${query}"`, 'system');

        // Connect to SSE Endpoint
        const eventSource = new EventSource(`/api/stream?q=${encodeURIComponent(query)}`);

        eventSource.onmessage = function (event) {
            const data = JSON.parse(event.data);

            if (data.type === 'log') {
                let logType = 'running';
                if (data.content.includes("❌")) logType = 'error';
                else if (data.content.includes("✅")) logType = 'success';

                addLog(data.content, logType);
            }
            else if (data.type === 'chart_data') {
                // The AI finished execution and passed the Chart JS conf + raw data
                addLog("Compiling visual payload for dashboard...", "system");
                renderChart(data.config, data.data);
            }
            else if (data.type === 'done') {
                eventSource.close();
                askBtn.disabled = false;
                nlInput.disabled = false;
                nlInput.focus();
                askBtn.innerText = "EXECUTE";
            }
        };

        eventSource.onerror = function (err) {
            console.error("EventSource failed:", err);
            addLog("Lost connection to the LangGraph Hive Engine.", "error");
            eventSource.close();
            askBtn.disabled = false;
            nlInput.disabled = false;
            askBtn.innerText = "EXECUTE";
        };
    }

    askBtn.addEventListener('click', executeQuery);
    nlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') executeQuery();
    });
    loadRuntimeBrief();
    loadReviewPack();
});
