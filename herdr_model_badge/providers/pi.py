"""Pi: model and thinking level from the latest persisted session branch."""

import glob
import json
import os

from .. import discover, fmt, tail

AGENTS = ("pi",)

# Older Pi versions only record thinking changes, not the level on each response.
# Look further back once, but keep hook work bounded even on very large sessions.
SETTINGS_TAIL_BYTES = 4 * 1024 * 1024


def default_home():
    return os.path.expanduser(
        os.environ.get("PI_CODING_AGENT_DIR") or os.path.join("~", ".pi", "agent")
    )


def find_session(session_id, home):
    """Resolve an exact session id; never guess between panes sharing a cwd."""
    if not isinstance(session_id, str) or not session_id:
        return None
    pattern = os.path.join(home, "sessions", "*", "*_" + glob.escape(session_id) + ".jsonl")
    matches = discover.newest_first(pattern, limit=1)
    return matches[0] if matches else None


def _model(raw):
    if isinstance(raw, str) and "claude-" in raw.lower():
        return fmt.claude_model(raw)
    return fmt.generic_model(raw)


def _settings(path, max_bytes):
    values = {}
    parent = None
    for line in tail.lines(path, max_bytes):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        if record.get("type") == "session":
            continue
        if parent is not None and record["id"] != parent:
            continue

        kind = record.get("type")
        if kind == "model_change" and "model" not in values:
            values["model"] = _model(record.get("modelId"))
        elif kind == "thinking_level_change" and "effort" not in values:
            values["effort"] = fmt.effort(record.get("thinkingLevel"))
        elif kind == "message":
            message = record.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                if "model" not in values and "model" in message:
                    values["model"] = _model(message["model"])
                if "effort" not in values and "thinkingLevel" in message:
                    values["effort"] = fmt.effort(message["thinkingLevel"])

        # Walk parents, not just file order: another branch can use another model.
        parent = record.get("parentId")
        if parent is None or ("model" in values and "effort" in values):
            return values, True
    return values, False


def read(session, home=None):
    home = home or default_home()
    path = session.get("session_path") or find_session(session.get("session_id"), home)
    if not path:
        return {}

    values, complete = _settings(path, tail.DEFAULT_TAIL_BYTES)
    if not complete:
        values, _ = _settings(path, SETTINGS_TAIL_BYTES)
    return {name: value for name, value in values.items() if value is not None}
