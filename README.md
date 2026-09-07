# herdr-model-badge

A [herdr](https://herdr.dev) plugin that answers the one thing the agents sidebar
does not tell you: **which model, at which reasoning effort, is each agent actually
running?**

```
  ○ panova                 ○ panova
      claude                   claude
                     ->        fable 5.1 · high
  ○ collect                ○ collect
      claude                   claude
                               opus 5 · high
```

Each agent already writes its model and effort into its own session log. This plugin
reads that log and hands the values back to herdr as pane metadata tokens, so the
sidebar renders them like any built-in field — no patched herdr, no polling daemon.

## Install

```bash
herdr plugin install dkbo/herdr-model-badge
```

Then tell the sidebar where to put the badge, in `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents.rows_by_agent]
claude = [["state_icon", "workspace", "tab"], ["agent"], [{ token = "$badge", dim = true }]]
codex = [["state_icon", "workspace", "tab"], ["agent"], [{ token = "$badge", dim = true }]]
agy = [["state_icon", "workspace", "tab"], ["agent"], [{ token = "$badge", dim = true }]]
```

```bash
herdr server reload-config
```

Badges appear as each agent next changes state, or immediately with
`herdr plugin action invoke refresh-badges --plugin herdr-model-badge`.

`config.example.toml` has other layouts: one rule for every agent, replacing the
`claude` line instead of adding a row, and composing the individual tokens yourself.

Requires herdr 0.8.0+ and `python3` 3.8+ on `PATH`. No third-party packages.

## The tokens

| token | example | notes |
|---|---|---|
| `$badge` | `opus 5 · high` | `$model · $effort`, the one-row default |
| `$model` | `opus 5` | family and version, trimmed for a narrow sidebar |
| `$effort` | `high` | reasoning effort as the agent recorded it |
| `$perm` | `auto` | permission / approval mode in force |
| `$ctx` | `147k` | tokens in context on the agent's last turn |

A token you cannot read is reported as empty rather than guessed, and a token that
stops being readable is cleared rather than left showing a stale value.

## Supported agents

| agent | source | model | effort | `$perm` | `$ctx` |
|---|---|---|---|---|---|
| `claude` | `~/.claude/projects/*/<session>.jsonl` | ✅ | ✅ | ✅ | ✅ |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` | ✅ | ✅ | ✅ | ✅ |
| `agy` | `~/.gemini/antigravity-cli/settings.json` | ✅ | ✅ | — | — |

Every other agent herdr recognises reports nothing, which leaves its row blank
instead of wrong. Adding one is a module in `herdr_model_badge/providers/`: expose
`AGENTS` and a `read(session, home=None)` that returns display-ready values.

`CLAUDE_CONFIG_DIR` and `CODEX_HOME` are honoured if you have moved those homes.

## How it works

herdr's agent integrations already report each pane's session id, and
`pane.report_metadata` already accepts arbitrary tokens per pane. The plugin is the
piece in between:

1. **Event hooks** on `pane.agent_status_changed` and `pane.agent_detected` update
   the one pane that changed. A turn boundary is the only moment a new model or
   effort can be recorded, so there is nothing to poll for in between.
2. **A startup hook** fills in the agents that already existed when herdr restored
   the session.
3. **Reading** opens only the last 256 KB of the session log and walks it backwards
   to the newest relevant record, so cost stays flat as a session grows into
   megabytes.
4. **Reporting** compares against the tokens herdr just handed back, so a settled
   pane reports nothing at all — an event hook cannot feed itself.

herdr documents startup hooks as one-shot initialization rather than supervised
daemons, so there is no background process: every run does its work and exits. A
full sweep of three agents takes about 50 ms.

## Known limits

- **Antigravity is global, not per-pane.** Antigravity CLI stores conversations as
  protobuf/SQLite blobs with no documented model field, so the plugin reads the
  CLI's current selection. Two `agy` panes therefore always show the same value.
- **No context percentage.** Claude Code records `claude-opus-5` whether the session
  is the 200K or the 1M variant, so the limit is not knowable and `$ctx` is an
  absolute count.
- **Resumed sessions rely on a fallback.** herdr learns a session id once, from the
  agent's `SessionStart` hook; a resume or compaction can leave that id pointing at
  nothing. When the id misses, the plugin takes the newest session log that records
  the pane's own cwd. Two agents of the same kind in the same directory can then
  briefly share a badge until each reports its own session.

## Uninstall

Clear the tokens first, so no badge is left behind in a running session:

```bash
herdr plugin action invoke clear-badges --plugin herdr-model-badge
herdr plugin uninstall herdr-model-badge
```

Then drop the `$badge` rows from your config. Reported tokens are runtime-only —
they never reach `session.json` — so restarting herdr also clears them.

## Development

```bash
git clone https://github.com/dkbo/herdr-model-badge
cd herdr-model-badge
python3 -m unittest discover -s tests -t .    # no dependencies
herdr plugin link "$PWD"                      # run it from the checkout
```

The three modes are runnable by hand from the plugin root:

```bash
python3 -m herdr_model_badge sweep    # every agent
python3 -m herdr_model_badge clear    # drop every token this plugin owns
HERDR_PLUGIN_EVENT_JSON='{"data":{"pane_id":"w1:p1"}}' \
  python3 -m herdr_model_badge event  # one pane, as an event hook would
```

Hook output lands in `herdr plugin log list --plugin herdr-model-badge`.

## License

MIT
