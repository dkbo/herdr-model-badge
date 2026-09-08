"""Turn one herdr AgentInfo into the reports we send back for its pane."""

import collections

from . import SOURCE, USAGE_SOURCE, fmt, providers, statusline, usage

#: The tokens that only an agent can change. Every one of them goes on every report
#: so that a value which stops being readable clears instead of lingering as a stale
#: badge. herdr styles a token as a whole, which is why the composite values are
#: reported alongside their parts: a row can spend one token on "5h:6% (→04:29)" or
#: two on a coloured percentage and a quiet reset.
DURABLE_TOKENS = (
    "badge",
    "model",
    "effort",
    "perm",
    "ctx",
    "ctx_num",
    "cost",
)

#: The tokens a clock can invalidate without the agent doing anything. They travel
#: under their own source with a ttl, so herdr drops them on a pane that has gone
#: quiet instead of leaving a percentage that nothing is confirming any more.
EPHEMERAL_TOKENS = usage.TOKEN_NAMES

#: Everything we own, which is what an uninstall has to clear. herdr accepts at most
#: 16 tokens per report; each group is well inside that on its own.
TOKEN_NAMES = DURABLE_TOKENS + EPHEMERAL_TOKENS

#: One ``pane.report_metadata`` call: what to say, and how long it stays true.
Report = collections.namedtuple("Report", "source tokens ttl_ms")


def session_of(agent):
    """Lift the session reference herdr's agent integration reported for this pane."""
    reference = agent.get("agent_session") or {}
    value = reference.get("value")
    kind = reference.get("kind")
    return {
        "pane_id": agent.get("pane_id"),
        "session_id": value if kind == "id" else None,
        "session_path": value if kind == "path" else None,
        "cwd": agent.get("cwd"),
    }


def merge(base, overlay):
    """Combine a provider's own reading with what a statusline saw.

    The transcript names the model precisely, so it keeps those fields; the
    statusline is the only source for rate limits and a true context percentage,
    so it wins those outright and fills anything the provider could not read.
    """
    merged = dict(base)
    for name, value in overlay.items():
        if value is None:
            continue
        if name in statusline.AUTHORITATIVE or merged.get(name) is None:
            merged[name] = value
    return merged


def values_for(agent, resolve=providers.for_agent, cache=None, now=None):
    """Everything readable about one agent: its own log, plus what a statusline saw."""
    session = session_of(agent)
    read = resolve(agent.get("agent"))
    values = {}
    if read is not None:
        try:
            values = read(session) or {}
        except Exception:
            # A session log can be rotated or truncated between our two reads. A blank
            # badge is the right answer; a crashed hook would leave the last one stale.
            values = {}

    pane_id = session.get("pane_id")
    if pane_id:
        cache = cache if cache is not None else statusline.Cache()
        values = merge(values, cache.read(pane_id, session.get("session_id"), now))
    return values


def _tokens(values, names):
    tokens = {name: values.get(name) for name in names}
    if "badge" in tokens:
        tokens["badge"] = fmt.badge(values.get("model"), values.get("effort"))
    return tokens


def tokens_for(agent, resolve=providers.for_agent, cache=None, now=None):
    """Build ``{token: value}`` for one agent, with ``None`` meaning "clear it"."""
    return _tokens(values_for(agent, resolve, cache, now), TOKEN_NAMES)


def reports_for(agent, resolve=providers.for_agent, cache=None, now=None):
    """One reading, split into the report that lasts and the one that expires."""
    values = values_for(agent, resolve, cache, now)
    return (
        Report(SOURCE, _tokens(values, DURABLE_TOKENS), None),
        Report(USAGE_SOURCE, _tokens(values, EPHEMERAL_TOKENS), usage.ttl_ms(values, now)),
    )


def needs_report(agent, tokens):
    """True when herdr's live tokens already differ from what we would report.

    Reporting metadata makes herdr emit a pane update, which can bring us straight
    back here. Comparing against the tokens herdr just handed us in the AgentInfo
    means a settled pane reports nothing at all, so an event hook cannot feed itself.
    """
    live = agent.get("tokens") or {}
    return any(live.get(name) != value for name, value in tokens.items())
