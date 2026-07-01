"""
catalog.py — Walk a Click command tree and emit a machine-readable manifest.

Usage:
    from mads_lib.catalog import build_catalog
    from mads_lib.cli import cli
    manifest = build_catalog(cli, version="0.1.0")

The returned dict is JSON-serializable and describes every command,
subcommand, param, type, default, and help string so an LLM can
discover the full CLI surface without parsing --help text.

Adapted from gads-cli's gads_lib/catalog.py.
"""

import json
import click


def _safe_default(value):
    """Return a JSON-serializable representation of a default value."""
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _param_entry(param, ctx):
    """Build a dict describing a single Click parameter."""
    type_obj = param.type

    # Type name
    type_name = getattr(type_obj, "name", str(type_obj))

    entry = {
        "name": param.name,
        "param_type": "argument" if isinstance(param, click.Argument) else "option",
        "opts": list(param.opts),
        "type": type_name,
        "required": bool(param.required),
        "is_flag": bool(getattr(param, "is_flag", False)),
        "default": _safe_default(param.default),
        "multiple": bool(getattr(param, "multiple", False)),
        "help": getattr(param, "help", None),
    }

    # Attach choices list for Choice types
    if isinstance(type_obj, click.Choice):
        entry["choices"] = list(type_obj.choices)

    return entry


def _command_entry(cmd, name, parent_ctx):
    """Recursively build a dict describing a Click command or group."""
    is_group = isinstance(cmd, click.Group)

    # Build a proper context so params resolve correctly
    ctx = click.Context(cmd, info_name=name, parent=parent_ctx)

    # Prefer the full help string; fall back to short help
    help_text = cmd.help or cmd.get_short_help_str()

    # Collect params, skipping the auto-injected --help eager flag
    params = []
    for param in cmd.get_params(ctx):
        if param.name == "help":
            continue
        # Also skip version eager flags
        if getattr(param, "is_eager", False) and param.name in ("version",):
            continue
        try:
            params.append(_param_entry(param, ctx))
        except Exception:
            # Never crash on real tree; skip problematic param
            pass

    entry = {
        "name": name,
        "help": help_text,
        "is_group": is_group,
        "params": params,
    }

    if is_group:
        subcommands = {}
        try:
            sub_names = cmd.list_commands(ctx)
        except Exception:
            sub_names = []

        for sub_name in sub_names:
            try:
                sub_cmd = cmd.get_command(ctx, sub_name)
                if sub_cmd is None:
                    continue
                subcommands[sub_name] = _command_entry(sub_cmd, sub_name, ctx)
            except Exception:
                # Never crash; skip problematic subcommand
                pass

        entry["subcommands"] = subcommands

    return entry


def build_catalog(group, version=None):
    """
    Walk a Click Group tree and return a JSON-serializable manifest.

    Parameters
    ----------
    group : click.Group
        The root CLI group (e.g. the `cli` object from cli.py).
    version : str, optional
        CLI version string to embed in the manifest.

    Returns
    -------
    dict
        {
          "cli": "mads",
          "version": version,
          "description": <root group help>,
          "commands": { name: <entry>, ... }
        }
    """
    root_ctx = click.Context(group, info_name="mads")

    # Root description
    description = group.help or group.get_short_help_str() or ""

    commands = {}
    try:
        top_names = group.list_commands(root_ctx)
    except Exception:
        top_names = []

    for name in top_names:
        try:
            cmd = group.get_command(root_ctx, name)
            if cmd is None:
                continue
            commands[name] = _command_entry(cmd, name, root_ctx)
        except Exception:
            # Never crash on real tree; skip problematic command
            pass

    return {
        "cli": "mads",
        "version": version,
        "description": description,
        "commands": commands,
    }
