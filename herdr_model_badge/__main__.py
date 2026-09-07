"""Entry point for every command the manifest declares.

Modes:
  sweep   every agent in the session (startup hook, and the refresh action)
  event   the one pane named by HERDR_PLUGIN_EVENT_JSON (event hooks)
  clear   drop every token this plugin owns (uninstall helper)

Nothing here is long-running: herdr starts plugin commands one-shot, so each run
does its work and exits. Failures are logged to stderr, which herdr collects into
``herdr plugin log list``, and never raise into the host.
"""

import argparse
import json
import os
import sys

from . import SOURCE, badge
from .api import Client, HerdrError

CLEARED = {name: None for name in badge.TOKEN_NAMES}


def log(message):
    sys.stderr.write("herdr-model-badge: %s\n" % message)


def event_pane_id(raw):
    """Pull the pane id out of HERDR_PLUGIN_EVENT_JSON.

    herdr passes the event envelope, so the pane id sits under ``data``; older and
    newer shapes have carried it at the top level, so accept either.
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    for candidate in (payload, payload.get("data") if isinstance(payload, dict) else None):
        if isinstance(candidate, dict) and isinstance(candidate.get("pane_id"), str):
            return candidate["pane_id"]
    return None


def apply_to(client, agent):
    """Report one agent's tokens, and return whether anything actually changed."""
    pane_id = agent.get("pane_id")
    if not pane_id:
        return False
    tokens = badge.tokens_for(agent)
    if not badge.needs_report(agent, tokens):
        return False
    client.report(pane_id, SOURCE, tokens)
    return True


def sweep(client):
    updated = 0
    for agent in client.agents():
        try:
            if apply_to(client, agent):
                updated += 1
        except HerdrError as exc:
            log("skipped %s: %s" % (agent.get("pane_id"), exc))
    return updated


def event(client):
    pane_id = event_pane_id(os.environ.get("HERDR_PLUGIN_EVENT_JSON"))
    if not pane_id:
        log("no pane id in HERDR_PLUGIN_EVENT_JSON; nothing to update")
        return 0
    try:
        agent = client.agent(pane_id)
    except HerdrError:
        # The pane lost its agent (exited, or was released). Clear our tokens so the
        # sidebar does not keep showing the model of an agent that is gone.
        client.report(pane_id, SOURCE, CLEARED)
        return 1
    agent.setdefault("pane_id", pane_id)
    return 1 if apply_to(client, agent) else 0


def clear(client):
    cleared = 0
    for agent in client.agents():
        pane_id = agent.get("pane_id")
        if pane_id and badge.needs_report(agent, CLEARED):
            client.report(pane_id, SOURCE, CLEARED)
            cleared += 1
    return cleared


MODES = {"sweep": sweep, "event": event, "clear": clear}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="herdr-model-badge", description=__doc__)
    parser.add_argument("mode", choices=sorted(MODES))
    parser.add_argument(
        "--notify",
        action="store_true",
        help="show a herdr notification with the result (used by the refresh action)",
    )
    args = parser.parse_args(argv)

    client = Client()
    if not client.available():
        log("not running under herdr (HERDR_SOCKET_PATH is unset or missing)")
        return 0

    try:
        count = MODES[args.mode](client)
    except HerdrError as exc:
        log(str(exc))
        return 1

    if args.notify:
        noun = "badge" if count == 1 else "badges"
        try:
            client.notify("herdr-model-badge", "%d %s updated" % (count, noun))
        except HerdrError as exc:
            log("notification failed: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
