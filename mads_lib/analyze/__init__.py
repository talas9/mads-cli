"""Analysis sub-package for the Talas mads CLI.

Read-only analytical helpers that build on top of :mod:`mads_lib.http`
(``graph_request`` against the Meta Graph/Marketing API) to surface
actionable insights — structural compliance, creative fatigue, placement
mix, audience overlap, budget pacing. Mirrors the sibling gads-cli's
``gads_lib/analyze/`` package shape and conventions exactly. None of these
modules mutate the account.
"""
