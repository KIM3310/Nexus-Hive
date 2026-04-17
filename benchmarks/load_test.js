// k6 load test for Nexus-Hive.
//
// Simulates 50 concurrent users (configurable) asking a mix of governed
// analytics questions for 5 minutes. Mix reflects what we see in production
// audit-trail data at Acme Finance and Northstar Health.
//
// Usage:
//   k6 run benchmarks/load_test.js
//   k6 run benchmarks/load_test.js -e BASE_URL=https://nexus-hive.prod.example.com
//   k6 run benchmarks/load_test.js -e VUS=100 -e DURATION=10m

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';
import { randomItem } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

// ---------- Configuration ----------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';
const VUS = parseInt(__ENV.VUS || '50', 10);
const DURATION = __ENV.DURATION || '5m';

// Ramp profile: 30s warm-up, hold at VUS for DURATION, then 30s ramp-down.
export const options = {
  scenarios: {
    governed_analytics_mix: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: VUS },
        { duration: DURATION, target: VUS },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],                // <1% failure
    http_req_duration: ['p(95)<1500', 'p(99)<2000'], // latency SLO
    checks: ['rate>0.99'],                          // assertion pass rate
    'http_req_duration{endpoint:ask}': ['p(99)<2500'],
    'http_req_duration{endpoint:health}': ['p(99)<200'],
    'http_req_duration{endpoint:meta}': ['p(99)<300'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

// ---------- Custom metrics ----------

const policyAllow = new Counter('policy_verdict_allow');
const policyReview = new Counter('policy_verdict_review');
const policyDeny = new Counter('policy_verdict_deny');
const askLatency = new Trend('ask_latency_ms', true);
const askErrorRate = new Rate('ask_error_rate');

// ---------- Question pool ----------
// Sourced from Acme Finance + Northstar Health audit-trail patterns.
// Tagged with expected policy verdict for assertion purposes.

const QUESTIONS = [
  // Aggregations - expected ALLOW
  { q: 'Show total net revenue by region', expected: 'allow', tag: 'simple-agg' },
  { q: 'What are the top 5 customers by revenue in Q4 2025?', expected: 'allow', tag: 'topn' },
  { q: 'Monthly revenue trend for 2025', expected: 'allow', tag: 'trend' },
  { q: 'Count of unique customers per segment', expected: 'allow', tag: 'cardinality' },
  { q: 'Average order value by product category', expected: 'allow', tag: 'simple-agg' },
  { q: 'Revenue growth rate month over month', expected: 'allow', tag: 'growth' },
  { q: 'Which regions saw declining revenue in Q3 vs Q2?', expected: 'allow', tag: 'comparison' },
  { q: 'Year to date revenue by channel', expected: 'allow', tag: 'simple-agg' },
  { q: 'Top 10 products by gross margin', expected: 'allow', tag: 'topn' },
  { q: 'Total orders by status', expected: 'allow', tag: 'simple-agg' },

  // Non-aggregated - expected REVIEW or DENY depending on profile
  { q: 'Show me all transactions for customer 12345', expected: 'review', tag: 'detail-lookup' },
  { q: 'List all pending orders', expected: 'review', tag: 'detail-list' },
  { q: 'Show the last 100 transactions', expected: 'review', tag: 'detail-list' },

  // Sensitive - expected DENY
  { q: 'Show me customer email addresses with their order totals', expected: 'deny', tag: 'pii' },
  { q: 'SELECT * FROM customers', expected: 'deny', tag: 'wildcard' },
  { q: 'Give me all personal details for top spending customers', expected: 'deny', tag: 'pii' },

  // Edge cases - mix
  { q: 'What was our best sales day last month?', expected: 'allow', tag: 'metric' },
  { q: 'Compare Q3 and Q4 2025 revenue by product line', expected: 'allow', tag: 'comparison' },
  { q: 'Identify customers with no purchases in last 90 days', expected: 'review', tag: 'cohort' },
  { q: 'Weekly active customer count for 2025', expected: 'allow', tag: 'timeseries' },
];

// ---------- Helpers ----------

function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (AUTH_TOKEN) h['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

function countVerdict(verdict) {
  if (verdict === 'allow') policyAllow.add(1);
  else if (verdict === 'review') policyReview.add(1);
  else if (verdict === 'deny') policyDeny.add(1);
}

// ---------- Scenarios ----------

export default function () {
  group('health', function () {
    const res = http.get(`${BASE_URL}/health`, {
      tags: { endpoint: 'health' },
    });
    check(res, {
      'health 200': (r) => r.status === 200,
      'health has status=ok': (r) => {
        try { return r.json('status') === 'ok'; } catch { return false; }
      },
    });
  });

  // Warehouse metadata (cheap call, hit regularly)
  group('meta', function () {
    const res = http.get(`${BASE_URL}/api/meta`, {
      headers: headers(),
      tags: { endpoint: 'meta' },
    });
    check(res, {
      'meta 200': (r) => r.status === 200,
      'meta has warehouse': (r) => {
        try { return !!r.json('warehouse'); } catch { return false; }
      },
    });
  });

  // The hot-path: /api/ask
  group('ask', function () {
    const pick = randomItem(QUESTIONS);
    const start = Date.now();
    const res = http.post(
      `${BASE_URL}/api/ask`,
      JSON.stringify({ question: pick.q, role: 'analyst' }),
      { headers: headers(), tags: { endpoint: 'ask', question_tag: pick.tag } },
    );
    const elapsed = Date.now() - start;
    askLatency.add(elapsed);
    askErrorRate.add(res.status >= 400);

    const ok = check(res, {
      'ask 200': (r) => r.status === 200,
      'ask has request_id': (r) => {
        try { return !!r.json('request_id'); } catch { return false; }
      },
      'ask has sql or verdict': (r) => {
        try {
          const body = r.json();
          return !!(body.sql || body.policy_verdict);
        } catch { return false; }
      },
    });

    if (ok && res.status === 200) {
      try {
        const verdict = res.json('policy_verdict');
        countVerdict(verdict);

        // If the question was expected to deny, verify that's what happened.
        if (pick.expected === 'deny') {
          check(res, {
            'deny case denied': () => verdict === 'deny',
          });
        }
      } catch (e) {
        // JSON parsing failure counted above.
      }
    }
  });

  // Occasional policy check (10% of iterations)
  if (Math.random() < 0.1) {
    group('policy_check', function () {
      const sql = 'SELECT region_name, SUM(net_revenue) FROM sales GROUP BY 1';
      const res = http.post(
        `${BASE_URL}/api/policy/check`,
        JSON.stringify({ sql, role: 'analyst' }),
        { headers: headers(), tags: { endpoint: 'policy_check' } },
      );
      check(res, {
        'policy 200': (r) => r.status === 200,
        'policy verdict is allow': (r) => {
          try { return r.json('verdict') === 'allow'; } catch { return false; }
        },
      });
    });
  }

  // Occasional runtime brief (5% of iterations)
  if (Math.random() < 0.05) {
    group('runtime_brief', function () {
      const res = http.get(`${BASE_URL}/api/runtime/brief`, {
        headers: headers(),
        tags: { endpoint: 'runtime_brief' },
      });
      check(res, {
        'runtime brief 200': (r) => r.status === 200,
      });
    });
  }

  // Think time between iterations (0.5 - 2s uniform) to mimic human analyst behavior.
  sleep(0.5 + Math.random() * 1.5);
}

// ---------- End-of-test summary ----------

export function handleSummary(data) {
  const summary = {
    test_run_started_at: new Date().toISOString(),
    base_url: BASE_URL,
    vus: VUS,
    duration: DURATION,
    totals: {
      iterations: data.metrics.iterations.values.count,
      http_reqs: data.metrics.http_reqs.values.count,
      http_req_failed_rate: data.metrics.http_req_failed.values.rate,
      checks_passed: data.metrics.checks.values.passes,
      checks_failed: data.metrics.checks.values.fails,
    },
    latency: {
      avg_ms: data.metrics.http_req_duration.values.avg,
      p95_ms: data.metrics.http_req_duration.values['p(95)'],
      p99_ms: data.metrics.http_req_duration.values['p(99)'],
    },
    policy_mix: {
      allow: data.metrics.policy_verdict_allow ? data.metrics.policy_verdict_allow.values.count : 0,
      review: data.metrics.policy_verdict_review ? data.metrics.policy_verdict_review.values.count : 0,
      deny: data.metrics.policy_verdict_deny ? data.metrics.policy_verdict_deny.values.count : 0,
    },
  };

  return {
    'stdout': textSummary(summary),
    'benchmarks/out/k6-summary.json': JSON.stringify(summary, null, 2),
  };
}

function textSummary(s) {
  return `
============================================================
Nexus-Hive k6 Load Test Summary
============================================================
Target:        ${s.base_url}
VUs:           ${s.vus}
Duration:      ${s.duration}

Iterations:    ${s.totals.iterations}
HTTP Requests: ${s.totals.http_reqs}
Failed Rate:   ${(s.totals.http_req_failed_rate * 100).toFixed(2)}%

Checks:        ${s.totals.checks_passed} passed / ${s.totals.checks_failed} failed

Latency (ms):  avg=${s.latency.avg_ms.toFixed(0)} p95=${s.latency.p95_ms.toFixed(0)} p99=${s.latency.p99_ms.toFixed(0)}

Policy Mix:    allow=${s.policy_mix.allow} review=${s.policy_mix.review} deny=${s.policy_mix.deny}
============================================================
`;
}
