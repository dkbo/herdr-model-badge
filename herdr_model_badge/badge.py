"""Turn one herdr AgentInfo into the token set reported back for its pane."""

from . import fmt, providers, statusline

#: Every token we own. All of them go on every report so that a value which stops
#: being readable clears instead of lingering as a stale badge.
TOKEN_NAMES = (
    "badge",
    "model",
    "effort",
    "perm",
    "ctx",
    "usage",
    "usage_session",
    "usage_period",
)


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


def tokens_for(agent, resolve=providers.for_agent, cache=None, now=None):
    """Build ``{token: value}`` for one agent, with ``None`` meaning "clear it"."""
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
        values = merge(values, cache.read(pane_id, session.get("session_id")))

    tokens = {name: values.get(name) for name in TOKEN_NAMES}
    tokens["badge"] = fmt.badge(values.get("model"), values.get("effort"))
    return tokens


def needs_report(agent, tokens):
    """True when herdr's live tokens already differ from what we would report.

    Reporting metadata makes herdr emit a pane update, which can bring us straight
    back here. Comparing against the tokens herdr just handed us in the AgentInfo
    means a settled pane reports nothing at all, so an event hook cannot feed itself.
    """
    live = agent.get("tokens") or {}
    return any(live.get(name) != value for name, value in tokens.items())
