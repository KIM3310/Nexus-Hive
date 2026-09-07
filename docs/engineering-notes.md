# SQL policy that governs execution

The previous policy searched SQL text for strings such as `SELECT *` and `LIMIT`. Newlines, comments, qualified wildcards, or a LIMIT inside a subquery could change the verdict without changing what the query exposed. A `review` verdict was logged but still executed.

The policy now parses SQL with [SQLGlot](https://github.com/tobymao/sqlglot), requires one read-query statement, checks wildcard and sensitive column nodes, and examines the outer query's explicit bound. Unknown roles and invalid input fail closed. Literals and comments no longer trigger write-keyword false positives. Both `review` and `deny` stop the executor and end the graph instead of entering automatic translation retries.

Run `make verify`. `tests/test_sql_policy_boundaries.py` includes whitespace/comment and qualified wildcard cases, nested query access, multiple statements, quoted sensitive identifiers, write/command statements, benign keyword literals, negative LIMIT, unknown roles, and an assertion that a review-required query never calls the warehouse adapter.

The parser does not authenticate users or prove all SQL harmless. Database read-only permissions and engine-specific constraints remain necessary. Review-required queries currently remain stopped; implementing a durable, authenticated approval workflow is a separate change.
