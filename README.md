# herdr-model-badge

A [herdr](https://herdr.dev) plugin that answers what the agents sidebar does not
tell you: **which model is each agent running, at what effort, how full is its
context, and how close is the account to its rate limits?**

```
  ○ panova              ○ panova
      claude                claude
                  ->        fable 5.1 · high · 21%
                            5h:6% · →02:10
                            wk:4% · →09-14
  ○ collect             ○ collect
      claude                claude
                            opus 5 · high · 6%
                            5h:6% · →02:10
                            wk:4% · →09-14
```

Every agent already records this in its own session log or hands it to its
statusline. The plugin reads it and gives it back to herdr as pane metadata tokens,
so the sidebar renders them like any built-in field — no patched herdr, no polling
daemon.

## Install

```bash
herdr plugin install dkbo/herdr-model-badge
```

Then tell the sidebar where to put the values, in `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents.rows_by_agent]
claude = [
  ["state_icon", "workspace", "tab"],
  [{ token = "agent", dim = true }],
  [
    { token = "$model", fg = "#cdd6f4", bold = true },
    { token = "$effort", dim = true },
    { token = "$ctx", fg = "#89b4fa" },
  ],
  [{ token = "$usage_session_pct", fg = "#a6e3a1" }, { token = "$usage_session_at", dim = true }],
  [{ token = "$usage_period_pct", fg = "#a6e3a1" }, { token = "$usage_period_at", dim = true }],
]
# codex takes the same rows; agy has no usage windows, so its rows stop at the model.
```

The full set, plus narrower and monochrome variants, is in
[`config.example.toml`](config.example.toml).

```bash
herdr server reload-config
```

Values appear as each agent next changes state, or immediately with
`herdr plugin action invoke refresh-badges --plugin herdr-model-badge`.

Give each agent only the rows it can fill — a row whose tokens are all empty is
still a row.

Requires herdr 0.8.0+ and `python3` 3.8+ on `PATH`. No third-party packages.

### One extra step for Claude Code

Claude Code keeps its rate-limit windows and true context percentage out of the
transcript entirely; the only place they appear is the JSON it hands its statusLine
command. So `$usage*` and a percentage `$ctx` need the statusline wired through the
plugin. **Codex needs none of this** — it records its own rate limits, and works
straight after install.

The plugin writes a launcher at a fixed path that survives plugin updates:

```bash
herdr plugin action invoke refresh-badges --plugin herdr-model-badge
cat "${XDG_STATE_HOME:-$HOME/.local/state}/herdr/plugins/herdr-model-badge/statusline"
```

Point Claude Code's `statusLine` at it in `~/.claude/settings.json`, passing your
existing statusline command as arguments:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/you/.local/state/herdr/plugins/herdr-model-badge/statusline bash \"$HOME/.claude/statusline-command.sh\""
  }
}
```

The launcher reads the payload, reports it to herdr, then runs your command on the
same payload and passes its output through byte for byte — **your statusline keeps
rendering exactly what it rendered before**. Drop the trailing arguments if you have
no statusline of your own and want a blank one. Nothing the plugin does can stop
your statusline from rendering: a failure is logged to stderr and the wrapped
command still runs.

## The tokens

| token | example | notes |
|---|---|---|
| `$badge` | `opus 5 · high` | `$model · $effort`, the one-row default |
| `$model` | `opus 5` | family and version, trimmed for a narrow sidebar |
| `$effort` | `high` | reasoning effort as the agent recorded it |
| `$perm` | `auto` | permission / approval mode in force |
| `$ctx` | `21%` | context used; falls back to a count (`147k`) when no percentage is available |
| `$usage_session` | `5h:6% (→02:10)` | the short rate-limit window (≤ 24h) |
| `$usage_session_pct` | `5h:6%` | just the number, for a row that colours it |
| `$usage_session_at` | `→02:10` | just the reset, for a row that keeps it quiet |
| `$usage_period` | `wk:4% (→09-14)` | the long rate-limit window (> 24h) |
| `$usage_period_pct` | `wk:4%` | |
| `$usage_period_at` | `→09-14` | |
| `$usage` | `5h:6%  wk:4%` | both windows on one narrow row, percentages only |

### Laying them out

herdr joins the tokens in a row with `" · "`, so separators come free and should
not be baked into a value. It styles a token as a whole, which is why every
composite value is also reported pre-split: spend one token on
`5h:6% (→02:10)`, or two on a coloured percentage beside a dim reset time.

That whole-token styling is static, so the plugin cannot turn a percentage red as
it climbs. The statusline it wraps still does — this is a sidebar at 26 columns,
not a status bar, and one calm colour per kind of number reads better there than
four that change under you.

Window labels come from each provider's own window length, so a 5-hour, weekly or
30-day plan all read correctly (`5h`, `wk`, `30d`) without the plugin knowing
anything about plans.

Resets are shown as an absolute time — `→02:10` today, `→09-14` further out —
rather than a countdown. A countdown is only true at the instant it is computed, and
these values refresh on events rather than on a clock, so an idle pane would sit
there showing a countdown that quietly expired. Once a window's reset passes, its
segment is dropped: the percentage that came with it belongs to a window that no
longer exists.

A token you cannot read is reported as empty rather than guessed, and a token that
stops being readable is cleared rather than left showing a stale value.

## Supported agents

| agent | source | model | effort | `$perm` | `$ctx` | `$usage_*` |
|---|---|---|---|---|---|---|
| `claude` | transcript, plus the statusLine payload | ✅ | ✅ | ✅ | `21%` with statusline, else `147k` | statusline only |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` | ✅ | ✅ | ✅ | `17k` | ✅ built in |
| `agy` | `~/.gemini/antigravity-cli/settings.json` | ✅ | ✅ | — | — | — |

Every other agent herdr recognises reports nothing, which leaves its row blank
instead of wrong. Adding one is a module in `herdr_model_badge/providers/`: expose
`AGENTS` and a `read(session, home=None)` that returns display-ready values, and
call `usage.tokens()` if that agent records rate-limit windows.

`CLAUDE_CONFIG_DIR` and `CODEX_HOME` are honoured if you have moved those homes.

## How it works

herdr's agent integrations already report each pane's session id, and
`pane.report_metadata` already accepts arbitrary tokens per pane. The plugin is the
piece in between:

1. **Event hooks** on `pane.agent_status_changed` and `pane.agent_detected` update
   the one pane that changed. A turn boundary is the only moment a new model or
   effort can be recorded, so there is nothing to poll for in between.
2. **A startup hook** fills in the agents that already existed when herdr restored
   the session, and rewrites the statusline launcher so it points at the plugin's
   current directory after an update.
3. **The statusline wrapper** catches what only Claude Code knows. Its payload
   exists for the instant the statusline renders, while the event hooks run at
   unrelated moments, so what it saw is cached per pane — otherwise every later hook
   would clear usage tokens it has no other way to learn.
4. **Reading** opens only the last 256 KB of the session log and walks it backwards
   to the newest relevant record, so cost stays flat as a session grows into
   megabytes.
5. **Reporting** compares against the tokens herdr just handed back, so a settled
   pane reports nothing at all — an event hook cannot feed itself.

herdr documents startup hooks as one-shot initialization rather than supervised
daemons, so there is no background process: every run does its work and exits. A
full sweep of three agents takes about 50 ms. The statusline path renders many times
a second, so it compares against its cache first and only reaches the socket when a
value actually changed.

## Known limits

- **Antigravity is global, not per-pane.** Antigravity CLI stores conversations as
  protobuf/SQLite blobs with no documented model field, so the plugin reads the
  CLI's current selection. Two `agy` panes therefore always show the same value.
- **`$ctx` needs the statusline to be a percentage.** Claude Code records
  `claude-opus-5` in the transcript whether the session is the 200K or the 1M
  variant, so without the statusline the limit is not knowable and `$ctx` falls back
  to an absolute count. Codex is always a count.
- **Claude usage stops updating when a pane goes quiet.** The percentages come from
  the statusline, which only renders while Claude Code is running, so an idle pane
  shows the last reading. The reset times stay correct because they are absolute,
  and the segment disappears once its window rolls over.
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

Then drop the `$badge` rows from your herdr config, and put your `statusLine`
command in `~/.claude/settings.json` back to what it wraps. Reported tokens are runtime-only —
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
python3 -m herdr_model_badge sweep     # every agent, and refresh the launcher
python3 -m herdr_model_badge clear     # drop every token this plugin owns
python3 -m herdr_model_badge launcher  # rewrite the statusline launcher only
HERDR_PLUGIN_EVENT_JSON='{"data":{"pane_id":"w1:p1"}}' \
  python3 -m herdr_model_badge event   # one pane, as an event hook would
echo '{"context_window":{"used_percentage":21}}' \
  | python3 -m herdr_model_badge statusline -- cat   # as the statusline would
```

Hook output lands in `herdr plugin log list --plugin herdr-model-badge`.

## License

MIT
