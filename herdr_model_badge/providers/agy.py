"""Antigravity CLI: the selected model, read from its settings.

Antigravity stores conversations as protobuf/SQLite blobs with no documented model
field, so this reads the CLI's current selection instead. That is the model the pane
will use for its next turn, but it is global rather than per-pane: two agy panes
always show the same value, and it changes for both when the selection changes.
"""

import json
import os

from .. import fmt

AGENTS = ("agy",)


def default_home():
    return os.path.join(os.path.expanduser("~"), ".gemini")


def read(session, home=None):
    home = home or default_home()
    path = os.path.join(home, "antigravity-cli", "settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            settings = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(settings, dict):
        return {}

    # The selection is one label with the effort in parentheses: "Gemini 3.8 Flash (High)".
    name, suffix = fmt.split_trailing_parens(settings.get("model"))
    values = {"model": fmt.generic_model(name), "effort": fmt.effort(suffix)}
    return {name_: value for name_, value in values.items() if value is not None}
