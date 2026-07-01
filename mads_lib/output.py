import json

import click

# EXIT_CODES mirrors gads-cli's dict (OK/GENERAL/USAGE/AUTH/NOT_FOUND/API/VALIDATION/DB)
# PLUS RATE_LIMIT=8, which is mads-cli-specific — gads-cli does NOT define this
# code. Meta's Graph API has explicit, frequent rate-limiting error codes
# (4, 17, 32, 613, and the ads-insights-specific 80xxx codes) that warrant a
# distinct exit code so callers/agents can back off and retry instead of
# treating it as a generic API failure.
EXIT_CODES = {
    "OK": 0,
    "GENERAL": 1,
    "USAGE": 2,
    "AUTH": 3,
    "NOT_FOUND": 4,
    "API": 5,
    "VALIDATION": 6,
    "DB": 7,
    "RATE_LIMIT": 8,
}


def print_error(message, code="GENERAL", exit_code=None, as_json=False):
    """Print a structured error and return the numeric exit code."""
    numeric = exit_code if exit_code is not None else EXIT_CODES.get(code, 1)
    if as_json:
        click.echo(
            json.dumps({"error": {"code": code, "message": message, "exit_code": numeric}}),
            err=True,
        )
    else:
        click.secho(f"✗ {message}", fg="red", err=True)
    return numeric


def flatten(obj, prefix=""):
    """Flatten nested dict for table display."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flatten(v, key))
            else:
                items[key] = v
    return items


def print_table(rows, columns=None):
    """Print rows as an aligned terminal table."""
    if not rows:
        click.echo("  (no results)")
        return
    if columns is None:
        columns = list(rows[0].keys())

    widths = {c: len(c) for c in columns}
    str_rows = []
    for row in rows:
        sr = {}
        for c in columns:
            val = row.get(c, "")
            if val is None:
                val = "—"
            elif isinstance(val, float):
                val = f"{val:,.2f}"
            else:
                val = str(val)
            sr[c] = val
            widths[c] = max(widths[c], len(val))
        str_rows.append(sr)

    header = "  ".join(c.ljust(widths[c]) for c in columns)
    click.secho(header, fg="cyan", bold=True)
    click.echo("  ".join("─" * widths[c] for c in columns))
    for sr in str_rows:
        click.echo("  ".join(sr[c].ljust(widths[c]) for c in columns))


def print_json(data):
    """Pretty-print JSON to stdout."""
    click.echo(json.dumps(data, indent=2, default=str))
