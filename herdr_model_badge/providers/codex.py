"""Codex: model, effort, approval policy and context size from the rollout log."""

import os

from .. import discover, fmt, tail, usage

AGENTS = ("codex",)


def default_home():
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def _is_turn_context(record):
    return record.get("type") == "turn_context"


def _rollout_glob(home, session_id="*"):
    # Rollouts live under sessions/YYYY/MM/DD and end with the session id.
    return os.path.join(home, "sessions", "**", "*%s.jsonl" % session_id)


def _recorded_cwd(path):
    turn = tail.scan(path, {"turn": _is_turn_context}).get("turn")
    return (turn.get("payload") or {}).get("cwd") if turn else None


def find_rollout(session_id, cwd, home):
    """Prefer the reported session id; fall back to the newest log naming this cwd."""
    if session_id:
        matches = discover.newest_first(_rollout_glob(home, session_id), recursive=True, limit=1)
        if matches:
            return matches[0]
    candidates = discover.newest_first(_rollout_glob(home), recursive=True)
    return discover.first_naming_cwd(candidates, cwd, _recorded_cwd)


def _is_token_count(record):
    return record.get("type") == "event_msg" and (record.get("payload") or {}).get(
        "type"
    ) == "token_count"


def _context_tokens(record):
    info = (record.get("payload") or {}).get("info") or {}
    usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
    value = usage.get("input_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _usage_windows(record):
    """Codex names each window's length, so the labels come from the data."""
    limits = (record.get("payload") or {}).get("rate_limits") or {}
    windows = []
    for slot in ("primary", "secondary"):
        window = limits.get(slot)
        if not isinstance(window, dict):
            continue
        windows.append(
            {
                "minutes": window.get("window_minutes"),
                "percent": window.get("used_percent"),
                "resets_at": window.get("resets_at"),
            }
        )
    return windows


def read(session, home=None):
    home = home or default_home()
    path = session.get("session_path") or find_rollout(
        session.get("session_id"), session.get("cwd"), home
    )
    if not path:
        return {}

    found = tail.scan(path, {"turn": _is_turn_context, "usage": _is_token_count})

    values = {}
    turn = found.get("turn")
    if turn is not None:
        payload = turn.get("payload") or {}
        values["model"] = fmt.generic_model(payload.get("model"))
        values["effort"] = fmt.effort(payload.get("effort"))
        values["perm"] = fmt.permission(payload.get("approval_policy"))
    counted = found.get("usage")
    if counted is not None:
        values["ctx"] = fmt.token_count(_context_tokens(counted))
        values.update(usage.tokens(_usage_windows(counted)))
    return {name: value for name, value in values.items() if value is not None}
