let currentChart = null;
let latestRequestId = null;

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
    const warehouseHeadline = document.getElementById('warehouse-headline');
    const warehouseBadge = document.getElementById('warehouse-badge');
    const warehouseMode = document.getElementById('warehouse-mode');
    const warehouseTableCount = document.getElementById('warehouse-table-count');
    const warehouseQuality = document.getElementById('warehouse-quality');
    const warehouseAuditCount = document.getElementById('warehouse-audit-count');
    const warehouseLineage = document.getElementById('warehouse-lineage');
    const warehouseQualityChecks = document.getElementById('warehouse-quality-checks');
    const warehousePolicies = document.getElementById('warehouse-policies');
    const warehouseAuditFeed = document.getElementById('warehouse-audit-feed');

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

    function renderObjectList(container, items, formatter) {
        container.innerHTML = '';
        items.forEach((item) => {
            const listItem = document.createElement('li');
            listItem.className = 'brief-list-item';
            listItem.innerText = formatter(item);
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

    async function loadWarehouseBrief() {
        try {
            const response = await fetch('/api/runtime/warehouse-brief');
            if (!response.ok) {
                throw new Error(`Warehouse brief request failed with ${response.status}`);
            }

            const payload = await response.json();
            warehouseHeadline.innerText = payload.headline || 'Warehouse brief available.';
            warehouseBadge.innerText = (payload.status || 'unknown').toUpperCase();
            const evalSummary = payload.gold_eval_run?.summary || payload.gold_eval?.summary || {};
            warehouseMode.innerText = `${payload.warehouse_mode || 'Unavailable'} / ${payload.fallback_mode || 'unknown'}`;
            warehouseTableCount.innerText = `${(payload.table_profiles || []).length} tables / ${evalSummary.pass_count || 0}/${evalSummary.case_count || 0} evals`;
            warehouseQuality.innerText = (payload.quality_gate?.status || 'unknown').toUpperCase();
            warehouseAuditCount.innerText = `${payload.recent_audit_count || 0} requests`;

            renderObjectList(warehouseLineage, payload.lineage?.relationships || [], (item) =>
                `${item.from_table}.${item.from_column} -> ${item.to_table}.${item.to_column} (${item.semantic_role})`
            );
            renderObjectList(warehouseQualityChecks, payload.quality_gate?.checks || [], (item) =>
                `${item.name}: ${item.status.toUpperCase()} (${item.violations} violations)`
            );
            const policyRules = [
                ...(payload.policy?.deny_rules || []).map((item) => `DENY: ${item}`),
                ...(payload.policy?.review_rules || []).map((item) => `REVIEW: ${item}`),
                ...(payload.policy_examples || []).map((item) => `FLOW: ${item}`),
            ];
            renderReviewList(warehousePolicies, policyRules);
        } catch (error) {
            console.error(error);
            warehouseHeadline.innerText = 'Warehouse brief unavailable.';
            warehouseBadge.innerText = 'ERROR';
            warehouseMode.innerText = 'Unavailable';
            warehouseTableCount.innerText = 'Unavailable';
            warehouseQuality.innerText = 'Unavailable';
            warehouseAuditCount.innerText = 'Unavailable';
            renderReviewList(warehouseLineage, ['Lineage surface unavailable.']);
            renderReviewList(warehouseQualityChecks, ['Quality gate unavailable.']);
            renderReviewList(warehousePolicies, ['Policy examples unavailable.']);
            addLog('Failed to load warehouse brief surface.', 'error');
        }
    }

    async function loadQueryAuditFeed() {
        try {
            const response = await fetch('/api/query-audit/recent');
            if (!response.ok) {
                throw new Error(`Query audit request failed with ${response.status}`);
            }

            const payload = await response.json();
            const items = payload.items || [];
            if (items.length === 0) {
                renderReviewList(warehouseAuditFeed, ['No governed query requests recorded yet.']);
                warehouseAuditCount.innerText = '0 requests';
                return;
            }

            renderObjectList(warehouseAuditFeed, items, (item) => {
                const chartPart = item.chart_type ? ` | ${item.chart_type}` : '';
                const rowPart = Number.isFinite(item.row_count) ? ` | ${item.row_count} rows` : '';
                const policyPart = item.policy_decision ? ` | ${item.policy_decision}` : '';
                const fallbackPart = item.fallback_sql_used || item.fallback_chart_used ? ' | fallback' : '';
                return `${item.stage.toUpperCase()} | ${item.request_id}${policyPart}${chartPart}${rowPart}${fallbackPart} | ${item.question}`;
            });
            warehouseAuditCount.innerText = `${items.length} requests`;
        } catch (error) {
            console.error(error);
            renderReviewList(warehouseAuditFeed, ['Query audit feed unavailable.']);
            addLog('Failed to load query audit feed.', 'error');
        }
    }

    async function loadQueryAuditDetail(requestId) {
        if (!requestId) return;
        try {
            const response = await fetch(`/api/query-audit/${encodeURIComponent(requestId)}`);
            if (!response.ok) {
                throw new Error(`Query audit detail request failed with ${response.status}`);
            }

            const payload = await response.json();
            const latest = payload.latest || {};
            const policyDecision = latest.policy_decision || 'unknown';
            const fallback = latest.fallback_sql_used || latest.fallback_chart_used ? 'fallback=yes' : 'fallback=no';
            addLog(
                `Audit detail ${payload.request_id}: ${policyDecision.toUpperCase()} | ${latest.row_count || 0} rows | ${fallback}`,
                policyDecision === 'deny' ? 'error' : 'system'
            );
        } catch (error) {
            console.error(error);
            addLog('Failed to load query audit detail.', 'error');
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
        let askPayload;

        try {
            const askResponse = await fetch('/api/ask', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ question: query })
            });

            if (!askResponse.ok) {
                throw new Error(`Ask request failed with ${askResponse.status}`);
            }

            askPayload = await askResponse.json();
            latestRequestId = askPayload.request_id;
            addLog(`Audit Request ID: ${askPayload.request_id}`, 'system');
        } catch (error) {
            console.error(error);
            addLog('Failed to register governed query request.', 'error');
            askBtn.disabled = false;
            nlInput.disabled = false;
            askBtn.innerText = "EXECUTE";
            return;
        }

        // Connect to SSE Endpoint
        const eventSource = new EventSource(askPayload.stream_url);

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
                loadWarehouseBrief();
                loadQueryAuditFeed();
                loadQueryAuditDetail(latestRequestId);
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
            loadWarehouseBrief();
            loadQueryAuditFeed();
            loadQueryAuditDetail(latestRequestId);
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
    loadWarehouseBrief();
    loadQueryAuditFeed();
});
