import unittest

from agent_utils import normalize_chart_config, strip_markdown_fence, validate_read_only_sql


class StripMarkdownFenceTests(unittest.TestCase):
    def test_strips_fenced_sql(self):
        raw = "```sql\nSELECT * FROM sales;\n```"
        self.assertEqual(strip_markdown_fence(raw), "SELECT * FROM sales;")


class ValidateReadOnlySqlTests(unittest.TestCase):
    def test_allows_simple_select(self):
        is_safe, message = validate_read_only_sql("SELECT * FROM sales LIMIT 5;")
        self.assertTrue(is_safe)
        self.assertEqual(message, "")

    def test_rejects_multiple_statements(self):
        is_safe, message = validate_read_only_sql("SELECT 1; SELECT 2;")
        self.assertFalse(is_safe)
        self.assertIn("Only one SQL statement", message)

    def test_rejects_unsafe_keyword(self):
        is_safe, message = validate_read_only_sql("SELECT * FROM sales; DELETE FROM sales;")
        self.assertFalse(is_safe)

    def test_ignores_keyword_inside_string_literal(self):
        is_safe, message = validate_read_only_sql("SELECT 'drop table users' AS note;")
        self.assertTrue(is_safe)
        self.assertEqual(message, "")

    def test_rejects_non_select_statement(self):
        is_safe, message = validate_read_only_sql("PRAGMA table_info(sales);")
        self.assertFalse(is_safe)
        self.assertIn("read-only SELECT", message)


class NormalizeChartConfigTests(unittest.TestCase):
    def test_fallback_for_empty_rows(self):
        config = normalize_chart_config({}, [])
        self.assertEqual(
            config,
            {
                "type": "bar",
                "labels_key": "label",
                "data_key": "value",
                "title": "Data Visualization",
            },
        )

    def test_invalid_type_and_missing_keys_are_normalized(self):
        rows = [{"region_name": "EMEA", "total_profit": 100.5}]
        config = normalize_chart_config(
            {"type": "scatter", "labels_key": "bad", "data_key": "missing", "title": "Profit"},
            rows,
        )
        self.assertEqual(config["type"], "bar")
        self.assertEqual(config["labels_key"], "region_name")
        self.assertEqual(config["data_key"], "total_profit")
        self.assertEqual(config["title"], "Profit")

    def test_preserves_valid_config(self):
        rows = [{"month": "2026-01", "revenue": 1200}]
        config = normalize_chart_config(
            {"type": "line", "labels_key": "month", "data_key": "revenue", "title": "Revenue Trend"},
            rows,
        )
        self.assertEqual(config["type"], "line")
        self.assertEqual(config["labels_key"], "month")
        self.assertEqual(config["data_key"], "revenue")
        self.assertEqual(config["title"], "Revenue Trend")


if __name__ == "__main__":
    unittest.main()
