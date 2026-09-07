"""Provider registry, keyed by the canonical agent kind herdr reports."""

from . import agy, claude, codex

MODULES = (claude, codex, agy)

_BY_AGENT = {
    agent: module.read for module in MODULES for agent in module.AGENTS
}

#: Agent kinds we can read something for. Every other kind reports no tokens, which
#: is what leaves its sidebar row blank rather than stale.
SUPPORTED = tuple(sorted(_BY_AGENT))


def for_agent(kind):
    """Return the reader for an agent kind, or ``None`` if we cannot read that agent."""
    if not isinstance(kind, str):
        return None
    return _BY_AGENT.get(kind.strip().lower())
