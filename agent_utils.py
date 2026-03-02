import re
from typing import Any, Dict, Iterable, List, Tuple

ALLOWED_CHART_TYPES = {"bar", "line", "pie", "doughnut"}
FORBIDDEN_SQL_KEYWORDS = {
    "ALTER",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "INSERT",
    "PRAGMA",
    "REINDEX",
    "REPLACE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


def strip_markdown_fence(text: str) -> str:
    """Remove optional markdown code fences from model output."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _strip_sql_literals_and_comments(sql: str) -> str:
    # Replace quoted strings first so semicolons/keywords in literals are ignored.
    without_strings = re.sub(r"'(?:''|[^'])*'", "''", sql, flags=re.S)
    without_strings = re.sub(r'"(?:""|[^"])*"', '""', without_strings, flags=re.S)
    without_block_comments = re.sub(r"/\*.*?\*/", " ", without_strings, flags=re.S)
    without_line_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    return without_line_comments


def validate_read_only_sql(sql: str) -> Tuple[bool, str]:
    """Validate that SQL is a single read-only statement."""
    candidate = strip_markdown_fence(sql)
    if not candidate:
        return False, "Generated SQL was empty."

    normalized = _strip_sql_literals_and_comments(candidate)
    statements = [part.strip() for part in normalized.split(";") if part.strip()]
    if len(statements) != 1:
        return False, "Only one SQL statement is allowed per request."

    statement = statements[0]
    first_token_match = re.match(r"^\s*([A-Za-z_]+)", statement)
    first_token = first_token_match.group(1).upper() if first_token_match else ""
    if first_token not in {"SELECT", "WITH"}:
        return False, "Only read-only SELECT statements are allowed."

    upper_statement = statement.upper()
    for keyword in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper_statement):
            return False, f"Unsafe SQL keyword detected: {keyword}."

    return True, ""


def _first_numeric_key(rows: Iterable[Dict[str, Any]], keys: List[str], label_key: str) -> str:
    for key in keys:
        if key == label_key:
            continue
        for row in rows:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                return key
            if isinstance(value, str):
                try:
                    float(value)
                    return key
                except ValueError:
                    continue
            break
    return keys[1] if len(keys) > 1 else keys[0]


def normalize_chart_config(raw_config: Any, rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return a safe chart config that always references existing keys when possible."""
    keys = list(rows[0].keys()) if rows else []
    fallback_labels_key = keys[0] if keys else "label"
    fallback_data_key = _first_numeric_key(rows, keys, fallback_labels_key) if keys else "value"

    config: Dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    chart_type = str(config.get("type", "bar")).lower()
    if chart_type not in ALLOWED_CHART_TYPES:
        chart_type = "bar"

    labels_key = str(config.get("labels_key", fallback_labels_key))
    if keys and labels_key not in keys:
        labels_key = fallback_labels_key

    data_key = str(config.get("data_key", fallback_data_key))
    if keys and data_key not in keys:
        data_key = fallback_data_key

    title = str(config.get("title") or "Data Visualization")

    return {
        "type": chart_type,
        "labels_key": labels_key,
        "data_key": data_key,
        "title": title,
    }
