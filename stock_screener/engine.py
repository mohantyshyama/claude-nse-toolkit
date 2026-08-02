"""Loads the scoring engine ONCE and shares it.

stock_screener never reimplements a factor -- it imports analyze.compute() and
watchlist.score_at_trigger(). Both loaders must resolve to a single module
instance: analyze keeps a process-lifetime fetch cache, and two instances would
mean two caches and twice the network traffic for every scan.

Note on watchlist: it performs its own analyze load at import time, so W.A is a
DIFFERENT analyze instance from ours. That is harmless -- the only things we
call on W are score_at_trigger and action_for, which are pure functions of an
already-computed result dict and never fetch.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS = os.path.dirname(_HERE)


def _load(mod_name, filename, skill):
    """Local copy first, sibling skill second -- mirrors watchlist.load_engine()
    so the folder works whether the skills are installed together or alone."""
    local = os.path.join(_HERE, filename)
    path = local if os.path.exists(local) else os.path.join(_SKILLS, skill, filename)
    if not os.path.exists(path):
        raise SystemExit(
            f"ERROR: stock_screener needs {filename} from the {skill} skill. "
            f"Install {skill} in ~/.claude/skills/, or drop a copy of "
            f"{filename} into the stock_screener folder.")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("analyze", "analyze.py", "stock_analyser")
W = _load("wl_engine", "watchlist.py", "watchlist_analyser")
