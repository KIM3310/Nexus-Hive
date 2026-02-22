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
});
