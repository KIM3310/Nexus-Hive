let currentChart = null;
let latestRequestId = null;
let latestAuditRequestId = null;
let latestAuditDetailPayload = null;
let latestReviewRoutes = [];
let latestGoldEvalPayload = null;
let latestSessionBoardPayload = null;
let recordedReviewActive = false;
let currentLens = 'analyst';

const REVIEW_LENSES = {
    analyst: {
        headline: 'Reviewer-first governed path',
        summary: 'Start with the approval board, then open the review board and audit detail before presenting any chart answer.',
        cards: [
            ['01 · Approval', 'Review-required SQL should stop at a human gate first.'],
            ['02 · Review', 'Use the review board for fallback-heavy or denied requests.'],
            ['03 · Audit', 'Copy the governed claim only after the audit trace is visible.'],
        ],
        actions: ['Copy Review Routes', 'Copy Governed Claim', 'Copy Review Bundle'],
    },
    reviewer: {
        headline: 'Human-review path for risky SQL',
        summary: 'Use this lens when the audience cares about policy verdicts, denied requests, and the trust boundary around fallback answers.',
        cards: [
            ['01 · Policy preview', 'Run or seed a denied query to show the review gate before execution.'],
            ['02 · Audit detail', 'Focus the latest audit so SQL, retries, and fallback flags stay visible.'],
            ['03 · Decision brief', 'Copy the query decision brief once the policy story is concrete.'],
        ],
        actions: ['Copy Query Decision Brief', 'Copy Latest Audit', 'Seed Denied SQL'],
    },
    executive: {
        headline: 'Executive BI proof path',
        summary: 'Lead with the governed claim, then use the gold eval summary and review bundle to explain why this workflow is safe to trust.',
        cards: [
            ['01 · Governed claim', 'Summarize readiness, schema, and current policy posture in one block.'],
            ['02 · Gold eval', 'Use the eval summary before talking about chart quality or rollout.'],
            ['03 · Review bundle', 'End with the bundle so the proof path is easy to replay later.'],
        ],
        actions: ['Copy Governed Claim', 'Copy Gold Eval', 'Copy Review Bundle'],
    },
};

const RECORDED_REVIEW = {
    runtimeBrief: {
        headline: 'Recorded runtime brief for a recruiter walkthrough.',
        status: 'recorded-review',
        report_contract: {
            schema: 'nexus-answer-v1',
            operator_rules: [
                'Keep policy preview visible before running or sharing SQL.',
                'Treat review-required output as human-held until the approval board is clear.',
                'Use the audit trail as proof, not a hidden implementation detail.',
            ],
        },
        model: 'phi3-local + deterministic fallback',
        diagnostics: { db_ready: true },
        evidence_counts: { retry_budget: 1 },
        review_flow: [
            'Open /health and /api/runtime/brief to confirm local demo posture.',
            'Use /api/query-approval-board before presenting any review-required SQL as execution-ready.',
            'Read /api/query-review-board for fallback-heavy or denied requests before the chart deck.',
        ],
        agent_contract: [
            { agent: 'Planner', responsibility: 'Translate the business question into a governed SQL intent.' },
            { agent: 'Policy', responsibility: 'Block or escalate risky SQL before execution.' },
            { agent: 'Reviewer', responsibility: 'Package answer, chart, and audit trace into one shareable decision surface.' },
        ],
        watchouts: [
            'Recorded mode proves the workflow shape, not live infra latency.',
            'Any review-required SQL still needs explicit approval before external sharing.',
        ],
    },
    reviewPack: {
        headline: 'Recorded executive pack with approval, audit, and proof surfaces already stitched together.',
        status: 'recorded-review',
        proof_bundle: {
            warehouse_ready: true,
            review_routes: [
                '/health',
                '/api/runtime/brief',
                '/api/query-approval-board',
                '/api/query-review-board',
            ],
            retry_budget: 1,
        },
        answer_contract: { schema: 'nexus-answer-v1' },
        executive_promises: [
            'Every chart is paired with auditable SQL and a request ID.',
            'Review-required SQL is isolated before it can look production-safe.',
        ],
        proof_assets: [
            { label: 'Approval Board', href: '/api/query-approval-board' },
            { label: 'Review Board', href: '/api/query-review-board' },
            { label: 'Gold Eval Run', href: '/api/evals/nl2sql-gold/run' },
        ],
        trust_boundary: [
            'Warehouse access stays local to the governed runtime.',
            'Fallback answers stay visibly marked in the audit trail.',
        ],
        two_minute_review: [
            'Check the approval board first.',
            'Open the review board for denied or fallback-heavy requests.',
            'Use the gold eval summary before claiming governed quality.',
        ],
        review_sequence: [
            'Approval board -> review board -> audit detail -> chart answer.',
        ],
        watchouts: [
            'Recorded mode is meant for proof of workflow, not live latency claims.',
        ],
    },
    warehouseBrief: {
        headline: 'Recorded warehouse posture with lineage, quality gates, and recent audits.',
        status: 'recorded-review',
        warehouse_mode: 'sqlite demo warehouse',
        fallback_mode: 'heuristic answer fallback',
        table_profiles: [{}, {}, {}],
        gold_eval_run: { summary: { pass_count: 4, case_count: 4 } },
        quality_gate: {
            status: 'pass',
            checks: [
                { name: 'freshness', status: 'pass', violations: 0 },
                { name: 'null spikes', status: 'pass', violations: 0 },
                { name: 'role-filter coverage', status: 'pass', violations: 0 },
            ],
        },
        recent_audit_count: 6,
        lineage: {
            relationships: [
                { from_table: 'orders', from_column: 'merchant_id', to_table: 'merchants', to_column: 'merchant_id', semantic_role: 'lookup' },
                { from_table: 'orders', from_column: 'created_at', to_table: 'calendar', to_column: 'date_key', semantic_role: 'time' },
            ],
        },
        policy: {
            deny_rules: ['Block wildcard SELECT on viewer role.'],
            review_rules: ['Escalate finance joins that include restricted margin columns.'],
        },
        policy_examples: [
            'FLOW: approval board routes review-required SQL to a human gate.',
            'FLOW: review board groups fallback-heavy answers before chart sharing.',
        ],
    },
    queryAuditFeed: {
        items: [
            {
                request_id: 'req-recorded-1042',
                stage: 'review',
                policy_decision: 'review',
                chart_type: 'bar',
                row_count: 4,
                fallback_sql_used: false,
                fallback_chart_used: false,
                question: 'Which region saw the highest Q4 revenue dip?',
            },
            {
                request_id: 'req-recorded-1037',
                stage: 'deny',
                policy_decision: 'deny',
                chart_type: null,
                row_count: 0,
                fallback_sql_used: false,
                fallback_chart_used: false,
                question: 'Show every customer email tied to high-value orders.',
            },
        ],
    },
    querySessionBoard: {
        summary: {
            total_sessions: 3,
            ready_count: 1,
            attention_count: 1,
            review_count: 1,
            compare_count: 1,
        },
        items: [
            {
                request_id: 'req-recorded-1042',
                session_state: 'review',
                chart_type: 'bar',
                fallback_mode: { sql: false, chart: false },
                headline: 'Revenue dip answer is ready for approval review.',
            },
            {
                request_id: 'req-recorded-1037',
                session_state: 'attention',
                chart_type: null,
                fallback_mode: { sql: false, chart: false },
                headline: 'Restricted PII request was blocked before execution.',
            },
        ],
    },
    auditDetails: {
        'req-recorded-1042': {
            request_id: 'req-recorded-1042',
            latest: {
                request_id: 'req-recorded-1042',
                policy_decision: 'review',
                stage: 'review',
                row_count: 4,
                retry_count: 1,
                chart_type: 'bar',
                fallback_sql_used: false,
                fallback_chart_used: false,
                sql_query: "SELECT region, revenue_delta FROM regional_revenue WHERE quarter = 'Q4' ORDER BY revenue_delta ASC LIMIT 5",
                next_action: 'Open the approval board and sign off before external sharing.',
            },
            history: [{}, {}],
        },
    },
    goldEval: {
        summary: { case_count: 4, pass_count: 4, fail_count: 0 },
        items: [
            { question: 'Q4 revenue dip by region', status: 'pass', missing_features: [] },
            { question: 'Approval-required finance join', status: 'pass', missing_features: [] },
        ],
    },
};

// Ensure prompt chip updates input
window.setPrompt = function (text) {
    document.getElementById('nl-input').value = text;
};

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-prompt]').forEach((button) => {
        button.addEventListener('click', () => window.setPrompt(button.dataset.prompt || ''));
    });
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
    const storyboardHeadline = document.getElementById('storyboard-headline');
    const storyboardBadge = document.getElementById('storyboard-badge');
    const storyboardApproval = document.getElementById('storyboard-approval');
    const storyboardChart = document.getElementById('storyboard-chart');
    const storyboardSessions = document.getElementById('storyboard-sessions');
    const storyboardRoutes = document.getElementById('storyboard-routes');
    const storyboardClaim = document.getElementById('storyboard-claim');
    const storyboardAudit = document.getElementById('storyboard-audit');
    const storyboardNext = document.getElementById('storyboard-next');
    const policyRoleSelect = document.getElementById('policy-role-select');
    const policySqlInput = document.getElementById('policy-sql-input');
    const policyCheckBtn = document.getElementById('policy-check-btn');
    const useLatestSqlBtn = document.getElementById('use-latest-sql-btn');
    const copyReviewRoutesBtn = document.getElementById('copy-review-routes-btn');
    const copyGovernedClaimBtn = document.getElementById('copy-governed-claim-btn');
    const copyQueryDecisionBtn = document.getElementById('copy-query-decision-btn');
    const copyReviewBundleBtn = document.getElementById('copy-review-bundle-btn');
    const copyLatestAuditBtn = document.getElementById('copy-latest-audit-btn');
    const focusLatestAuditBtn = document.getElementById('focus-latest-audit-btn');
    const seedDeniedSqlBtn = document.getElementById('seed-denied-sql-btn');
    const copyGoldEvalBtn = document.getElementById('copy-gold-eval-btn');
    const governanceHotkeys = document.getElementById('governanceHotkeys');
    const priorityHeadline = document.getElementById('priority-headline');
    const priorityBadge = document.getElementById('priority-badge');
    const prioritySummary = document.getElementById('priority-summary');
    const priorityRequest = document.getElementById('priority-request');
    const priorityMode = document.getElementById('priority-mode');
    const priorityApproval = document.getElementById('priority-approval');
    const priorityNext = document.getElementById('priority-next');
    const priorityFreshness = document.getElementById('priority-freshness');
    const priorityStaleness = document.getElementById('priority-staleness');
    const priorityQuestion = document.getElementById('priority-question');
    const priorityRoute = document.getElementById('priority-route');
    const priorityChart = document.getElementById('priority-chart');
    const priorityTrace = document.getElementById('priority-trace');
    const priorityProofNote = document.getElementById('priority-proof-note');
    const priorityTraceNote = document.getElementById('priority-trace-note');
    const priorityFlow = document.getElementById('priority-flow');
    const lensHeadline = document.getElementById('lens-headline');
    const lensSummary = document.getElementById('lens-summary');
    const lensGrid = document.getElementById('lens-grid');
    const lensAnalystBtn = document.getElementById('lens-analyst-btn');
    const lensReviewerBtn = document.getElementById('lens-reviewer-btn');
    const lensExecutiveBtn = document.getElementById('lens-executive-btn');
    const lensPrimaryBtn = document.getElementById('lens-primary-btn');
    const lensSecondaryBtn = document.getElementById('lens-secondary-btn');
    const lensTertiaryBtn = document.getElementById('lens-tertiary-btn');
    const policyVerdict = document.getElementById('policy-verdict');
    const runGoldEvalBtn = document.getElementById('run-gold-eval-btn');
    const goldEvalSummary = document.getElementById('gold-eval-summary');
    const goldEvalFailures = document.getElementById('gold-eval-failures');
    const auditDetail = document.getElementById('audit-detail');
    const sessionBoardSummary = document.getElementById('session-board-summary');
    const sessionBoardList = document.getElementById('session-board-list');
    const statusText = document.getElementById('status-text');

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

    function activateRecordedReview(reason = 'review surfaces') {
        if (statusText) {
            statusText.innerText = 'Recorded review only';
        }
        if (recordedReviewActive) {
            return;
        }
        recordedReviewActive = true;
        addLog(`Backend unavailable. Loaded recorded reviewer flow for ${reason}.`, 'success');
        renderReviewerPriority();
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

    function renderDetailCard(container, lines) {
        container.innerHTML = '';
        lines.forEach((line) => {
            const div = document.createElement('div');
            div.className = 'detail-line';
            div.innerText = line;
            container.appendChild(div);
        });
    }

    function formatAuditTimestamp(value) {
        if (!value) return 'Awaiting audit timestamp';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return String(value);
        return parsed.toISOString().replace('.000Z', 'Z');
    }

    function describeAuditFreshness(value) {
        if (!value) {
            return {
                freshness: 'Awaiting audit timestamp',
                note: 'Proof freshness should stay visible before any governed chart is shared.',
            };
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return {
                freshness: `Audit updated ${String(value)}`,
                note: 'Use the approval board and audit detail together before chart sharing.',
            };
        }
        const ageMinutes = Math.max(0, Math.round((Date.now() - parsed.getTime()) / 60000));
        if (ageMinutes <= 15) {
            return {
                freshness: `Audit updated ${formatAuditTimestamp(value)} · fresh`,
                note: 'Fresh audit detail is visible. Keep this request ID attached through approval, chart, and audit.',
            };
        }
        if (ageMinutes <= 60) {
            return {
                freshness: `Audit updated ${formatAuditTimestamp(value)} · ${ageMinutes}m old`,
                note: 'Audit detail is aging. Re-open the approval board before reusing this chart externally.',
            };
        }
        return {
            freshness: `Audit updated ${formatAuditTimestamp(value)} · stale`,
            note: 'Audit detail is stale. Refresh the governed request before sharing any chart claim.',
        };
    }


    function describeTraceContinuity() {
        const history = Array.isArray(latestAuditDetailPayload?.history) ? latestAuditDetailPayload.history : [];
        const latest = latestAuditDetailPayload?.latest || {};
        const retryCount = Number(latest.retry_count || 0);
        if (!history.length && !latest.request_id) {
            return {
                summary: 'Awaiting audit depth',
                note: 'Trace continuity keeps retries and audit depth attached to the same request.',
            };
        }
        const eventCount = Math.max(history.length, latest.request_id ? 1 : 0);
        return {
            summary: `${eventCount} audit events · ${retryCount} retries`,
            note: latest.request_id
                ? 'Trace continuity is live. Keep this same request ID attached through approval, chart, and audit.'
                : 'Trace continuity keeps retries and audit depth attached to the same request.',
        };
    }

    function renderReviewerPriority() {
        const latest = latestAuditDetailPayload?.latest || {};
        const reviewPack = RECORDED_REVIEW.reviewPack;
        const reviewRoutes = latestReviewRoutes.length > 0
            ? latestReviewRoutes
            : (reviewPack.proof_bundle?.review_routes || []);
        const approvalDecision = String(latest.policy_decision || 'review').replace(/-/g, ' ').toUpperCase();
        const effectiveRequestId = latest.request_id || latestAuditRequestId || latestRequestId || 'Awaiting request';
        const modeLabel = recordedReviewActive
            ? 'Recorded workflow only'
            : 'Live endpoint evidence';
        const nextAction = latest.next_action
            || (approvalDecision === 'DENY'
                ? 'Keep the denied request on the approval board until blocked SQL is rewritten.'
                : latest.request_id
                    ? 'Keep this request ID attached through approval, chart, and audit before sharing.'
                    : 'Run ask, then focus approval before chart sharing.');
        const hasChart = Boolean(latest.chart_type);
        const hasAudit = Boolean(latest.request_id);
        const stepStates = {
            ask: Boolean(latestRequestId || latestAuditRequestId),
            approve: hasAudit,
            chart: hasChart,
            audit: hasAudit,
        };

        priorityHeadline.innerText = recordedReviewActive
            ? 'Keep one recorded request visible from ask to approval to chart to audit.'
            : 'Keep one live request visible from ask to approval to chart to audit.';
        if (statusText) {
            statusText.innerText = recordedReviewActive
                ? 'Recorded review only'
                : (latest.request_id ? 'Live request in review' : 'Waiting for governed proof');
        }
        priorityBadge.innerText = recordedReviewActive ? 'RECORDED REVIEW' : 'LIVE REVIEW';
        prioritySummary.innerText = recordedReviewActive
            ? 'Recorded mode shows the reviewer flow shape with one request thread. Do not treat it as live warehouse runtime evidence.'
            : 'Use one request ID as the continuity anchor so approval posture, chart output, and audit proof stay on the same top-fold story.';
        const questionLane = latest.question || latestAuditDetailPayload?.question || 'Run a governed question or focus a recorded audit request.';
        const chartPosture = latest.chart_type
            ? `${latest.chart_type} · ${latest.row_count || 0} rows kept on the same request.`
            : 'Awaiting governed answer';
        const routePreview = `${reviewRoutes[0] || '/api/query-approval-board'} → ${reviewRoutes[1] || '/api/query-review-board'} → ${reviewRoutes[2] || '/api/query-audit/{request_id}'}`;

        priorityRequest.innerText = effectiveRequestId;
        priorityMode.innerText = modeLabel;
        priorityApproval.innerText = approvalDecision;
        priorityNext.innerText = nextAction;
        const freshness = describeAuditFreshness(latest.updated_at || latest.generated_at || null);
        if (priorityFreshness) priorityFreshness.innerText = freshness.freshness;
        if (priorityQuestion) priorityQuestion.innerText = questionLane;
        if (priorityRoute) priorityRoute.innerText = routePreview;
        if (priorityChart) priorityChart.innerText = chartPosture;
        const trace = describeTraceContinuity();
        if (priorityTrace) priorityTrace.innerText = trace.summary;
        priorityProofNote.innerText = recordedReviewActive
            ? 'Recorded review mode demonstrates workflow shape only. Treat live warehouse and runtime claims as valid only when the related endpoints answer successfully.'
            : `Live proof path: ${routePreview}.`;
        if (priorityStaleness) {
            priorityStaleness.innerText = recordedReviewActive
                ? 'Proof freshness should stay visible before any governed chart is shared.'
                : freshness.note;
        }
        if (priorityTraceNote) {
            priorityTraceNote.innerText = recordedReviewActive
                ? 'Trace continuity keeps retries and audit depth attached to the same request.'
                : trace.note;
        }

        priorityFlow?.querySelectorAll('.priority-step').forEach((step) => {
            const stepName = step.getAttribute('data-step');
            step.classList.remove('active', 'complete');
            if (stepName && stepStates[stepName]) {
                step.classList.add('complete');
            }
        });

        if (!stepStates.ask) {
            priorityFlow?.querySelector('[data-step="ask"]')?.classList.add('active');
        } else if (!stepStates.chart) {
            priorityFlow?.querySelector('[data-step="approve"]')?.classList.add('active');
        } else {
            priorityFlow?.querySelector('[data-step="audit"]')?.classList.add('active');
        }
    }

    function renderStoryboard() {
        const reviewPack = RECORDED_REVIEW.reviewPack;
        const latest = latestAuditDetailPayload?.latest || {};
        const sessionSummary = latestSessionBoardPayload?.summary || {};
        const evalSummary = latestGoldEvalPayload?.summary || {};
        const reviewRoutes = latestReviewRoutes.length > 0
            ? latestReviewRoutes
            : (reviewPack.proof_bundle?.review_routes || []);
        const effectiveRequestId = latest.request_id || latestAuditRequestId || 'review-pending';
        const approvalDecision = String(latest.policy_decision || 'review').replace(/-/g, ' ').toUpperCase();
        const chartState = latest.chart_type
            ? `${latest.chart_type} · ${latest.row_count || 0} rows`
            : 'Awaiting focused request';
        const compareCount = sessionSummary.compare_count || 0;
        const reviewCount = sessionSummary.review_count || 0;
        const nextAction = latest.next_action
            || (approvalDecision === 'DENY'
                ? 'Keep the request on the approval board until the blocked SQL is rewritten.'
                : 'Open the audit detail and query review board before sharing the chart claim.');
        const fallbackLabel = latest.fallback_sql_used || latest.fallback_chart_used ? 'Fallback path used' : 'Fallback not used';

        storyboardHeadline.innerText = recordedReviewActive
            ? 'Follow one recorded governed chart story from approval gate to audit trace before you present the answer.'
            : 'Follow the current governed chart story from approval gate to audit trace before you present the answer.';
        storyboardBadge.innerText = recordedReviewActive ? 'RECORDED STORY' : 'LIVE STORY';
        storyboardApproval.innerText = approvalDecision;
        storyboardChart.innerText = chartState;
        storyboardSessions.innerText = `${reviewCount} review · ${compareCount} compare`;
        storyboardRoutes.innerText = `${reviewRoutes.length} routes`;

        renderDetailCard(storyboardClaim, [
            `Request ID: ${effectiveRequestId}`,
            `Question lane: ${latest.question || 'Use the latest audit or gold eval example.'}`,
            `Claim posture: ${approvalDecision === 'DENY' ? 'blocked before chart sharing' : 'approval trace stays attached to the chart claim'}`,
        ]);
        renderDetailCard(storyboardAudit, [
            `Audit proof: ${fallbackLabel}`,
            `Gold eval: ${evalSummary.pass_count ?? 0}/${evalSummary.case_count ?? 0} cases`,
            `Session posture: ${compareCount > 0 ? 'compare lane available for reviewer replay' : 'single governed path focused'}`,
        ]);
        renderDetailCard(storyboardNext, [
            `Next reviewer move: ${nextAction}`,
            `Fast path: ${(reviewRoutes[0] || '/api/query-approval-board')} → ${(reviewRoutes[1] || '/api/query-review-board')} → ${(reviewRoutes[2] || '/api/evals/nl2sql-gold/run')}`,
            recordedReviewActive
                ? 'Recorded mode proves approval, audit, and chart storytelling without claiming live warehouse latency.'
                : 'Live mode should still keep the approval board and audit trace visible before external sharing.',
        ]);
        renderReviewerPriority();
    }

    async function copyTextToClipboard(text) {
        if (!text) return false;
        try {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch {
            // Fallback below.
        }

        try {
            const temp = document.createElement('textarea');
            temp.value = text;
            temp.style.position = 'fixed';
            temp.style.opacity = '0';
            document.body.appendChild(temp);
            temp.focus();
            temp.select();
            const success = document.execCommand('copy');
            document.body.removeChild(temp);
            return Boolean(success);
        } catch {
            return false;
        }
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
            briefBadge.innerText = String(payload.status || 'review-pending')
                .replace(/-/g, ' ')
                .toUpperCase();
            briefSchema.innerText = reportContract.schema || 'Unavailable';
            briefModel.innerText = payload.model || 'Unavailable';
            briefDbReady.innerText = diagnostics.db_ready ? 'Ready' : 'Degraded';
            briefRetryBudget.innerText = `${evidenceCounts.retry_budget || 0} retries`;

            renderBriefList(briefReviewFlow, payload.review_flow || []);
            renderBriefList(briefOperatorRules, reportContract.operator_rules || []);
            renderAgentContract(briefAgentContract, payload.agent_contract || []);
            renderBriefList(briefWatchouts, [...(payload.watchouts || []), 'Live runtime evidence is valid only when these endpoints respond in the current session.']);
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.runtimeBrief;
            activateRecordedReview('runtime brief');
            const diagnostics = payload.diagnostics || {};
            const reportContract = payload.report_contract || {};
            const evidenceCounts = payload.evidence_counts || {};
            briefHeadline.innerText = payload.headline;
            briefBadge.innerText = 'RECORDED';
            briefSchema.innerText = reportContract.schema || 'Unavailable';
            briefModel.innerText = payload.model || 'Unavailable';
            briefDbReady.innerText = diagnostics.db_ready ? 'Ready' : 'Degraded';
            briefRetryBudget.innerText = `${evidenceCounts.retry_budget || 0} retries`;
            renderBriefList(briefReviewFlow, payload.review_flow || []);
            renderBriefList(briefOperatorRules, reportContract.operator_rules || []);
            renderAgentContract(briefAgentContract, payload.agent_contract || []);
            renderBriefList(briefWatchouts, [...(payload.watchouts || []), 'Recorded mode demonstrates workflow shape, not live warehouse latency or freshness.']);
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
            const proofAssets = (payload.proof_assets || []).map((item) =>
                `Proof: ${item.label} -> ${item.href || item.path || '-'}`
            );
            const twoMinuteReview = (payload.two_minute_review || []).map((item) => `2-minute: ${item}`);
            latestReviewRoutes = proofBundle.review_routes || [];

            reviewPackHeadline.innerText = payload.headline || 'Review pack available.';
            reviewPackBadge.innerText = String(payload.status || 'review-pending')
                .replace(/-/g, ' ')
                .toUpperCase();
            reviewPackReady.innerText = proofBundle.warehouse_ready ? 'Auditable' : 'Degraded';
            reviewPackRoutes.innerText = `${(proofBundle.review_routes || []).length} routes`;
            reviewPackSchema.innerText = answerContract.schema || 'Unavailable';
            reviewPackRetry.innerText = `${proofBundle.retry_budget || 0} retries`;

            renderReviewList(reviewPackPromises, [...(payload.executive_promises || []), ...proofAssets]);
            renderReviewList(reviewPackBoundary, payload.trust_boundary || []);
            renderReviewList(reviewPackSequence, [...twoMinuteReview, ...(payload.review_sequence || [])]);
            renderReviewList(reviewPackWatchouts, [...(payload.watchouts || []), 'Keep one request ID attached through approval, chart, and audit when presenting this pack.']);
            renderStoryboard();
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.reviewPack;
            activateRecordedReview('review pack');
            const proofBundle = payload.proof_bundle || {};
            const answerContract = payload.answer_contract || {};
            const proofAssets = (payload.proof_assets || []).map((item) =>
                `Proof: ${item.label} -> ${item.href || item.path || '-'}`
            );
            const twoMinuteReview = (payload.two_minute_review || []).map((item) => `2-minute: ${item}`);
            latestReviewRoutes = proofBundle.review_routes || [];
            reviewPackHeadline.innerText = payload.headline;
            reviewPackBadge.innerText = 'RECORDED';
            reviewPackReady.innerText = proofBundle.warehouse_ready ? 'Auditable' : 'Degraded';
            reviewPackRoutes.innerText = `${(proofBundle.review_routes || []).length} routes`;
            reviewPackSchema.innerText = answerContract.schema || 'Unavailable';
            reviewPackRetry.innerText = `${proofBundle.retry_budget || 0} retries`;
            renderReviewList(reviewPackPromises, [...(payload.executive_promises || []), ...proofAssets]);
            renderReviewList(reviewPackBoundary, payload.trust_boundary || []);
            renderReviewList(reviewPackSequence, [...twoMinuteReview, ...(payload.review_sequence || [])]);
            renderReviewList(reviewPackWatchouts, [...(payload.watchouts || []), 'Recorded review pack shows workflow shape only; avoid implying live warehouse execution.']);
            renderStoryboard();
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
            const payload = RECORDED_REVIEW.warehouseBrief;
            activateRecordedReview('warehouse brief');
            const evalSummary = payload.gold_eval_run?.summary || payload.gold_eval?.summary || {};
            warehouseHeadline.innerText = payload.headline;
            warehouseBadge.innerText = 'RECORDED';
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

            latestAuditRequestId = items[0].request_id || latestAuditRequestId;
            warehouseAuditFeed.innerHTML = '';
            items.forEach((item) => {
                const chartPart = item.chart_type ? ` | ${item.chart_type}` : '';
                const rowPart = Number.isFinite(item.row_count) ? ` | ${item.row_count} rows` : '';
                const policyPart = item.policy_decision ? ` | ${item.policy_decision}` : '';
                const fallbackPart = item.fallback_sql_used || item.fallback_chart_used ? ' | fallback' : '';
                const listItem = document.createElement('li');
                listItem.className = 'brief-list-item interactive-item';
                listItem.innerText = `${item.stage.toUpperCase()} | ${item.request_id}${policyPart}${chartPart}${rowPart}${fallbackPart} | ${item.question}`;
                listItem.addEventListener('click', () => {
                    loadQueryAuditDetail(item.request_id);
                });
                warehouseAuditFeed.appendChild(listItem);
            });
            warehouseAuditCount.innerText = `${items.length} requests`;
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.queryAuditFeed;
            activateRecordedReview('query audit feed');
            const items = payload.items || [];
            latestAuditRequestId = items[0]?.request_id || latestAuditRequestId;
            warehouseAuditFeed.innerHTML = '';
            items.forEach((item) => {
                const chartPart = item.chart_type ? ` | ${item.chart_type}` : '';
                const rowPart = Number.isFinite(item.row_count) ? ` | ${item.row_count} rows` : '';
                const policyPart = item.policy_decision ? ` | ${item.policy_decision}` : '';
                const fallbackPart = item.fallback_sql_used || item.fallback_chart_used ? ' | fallback' : '';
                const listItem = document.createElement('li');
                listItem.className = 'brief-list-item interactive-item';
                listItem.innerText = `${item.stage.toUpperCase()} | ${item.request_id}${policyPart}${chartPart}${rowPart}${fallbackPart} | ${item.question}`;
                listItem.addEventListener('click', () => {
                    loadQueryAuditDetail(item.request_id);
                });
                warehouseAuditFeed.appendChild(listItem);
            });
            warehouseAuditCount.innerText = `${items.length} requests`;
        }
    }

    async function loadQuerySessionBoard() {
        try {
            const response = await fetch('/api/query-session-board?limit=6');
            if (!response.ok) {
                throw new Error(`Query session board request failed with ${response.status}`);
            }

            const payload = await response.json();
            latestSessionBoardPayload = payload;
            const summary = payload.summary || {};
            const items = payload.items || [];
            renderDetailCard(sessionBoardSummary, [
                `Sessions: ${summary.total_sessions || 0}`,
                `Ready: ${summary.ready_count || 0}`,
                `Attention: ${summary.attention_count || 0}`,
                `Review: ${summary.review_count || 0}`,
                `Compare: ${summary.compare_count || 0}`,
            ]);

            if (items.length === 0) {
                renderReviewList(sessionBoardList, ['No saved governed sessions yet. Run a question to capture one.']);
                return;
            }

            sessionBoardList.innerHTML = '';
            items.forEach((item) => {
                const fallbackPart = item.fallback_mode?.sql || item.fallback_mode?.chart ? ' | fallback' : '';
                const chartPart = item.chart_type ? ` | ${item.chart_type}` : '';
                const listItem = document.createElement('li');
                listItem.className = 'brief-list-item interactive-item';
                listItem.innerText = `${String(item.session_state || 'unknown').toUpperCase()} | ${item.request_id}${chartPart}${fallbackPart} | ${item.headline}`;
                listItem.addEventListener('click', () => {
                    loadQueryAuditDetail(item.request_id);
                });
                sessionBoardList.appendChild(listItem);
            });
            renderStoryboard();
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.querySessionBoard;
            activateRecordedReview('saved sessions');
            latestSessionBoardPayload = payload;
            const summary = payload.summary || {};
            const items = payload.items || [];
            renderDetailCard(sessionBoardSummary, [
                `Sessions: ${summary.total_sessions || 0}`,
                `Ready: ${summary.ready_count || 0}`,
                `Attention: ${summary.attention_count || 0}`,
                `Review: ${summary.review_count || 0}`,
                `Compare: ${summary.compare_count || 0}`,
            ]);
            sessionBoardList.innerHTML = '';
            items.forEach((item) => {
                const fallbackPart = item.fallback_mode?.sql || item.fallback_mode?.chart ? ' | fallback' : '';
                const chartPart = item.chart_type ? ` | ${item.chart_type}` : '';
                const listItem = document.createElement('li');
                listItem.className = 'brief-list-item interactive-item';
                listItem.innerText = `${String(item.session_state || 'unknown').toUpperCase()} | ${item.request_id}${chartPart}${fallbackPart} | ${item.headline}`;
                listItem.addEventListener('click', () => {
                    loadQueryAuditDetail(item.request_id);
                });
                sessionBoardList.appendChild(listItem);
            });
            renderStoryboard();
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
            latestAuditDetailPayload = payload;
            latestAuditRequestId = payload.request_id;
            if (latest.sql_query) {
                policySqlInput.value = latest.sql_query;
            }
            renderDetailCard(auditDetail, [
                `Request ID: ${payload.request_id}`,
                `Decision: ${String(policyDecision || 'review-pending').replace(/-/g, ' ').toUpperCase()}`,
                `Stage: ${String(latest.stage || 'not-run').replace(/-/g, ' ').toUpperCase()}`,
                `Rows: ${latest.row_count || 0}`,
                `Retries: ${latest.retry_count || 0}`,
                `Chart: ${latest.chart_type || 'n/a'}`,
                `Fallback: ${fallback}`,
                `SQL: ${latest.sql_query || 'not captured yet'}`,
            ]);
            addLog(
                `Audit detail ${payload.request_id}: ${policyDecision.toUpperCase()} | ${latest.row_count || 0} rows | ${fallback}`,
                policyDecision === 'deny' ? 'error' : 'system'
            );
            renderStoryboard();
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.auditDetails[requestId];
            if (!payload) {
                latestAuditDetailPayload = null;
                addLog('Failed to load query audit detail.', 'error');
                renderDetailCard(auditDetail, ['Audit detail unavailable.']);
                renderStoryboard();
                return;
            }
            activateRecordedReview('audit detail');
            const latest = payload.latest || {};
            const history = payload.history || [];
            latestAuditDetailPayload = payload;
            latestAuditRequestId = payload.request_id;
            if (latest.sql_query) {
                policySqlInput.value = latest.sql_query;
            }
            renderDetailCard(auditDetail, [
                `Request ID: ${payload.request_id}`,
                `Decision: ${String(latest.policy_decision || 'review-pending').replace(/-/g, ' ').toUpperCase()}`,
                `Stage: ${String(latest.stage || 'not-run').replace(/-/g, ' ').toUpperCase()}`,
                `Rows: ${latest.row_count || 0}`,
                `Retries: ${latest.retry_count || 0}`,
                `Chart: ${latest.chart_type || 'n/a'}`,
                `Fallback: ${latest.fallback_sql_used || latest.fallback_chart_used ? 'fallback=yes' : 'fallback=no'}`,
                `SQL: ${latest.sql_query || 'not captured yet'}`,
            ]);
            renderStoryboard();
        }
    }

    async function runPolicyCheck() {
        const sql = policySqlInput.value.trim();
        const role = policyRoleSelect.value;
        if (!sql) {
            renderDetailCard(policyVerdict, ['Enter SQL or load the latest audited query first.']);
            return;
        }

        policyCheckBtn.disabled = true;
        policyCheckBtn.innerText = 'CHECKING...';
        try {
            const response = await fetch('/api/policy/check', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ sql, role })
            });
            if (!response.ok) {
                throw new Error(`Policy check failed with ${response.status}`);
            }
            const payload = await response.json();
            const verdict = payload.verdict || {};
            const reasons = [
                ...(verdict.deny_reasons || []).map((item) => `DENY: ${item}`),
                ...(verdict.review_reasons || []).map((item) => `REVIEW: ${item}`),
            ];
            renderDetailCard(policyVerdict, [
                `Role: ${(verdict.role || role).toUpperCase()}`,
                `Decision: ${(verdict.decision || 'unknown').toUpperCase()}`,
                ...(reasons.length ? reasons : ['ALLOW: no policy blockers triggered']),
            ]);
            addLog(`Policy preview ${String(verdict.decision || 'unknown').toUpperCase()} for role ${role}.`, verdict.decision === 'deny' ? 'error' : 'system');
        } catch (error) {
            console.error(error);
            renderDetailCard(policyVerdict, ['Policy check unavailable.']);
            addLog('Failed to run policy preview.', 'error');
        } finally {
            policyCheckBtn.disabled = false;
            policyCheckBtn.innerText = 'Run Policy Check';
        }
    }

    async function loadGoldEvalRun() {
        runGoldEvalBtn.disabled = true;
        runGoldEvalBtn.innerText = 'RUNNING...';
        try {
            const response = await fetch('/api/evals/nl2sql-gold/run');
            if (!response.ok) {
                throw new Error(`Gold eval run failed with ${response.status}`);
            }
            const payload = await response.json();
            latestGoldEvalPayload = payload;
            const summary = payload.summary || {};
            const items = payload.items || [];
            const failing = items.filter((item) => item.status !== 'pass');
            renderDetailCard(goldEvalSummary, [
                `Cases: ${summary.case_count || items.length}`,
                `Pass: ${summary.pass_count || 0}`,
                `Fail: ${summary.fail_count || 0}`,
            ]);
            if (failing.length > 0) {
                renderObjectList(goldEvalFailures, failing, (item) => `${item.question} | ${item.status.toUpperCase()} | missing ${item.missing_features.join(', ')}`);
            } else {
                renderReviewList(goldEvalFailures, ['All governed eval cases passed in the current local review run.']);
            }
            addLog(`Gold eval run completed: ${(summary.pass_count || 0)}/${summary.case_count || items.length} cases passed.`, 'success');
            renderStoryboard();
        } catch (error) {
            console.error(error);
            const payload = RECORDED_REVIEW.goldEval;
            activateRecordedReview('gold eval');
            latestGoldEvalPayload = payload;
            const summary = payload.summary || {};
            const items = payload.items || [];
            const failing = items.filter((item) => item.status !== 'pass');
            renderDetailCard(goldEvalSummary, [
                `Cases: ${summary.case_count || items.length}`,
                `Pass: ${summary.pass_count || 0}`,
                `Fail: ${summary.fail_count || 0}`,
            ]);
            if (failing.length > 0) {
                renderObjectList(goldEvalFailures, failing, (item) => `${item.question} | ${item.status.toUpperCase()} | missing ${item.missing_features.join(', ')}`);
            } else {
                renderReviewList(goldEvalFailures, ['All recorded governed eval cases passed in the local recruiter review run.']);
            }
            renderStoryboard();
        } finally {
            runGoldEvalBtn.disabled = false;
            runGoldEvalBtn.innerText = 'Run Gold Eval';
        }
    }

    async function copyReviewRoutes() {
        const routes = latestReviewRoutes.length > 0
            ? latestReviewRoutes
            : ['/health', '/api/runtime/brief', '/api/review-pack', '/api/query-audit/recent'];
        const ok = await copyTextToClipboard(routes.join('\n'));
        addLog(ok ? 'Copied reviewer route checklist.' : 'Failed to copy reviewer route checklist.', ok ? 'success' : 'error');
    }

    async function copyGovernedClaim() {
        const latestSummary = latestAuditDetailPayload?.latest || {};
        const evalSummary = latestGoldEvalPayload?.summary || {};
        const lines = [
            'Nexus-Hive governed claim snapshot',
            `Headline: ${reviewPackHeadline.innerText || '-'}`,
            `Warehouse ready: ${reviewPackReady.innerText || '-'}`,
            `Schema: ${reviewPackSchema.innerText || '-'}`,
            `Audit requests: ${warehouseAuditCount.innerText || '-'}`,
            `Proof freshness: ${priorityFreshness?.innerText || '-'}`,
            `Gold eval: ${evalSummary.pass_count ?? 0}/${evalSummary.case_count ?? 0}`,
            `Latest audit: ${latestSummary.request_id || latestAuditRequestId || '-'}`,
            `Policy decision: ${latestSummary.policy_decision || 'review-pending'}`,
            `Fallback SQL: ${latestSummary.fallback_sql_used ? 'yes' : 'no'}`,
            '',
            'Fast routes',
            ...((latestReviewRoutes.length > 0 ? latestReviewRoutes : ['/api/review-pack', '/api/evals/nl2sql-gold/run', '/api/query-audit/recent'])
                .slice(0, 4)
                .map((item) => `- ${item}`)),
        ];
        const ok = await copyTextToClipboard(lines.join('\n'));
        addLog(ok ? 'Copied governed claim snapshot.' : 'Failed to copy governed claim snapshot.', ok ? 'success' : 'error');
    }

    async function copyQueryDecisionBrief() {
        const latestSummary = latestAuditDetailPayload?.latest || {};
        const history = latestAuditDetailPayload?.history || [];
        const nextAction = latestSummary.next_action
            || (latestSummary.policy_decision === 'deny'
                ? 'Remove blocked SQL patterns and rerun after policy preview.'
                : latestSummary.policy_decision === 'review'
                    ? 'Inspect audit detail, lineage, and policy reasons before sharing output.'
                    : 'Share the governed answer with audit detail attached.');
        const lines = [
            'Nexus-Hive query decision brief',
            `Headline: ${reviewPackHeadline.innerText || '-'}`,
            `Request ID: ${latestSummary.request_id || latestAuditRequestId || '-'}`,
            `Policy decision: ${String(latestSummary.policy_decision || 'review-pending').toUpperCase()}`,
            `Stage: ${String(latestSummary.stage || 'unknown').toUpperCase()}`,
            `Rows: ${latestSummary.row_count || 0}`,
            `Chart: ${latestSummary.chart_type || 'n/a'}`,
            `Fallback: ${latestSummary.fallback_sql_used || latestSummary.fallback_chart_used ? 'yes' : 'no'}`,
            `Proof freshness: ${priorityFreshness?.innerText || '-'}`,
            `History entries: ${history.length}`,
            `Next action: ${nextAction}`,
            '',
            'Fast routes',
            ...((latestReviewRoutes.length > 0 ? latestReviewRoutes : ['/api/query-review-board', '/api/query-audit/recent', '/api/query-audit/{request_id}'])
                .slice(0, 4)
                .map((item) => `- ${item}`)),
        ];
        const ok = await copyTextToClipboard(lines.join('\n'));
        addLog(ok ? 'Copied query decision brief.' : 'Failed to copy query decision brief.', ok ? 'success' : 'error');
    }

    function focusLatestAudit() {
        if (!latestAuditRequestId) {
            renderDetailCard(auditDetail, ['Run a governed query or select a request from the audit feed first.']);
            addLog('No recent audit request is available yet.', 'error');
            return;
        }
        loadQueryAuditDetail(latestAuditRequestId);
    }

    function seedDeniedSql() {
        policyRoleSelect.value = 'viewer';
        policySqlInput.value = 'SELECT * FROM sales LIMIT 20;';
        renderDetailCard(policyVerdict, [
            'Seeded deny-path SQL.',
            'Run Policy Check to confirm wildcard projection is blocked before execution.'
        ]);
        addLog('Loaded deny-path SQL example for policy preview.', 'system');
    }

    async function copyGoldEvalSummary() {
        const payload = latestGoldEvalPayload;
        const summary = payload?.summary || {};
        const items = payload?.items || [];
        const failing = items.filter((item) => item.status !== 'pass');
        const lines = [
            'Nexus-Hive gold eval summary',
            `Cases: ${summary.case_count || items.length || 0}`,
            `Pass: ${summary.pass_count || 0}`,
            `Fail: ${summary.fail_count || 0}`,
            '',
            'Failures',
            ...(failing.length > 0
                ? failing.map((item) => `- ${item.question} | ${String(item.status || 'unknown').toUpperCase()} | missing ${(item.missing_features || []).join(', ')}`)
                : ['- All governed eval cases passed in the current local review run.']),
        ];
        const ok = await copyTextToClipboard(lines.join('\n'));
        addLog(ok ? 'Copied gold eval summary.' : 'Failed to copy gold eval summary.', ok ? 'success' : 'error');
    }

    async function copyLatestAuditSnapshot() {
        if (!latestAuditDetailPayload?.latest) {
            renderDetailCard(auditDetail, ['Run a governed query or focus a recent request before copying audit detail.']);
            addLog('No audit detail is loaded yet.', 'error');
            return;
        }
        const latest = latestAuditDetailPayload.latest || {};
        const history = latestAuditDetailPayload.history || [];
        const lines = [
            'Nexus-Hive latest audit snapshot',
            `Request ID: ${latestAuditDetailPayload.request_id || '-'}`,
            `Decision: ${String(latest.policy_decision || 'unknown').toUpperCase()}`,
            `Stage: ${String(latest.stage || 'unknown').toUpperCase()}`,
            `Rows: ${latest.row_count || 0}`,
            `Retries: ${latest.retry_count || 0}`,
            `Chart: ${latest.chart_type || 'n/a'}`,
            `History entries: ${history.length}`,
            `Fallback: ${latest.fallback_sql_used || latest.fallback_chart_used ? 'yes' : 'no'}`,
            `SQL: ${latest.sql_query || 'not captured yet'}`,
        ];
        const ok = await copyTextToClipboard(lines.join('\n'));
        addLog(ok ? 'Copied latest audit snapshot.' : 'Failed to copy latest audit snapshot.', ok ? 'success' : 'error');
    }

    async function copyReviewBundle() {
        const bundle = [
            'Nexus-Hive review bundle',
            `Headline: ${reviewPackHeadline.innerText || '-'}`,
            `Routes: ${reviewPackRoutes.innerText || '-'}`,
            `Schema: ${reviewPackSchema.innerText || '-'}`,
            `Gold eval: ${goldEvalSummary.innerText || '-'}`,
            '',
            'Fast routes',
            ...((latestReviewRoutes.length > 0 ? latestReviewRoutes : ['/api/review-pack', '/api/query-audit/recent', '/api/evals/nl2sql-gold/run'])
                .map((route) => `- ${route}`)),
        ];
        const ok = await copyTextToClipboard(bundle.join('\n'));
        addLog(ok ? 'Copied review bundle.' : 'Failed to copy review bundle.', ok ? 'success' : 'error');
    }

    function renderLensPanel() {
        const config = REVIEW_LENSES[currentLens] || REVIEW_LENSES.analyst;
        lensHeadline.textContent = config.headline;
        lensSummary.textContent = config.summary;
        lensGrid.innerHTML = config.cards.map(([label, body]) => `
            <section class="brief-list-card">
                <span class="brief-label">${label}</span>
                <ul class="brief-list"><li class="brief-list-item">${body}</li></ul>
            </section>
        `).join('');
        [lensAnalystBtn, lensReviewerBtn, lensExecutiveBtn].forEach((btn) => btn?.classList.remove('active'));
        if (currentLens === 'analyst') lensAnalystBtn?.classList.add('active');
        if (currentLens === 'reviewer') lensReviewerBtn?.classList.add('active');
        if (currentLens === 'executive') lensExecutiveBtn?.classList.add('active');
        lensPrimaryBtn.textContent = config.actions[0];
        lensSecondaryBtn.textContent = config.actions[1];
        lensTertiaryBtn.textContent = config.actions[2];
    }

    function runLensAction(action) {
        if (action === 'Copy Review Routes') return copyReviewRoutes();
        if (action === 'Copy Governed Claim') return copyGovernedClaim();
        if (action === 'Copy Review Bundle') return copyReviewBundle();
        if (action === 'Copy Query Decision Brief') return copyQueryDecisionBrief();
        if (action === 'Copy Latest Audit') return copyLatestAuditSnapshot();
        if (action === 'Seed Denied SQL') return seedDeniedSql();
        if (action === 'Copy Gold Eval') return copyGoldEvalSummary();
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
            latestAuditRequestId = askPayload.request_id;
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
                loadQuerySessionBoard();
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
            loadQuerySessionBoard();
            loadQueryAuditDetail(latestRequestId);
            askBtn.disabled = false;
            nlInput.disabled = false;
            askBtn.innerText = "EXECUTE";
        };
    }

    askBtn.addEventListener('click', executeQuery);
    policyCheckBtn.addEventListener('click', runPolicyCheck);
    useLatestSqlBtn.addEventListener('click', () => {
        const requestId = latestRequestId || latestAuditRequestId;
        if (requestId) {
            loadQueryAuditDetail(requestId);
        } else {
            renderDetailCard(auditDetail, ['No audited request is available yet. Run a query or pick one from the audit feed.']);
        }
    });
    copyReviewRoutesBtn.addEventListener('click', copyReviewRoutes);
    copyGovernedClaimBtn.addEventListener('click', copyGovernedClaim);
    copyQueryDecisionBtn.addEventListener('click', copyQueryDecisionBrief);
    copyReviewBundleBtn.addEventListener('click', copyReviewBundle);
    copyLatestAuditBtn.addEventListener('click', copyLatestAuditSnapshot);
    focusLatestAuditBtn.addEventListener('click', focusLatestAudit);
    seedDeniedSqlBtn.addEventListener('click', seedDeniedSql);
    copyGoldEvalBtn.addEventListener('click', copyGoldEvalSummary);
    runGoldEvalBtn.addEventListener('click', loadGoldEvalRun);
    renderLensPanel();
    lensAnalystBtn.addEventListener('click', () => { currentLens = 'analyst'; renderLensPanel(); });
    lensReviewerBtn.addEventListener('click', () => { currentLens = 'reviewer'; renderLensPanel(); });
    lensExecutiveBtn.addEventListener('click', () => { currentLens = 'executive'; renderLensPanel(); });
    lensPrimaryBtn.addEventListener('click', () => runLensAction(lensPrimaryBtn.textContent));
    lensSecondaryBtn.addEventListener('click', () => runLensAction(lensSecondaryBtn.textContent));
    lensTertiaryBtn.addEventListener('click', () => runLensAction(lensTertiaryBtn.textContent));
    nlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') executeQuery();
    });
    if (statusText) {
        statusText.innerText = 'Waiting for governed proof';
    }
    policySqlInput.value = 'SELECT region, SUM(net_revenue) AS total_revenue FROM sales GROUP BY region ORDER BY total_revenue DESC LIMIT 5;';
    renderDetailCard(policyVerdict, ['Run a policy preview on the seeded warehouse SQL before relying on the chart output.']);
    renderDetailCard(goldEvalSummary, ['Run the deterministic NL2SQL suite to inspect governed baseline quality.']);
    renderDetailCard(auditDetail, ['Select a recent audit request or run a governed query to inspect SQL, fallback usage, and retries.']);
    renderDetailCard(sessionBoardSummary, ['Saved sessions let you reopen completed or blocked analyst requests.']);
    renderReviewerPriority();
    renderStoryboard();
    document.addEventListener('keydown', (event) => {
        const tag = String(event.target?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || event.metaKey || event.ctrlKey || event.altKey) {
            return;
        }
        const key = event.key.toLowerCase();
        if (key === '?') {
            if (governanceHotkeys) {
                governanceHotkeys.textContent = 'Keyboard: E execute · P policy check · G governed claim · D decision brief · B review bundle · A latest audit.';
            }
            return;
        }
        if (key === 'e') {
            event.preventDefault();
            askBtn.click();
        }
        if (key === 'p') {
            event.preventDefault();
            policyCheckBtn.click();
        }
        if (key === 'g') {
            event.preventDefault();
            copyGovernedClaimBtn.click();
        }
        if (key === 'd') {
            event.preventDefault();
            copyQueryDecisionBtn.click();
        }
        if (key === 'b') {
            event.preventDefault();
            copyReviewBundleBtn.click();
        }
        if (key === 'a') {
            event.preventDefault();
            copyLatestAuditBtn.click();
        }
    });
    loadRuntimeBrief();
    loadReviewPack();
    loadWarehouseBrief();
    loadQueryAuditFeed();
    loadQuerySessionBoard();
    loadGoldEvalRun();
});
