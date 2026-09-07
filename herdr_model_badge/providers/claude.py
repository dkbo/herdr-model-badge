"""Claude Code: model, effort, permission mode and context size from the transcript."""

import glob
import os

from .. import discover, fmt, tail

AGENTS = ("claude",)

#: A pane mid-way through a long answer can push its last user turn — where the
#: permission mode lives — past the default tail. Escalate once for that alone
#: rather than paying for a large read on every hook.
PERMISSION_TAIL_BYTES = 4_194_304


def default_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )


def _is_main_assistant_turn(record):
    # Sidechain turns are subagents, which may run a different model than the pane.
    return (
        record.get("type") == "assistant"
        and not record.get("isSidechain")
        and isinstance(record.get("message"), dict)
    )


def _newest_turn(path, max_bytes=tail.DEFAULT_TAIL_BYTES):
    return tail.scan(path, {"turn": _is_main_assistant_turn}, max_bytes).get("turn")


def _recorded_cwd(path):
    turn = _newest_turn(path)
    return turn.get("cwd") if turn else None


def find_transcript(session_id, cwd, home):
    """Prefer the reported session id; fall back to the newest log naming this cwd."""
    if session_id:
        matches = sorted(glob.glob(os.path.join(home, "projects", "*", "%s.jsonl" % session_id)))
        if matches:
            return matches[0]
    candidates = discover.newest_first(os.path.join(home, "projects", "*", "*.jsonl"))
    return discover.first_naming_cwd(candidates, cwd, _recorded_cwd)


def _context_tokens(usage):
    if not isinstance(usage, dict):
        return None
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total or None


def _is_permission_turn(record):
    # Every user turn stamps the mode in force. The standalone "permission-mode"
    # record only appears on a change, so it can be absent from a whole session.
    return (
        record.get("type") == "user"
        and not record.get("isSidechain")
        and isinstance(record.get("permissionMode"), str)
    )


def _is_permission_marker(record):
    return record.get("type") == "permission-mode"


PERMISSION_SOURCES = {"perm_turn": _is_permission_turn, "perm_marker": _is_permission_marker}


def _permission_of(found):
    for key in ("perm_turn", "perm_marker"):
        record = found.get(key)
        if record is not None:
            return fmt.permission(record.get("permissionMode"))
    return None


def read(session, home=None):
    home = home or default_home()
    path = session.get("session_path") or find_transcript(
        session.get("session_id"), session.get("cwd"), home
    )
    if not path:
        return {}

    wanted = {"turn": _is_main_assistant_turn}
    wanted.update(PERMISSION_SOURCES)
    found = tail.scan(path, wanted)
    if not any(key in found for key in PERMISSION_SOURCES):
        found.update(tail.scan(path, PERMISSION_SOURCES, PERMISSION_TAIL_BYTES))

    values = {}
    turn = found.get("turn")
    if turn is not None:
        message = turn.get("message") or {}
        values["model"] = fmt.claude_model(message.get("model"))
        values["effort"] = fmt.effort(turn.get("effort"))
        values["ctx"] = fmt.token_count(_context_tokens(message.get("usage")))
    values["perm"] = _permission_of(found)
    return {name: value for name, value in values.items() if value is not None}
