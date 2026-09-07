from unittest.mock import Mock, patch

import pytest

from graph.nodes import executor_node, route_after_execution
from langgraph.graph import END
from policy.engine import evaluate_sql_policy


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT\n* FROM sales LIMIT 1",
        "SELECT /* spacing */ * FROM sales LIMIT 1",
        "SELECT s.* FROM sales s LIMIT 1",
        "WITH private AS (SELECT * FROM products) SELECT product_name FROM private LIMIT 1",
        "SELECT transaction_id FROM sales LIMIT 1; SELECT manager FROM regions LIMIT 1",
        'SELECT "margin_percentage" AS public_value FROM products LIMIT 1',
        "SELECT product_name INTO copied FROM products LIMIT 1",
        "ATTACH DATABASE '/tmp/other.db' AS other",
        "PRAGMA writable_schema = 1",
        "",
    ],
)
def test_disallowed_query_shapes_fail_closed(sql: str) -> None:
    assert evaluate_sql_policy(sql)["decision"] == "deny"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'DROP TABLE sales' AS message LIMIT 1",
        "SELECT transaction_id FROM sales /* UPDATE is a comment */ LIMIT 1",
        "SELECT COUNT(*) AS count FROM sales GROUP BY region_id",
    ],
)
def test_literals_comments_and_count_are_not_wildcard_access(sql: str) -> None:
    assert evaluate_sql_policy(sql)["decision"] == "allow"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT transaction_id FROM sales -- LIMIT 1",
        "SELECT transaction_id FROM sales WHERE region_id IN (SELECT region_id FROM regions LIMIT 1)",
        "SELECT transaction_id FROM sales LIMIT -1",
    ],
)
def test_only_outer_bounded_limit_suppresses_review(sql: str) -> None:
    assert evaluate_sql_policy(sql)["decision"] == "review"


def test_unknown_role_cannot_disable_column_restrictions() -> None:
    assert (
        evaluate_sql_policy("SELECT margin_percentage FROM products LIMIT 1", role="admni")[
            "decision"
        ]
        == "deny"
    )


def test_review_required_query_never_reaches_warehouse() -> None:
    adapter = Mock()
    state = {
        "sql_query": "SELECT transaction_id FROM sales",
        "log_stream": [],
        "db_result": [{"stale": True}],
    }
    with patch("graph.nodes.get_active_warehouse_adapter", return_value=adapter):
        result = executor_node(state)
    adapter.execute_sql_preview.assert_not_called()
    assert result["db_result"] == []
    assert result["policy_verdict"]["decision"] == "review"
    assert route_after_execution(result) == END
