"""Claude Code's statusLine payload, and the cache that keeps it available.

Claude Code hands its statusLine command a JSON document on stdin containing the
only live source for a session's rate-limit windows and true context percentage —
none of it reaches the transcript. Wrapping that command lets the plugin read the
payload without changing what the statusline prints.

The payload exists only for the instant the statusline renders, while the plugin's
event hooks run at unrelated moments. The cache bridges the two: the statusline
writes what it saw, and a later status-change hook reads it back instead of
clearing usage tokens it has no other way to learn.
"""

import json
import os

from . import fmt, usage

#: Claude Code names its windows rather than giving their length.
WINDOW_MINUTES = {"five_hour": 300, "seven_day": 10080}

#: Values the statusline is authoritative for; everything else only fills a gap
#: the transcript could not.
AUTHORITATIVE = ("ctx", "ctx_num", "usage", "usage_session", "usage_period")


def _payload_dict(payload, *keys):
    for key in keys:
        if not isinstance(payload, dict):
            return {}
        payload = payload.get(key)
    return payload if isinstance(payload, dict) else {}


def session_id_of(payload):
    if not isinstance(payload, dict):
        return None
    value = payload.get("session_id")
    return value if isinstance(value, str) and value else None


def values(payload, now=None):
    """Everything the plugin can learn from one statusLine payload."""
    if not isinstance(payload, dict):
        return {}

    found = {}

    percentage = _payload_dict(payload, "context_window").get("used_percentage")
    if isinstance(percentage, (int, float)) and not isinstance(percentage, bool):
        whole = max(0, round(percentage))
        found["ctx"] = "%d%%" % whole
        # The same number without its unit, for a sidebar rule to compare. It is
        # absent whenever `$ctx` falls back to a count, because a threshold meant
        # for a percentage would otherwise colour "84k" as though it were one.
        found["ctx_num"] = "%d" % whole

    # display_name and effort.level only stand in when the transcript is unreadable.
    display = _payload_dict(payload, "model").get("display_name")
    model = fmt.generic_model(display)
    if model:
        found["model"] = model
    effort = fmt.effort(_payload_dict(payload, "effort").get("level"))
    if effort:
        found["effort"] = effort

    # What this session has cost so far. Claude Code totals it in this payload and
    # nowhere the transcript records, so there is no price table to keep and nothing
    # to estimate. Unlike a window percentage it only grows, so it needs no expiry.
    spend = fmt.money(_payload_dict(payload, "cost").get("total_cost_usd"))
    if spend:
        found["cost"] = spend

    limits = _payload_dict(payload, "rate_limits")
    windows = [
        {
            "minutes": minutes,
            "percent": _payload_dict(limits, name).get("used_percentage"),
            "resets_at": _payload_dict(limits, name).get("resets_at"),
        }
        for name, minutes in WINDOW_MINUTES.items()
    ]
    found.update(usage.tokens(windows, now))
    return found


#: herdr's own layout for HERDR_PLUGIN_STATE_DIR. Mirroring it means the statusline
#: and the event hooks agree on the cache directory even though only the hooks are
#: told where it is — get this wrong and every hook clears the usage the statusline
#: just wrote.
STATE_DIR_PARTS = ("herdr", "plugins", "herdr-model-badge")


def default_state_dir():
    """Where the cache lives. herdr names it for its hooks; derive it otherwise."""
    provided = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if provided:
        return provided
    root = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(root, *STATE_DIR_PARTS)


class Cache:
    """One small JSON file per pane. Never raises: a lost entry is only a blank badge."""

    def __init__(self, directory=None):
        self.directory = directory or default_state_dir()

    def _path(self, pane_id):
        slug = "".join(char if char.isalnum() else "_" for char in pane_id)
        return os.path.join(self.directory, "%s.json" % slug)

    def read(self, pane_id, session_id, now=None):
        try:
            with open(self._path(pane_id), encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(entry, dict):
            return {}
        # A pane outlives the agents that occupy it; only trust our own session.
        stored = entry.get("session_id")
        if stored is not None and session_id is not None and stored != session_id:
            return {}
        stored_values = entry.get("values")
        if not isinstance(stored_values, dict):
            return {}
        # A cached reading dates itself, so usage that has since expired never
        # reaches a later event to be reported again.
        return usage.drop_stale(stored_values, now)

    def write(self, pane_id, session_id, values_):
        path = self._path(pane_id)
        entry = {"session_id": session_id, "values": values_}
        try:
            os.makedirs(self.directory, exist_ok=True)
            temporary = path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(entry, handle)
            os.replace(temporary, path)
        except OSError:
            return False
        return True
