"""Read-only SELECT access to the local SQLite history DB.

This module gives an agent native, *read-only* access to the project's own
memory (changelog / decisions / milestones, etc.). It is defensive by design:

  1. A SQL guard (`assert_select_only`) statically rejects anything that is not
     a single read-only SELECT / WITH...SELECT statement.
  2. The connection itself is opened with `PRAGMA query_only = ON`, so even if
     the static guard were somehow bypassed, the connection physically refuses
     to mutate the database.

No Click commands live here — this module is pure logic. CLI wiring happens in
cli.py.

Near-verbatim port of gads-cli's gads_lib/dbread.py.
"""

import re

# Mutating / dangerous keywords that must never appear in a read-only query.
# Matched as whole words, case-insensitive.
_FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "TRUNCATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
    "GRANT",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
)

# Block comment: /* ... */  (non-greedy, across newlines)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Line comment: -- ... until end of line
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


class UnsafeSQLError(ValueError):
    """Raised when SQL is anything other than a single read-only SELECT."""

    pass


def _strip_comments(sql):
    """Remove SQL line (--) and block (/* */) comments."""
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    return sql


def assert_select_only(sql):
    """Raise UnsafeSQLError unless `sql` is a single read-only SELECT/WITH.

    Guards:
      * Strips leading whitespace and SQL comments before inspecting.
      * Rejects multiple statements (more than one non-empty `;`-fragment).
      * Requires the statement to start with SELECT or WITH (CTEs).
      * Rejects any forbidden mutating keyword (whole-word, case-insensitive).
    """
    if sql is None:
        raise UnsafeSQLError(
            "Only single read-only SELECT queries are allowed (rejected: empty query)."
        )

    cleaned = _strip_comments(sql).strip()

    if not cleaned:
        raise UnsafeSQLError(
            "Only single read-only SELECT queries are allowed (rejected: empty query)."
        )

    # Reject multiple statements. Split on ';' and keep non-empty fragments.
    fragments = [frag for frag in cleaned.split(";") if frag.strip()]
    if len(fragments) > 1:
        raise UnsafeSQLError(
            "Only single read-only SELECT queries are allowed "
            "(rejected: multiple statements)."
        )

    statement = fragments[0].strip()
    upper = statement.upper()

    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        first_word = upper.split(None, 1)[0] if upper.split() else "<empty>"
        raise UnsafeSQLError(
            "Only single read-only SELECT queries are allowed "
            f"(rejected: statement starts with {first_word})."
        )

    # Whole-word scan for forbidden mutating keywords.
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", statement, re.IGNORECASE):
            raise UnsafeSQLError(
                "Only single read-only SELECT queries are allowed "
                f"(rejected: {keyword})."
            )

    return True


def run_select(sql, limit=None):
    """Run a guarded, read-only SELECT and return rows as a list of dicts.

    The static guard runs first; the connection is then opened with
    `PRAGMA query_only = ON` for defense in depth. If `limit` is given, the
    result list is sliced in Python (the SQL is never modified).
    """
    assert_select_only(sql)

    # Import locally to keep this module importable without a live DB / Click.
    from .db import get_db

    conn = get_db()
    try:
        # Defense in depth: even if the guard were bypassed, the connection
        # itself refuses any write.
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        if limit is not None:
            rows = rows[:limit]
        return rows
    finally:
        conn.close()


def read_changelog(limit=50):
    """Return recent changelog entries (most recent first)."""
    return run_select(
        "SELECT id, timestamp, action, campaign, campaign_id, details, reason, "
        "agent, snapshot_ref, script FROM changelog ORDER BY timestamp DESC",
        limit=limit,
    )


def read_decisions(limit=50):
    """Return recent decisions (most recent first)."""
    return run_select(
        "SELECT id, date, decision, context, rationale, status, category, "
        "session_ref FROM decisions ORDER BY date DESC",
        limit=limit,
    )


def read_milestones(limit=50):
    """Return recent milestones (most recent first)."""
    return run_select(
        "SELECT id, date, milestone, category, status, outcome, notes "
        "FROM milestones ORDER BY date DESC",
        limit=limit,
    )
