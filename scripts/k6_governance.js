import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: {
    governance_runtime: {
      executor: "shared-iterations",
      vus: Number(__ENV.K6_VUS || 4),
      iterations: Number(__ENV.K6_ITERATIONS || 20),
      maxDuration: __ENV.K6_MAX_DURATION || "60s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<3000"],
  },
};

const baseUrl = (__ENV.NEXUS_HIVE_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const operatorToken = (__ENV.NEXUS_HIVE_OPERATOR_TOKEN || "").trim();
const operatorRole = (__ENV.NEXUS_HIVE_OPERATOR_ROLE || "").trim();

function buildHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (operatorToken) {
    headers.Authorization = `Bearer ${operatorToken}`;
  }
  if (operatorRole) {
    headers["x-operator-role"] = operatorRole;
  }
  return headers;
}

export default function () {
  const headers = buildHeaders();
  const askResponse = http.post(
    `${baseUrl}/api/ask`,
    JSON.stringify({ question: "Show total revenue by region" }),
    { headers }
  );
  check(askResponse, {
    "ask status 200": (response) => response.status === 200,
  });

  const policyResponse = http.post(
    `${baseUrl}/api/policy/check`,
    JSON.stringify({ role: "analyst", sql: "SELECT region_name, SUM(net_revenue) FROM sales JOIN regions USING(region_id) GROUP BY region_name" }),
    { headers }
  );
  check(policyResponse, {
    "policy status 200": (response) => response.status === 200,
  });

  const scorecardResponse = http.get(`${baseUrl}/api/runtime/governance-scorecard?focus=throughput`, {
    headers,
  });
  check(scorecardResponse, {
    "scorecard status 200": (response) => response.status === 200,
    "scorecard has summary": (response) => Boolean(response.json("summary.total_requests")),
  });

  sleep(0.2);
}
