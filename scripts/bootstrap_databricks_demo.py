from __future__ import annotations

import json
from pathlib import Path

from databricks_adapter import seed_demo_tables_from_sqlite


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sqlite_db = repo_root / "nexus_enterprise.db"
    counts = seed_demo_tables_from_sqlite(sqlite_db)
    print(json.dumps({"database": str(sqlite_db), "loaded_tables": counts}, indent=2))


if __name__ == "__main__":
    main()
