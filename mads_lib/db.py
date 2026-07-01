import sqlite3

import click

from .config import DB_PATH


def get_db():
    """Open SQLite connection with WAL mode.

    mads-cli owns no schema — it does not create tables. The database is
    expected to already exist (created/owned by the parent talas-ads project,
    e.g. shared with gads-cli's changelog table). This mirrors gads-cli's
    db.py exactly.
    """
    if not DB_PATH.exists():
        click.secho(f"✗ Database not found: {DB_PATH}", fg="red", err=True)
        click.secho("  This CLI does not create the database — it must already exist.", fg="yellow", err=True)
        raise SystemExit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn
