"""Display formatting: long provider model ids in, short sidebar labels out.

The agents sidebar is 18-36 columns wide, so everything here trims hard and
returns ``None`` whenever a value is missing rather than inventing a placeholder.
"""

import math
import re

#: Anthropic puts the family before the version in current ids and after it in the
#: 3.x ones, so we look the family up instead of relying on position.
CLAUDE_FAMILIES = ("opus", "sonnet", "haiku", "fable")

_DATE_SUFFIX = re.compile(r"-\d{8}$")
_BEDROCK_VERSION_SUFFIX = re.compile(r"-v\d+(?::\d+)?$")
_CONTEXT_VARIANT_SUFFIX = re.compile(r"\[[^\]]*\]$")
_TRAILING_PARENS = re.compile(r"\s*\(([^)]*)\)\s*$")


def _clean(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def claude_model(raw):
    """``claude-haiku-4-5-20251001`` -> ``haiku 4.5``."""
    value = _clean(raw)
    if value is None:
        return None
    value = _CONTEXT_VARIANT_SUFFIX.sub("", value.lower()).strip()
    # Bedrock and Vertex prefix the id with their own routing; keep the model part.
    marker = value.rfind("claude-")
    if marker != -1:
        value = value[marker + len("claude-"):]
    value = _BEDROCK_VERSION_SUFFIX.sub("", value)
    value = _DATE_SUFFIX.sub("", value)
    if not value:
        return None

    parts = [part for part in value.split("-") if part]
    families = [part for part in parts if part in CLAUDE_FAMILIES]
    if not families:
        return " ".join(parts) or None
    family = families[0]
    version = ".".join(part for part in parts if part != family)
    return "%s %s" % (family, version) if version else family


def generic_model(raw):
    """``gpt-5-codex`` -> ``gpt 5 codex``. Used for providers with no id convention."""
    value = _clean(raw)
    if value is None:
        return None
    value = _CONTEXT_VARIANT_SUFFIX.sub("", value.lower()).strip()
    value = _DATE_SUFFIX.sub("", value)
    return " ".join(value.replace("-", " ").split()) or None


def split_trailing_parens(raw):
    """``Gemini 3.8 Flash (High)`` -> ``("Gemini 3.8 Flash", "High")``."""
    value = _clean(raw)
    if value is None:
        return None, None
    match = _TRAILING_PARENS.search(value)
    if match is None:
        return value, None
    return value[: match.start()].strip() or None, _clean(match.group(1))


def effort(raw):
    value = _clean(raw)
    return value.lower() if value else None


def permission(raw):
    """Provider permission/approval labels, spaced out enough to read at a glance."""
    value = _clean(raw)
    if value is None:
        return None
    # Claude Code reports camelCase modes; everyone else already uses words.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return spaced.lower()


def token_count(raw):
    """``104272`` -> ``104k``. Absolute, because the context limit is not knowable."""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    if raw < 1000:
        return str(raw)
    if raw < 999_500:
        return "%dk" % round(raw / 1000)
    return "%.1fM" % (raw / 1_000_000)


def money(raw):
    """``1.2345`` -> ``$1.23``. Exact: the only source for this is a real total.

    Precision gives way to width as the number grows, because a sidebar has room
    for cents on a short session and not for cents on a long one.
    """
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    if not math.isfinite(raw) or raw < 0:
        return None
    if raw < 10:
        return "$%.2f" % raw
    if raw < 100:
        return "$%.1f" % raw
    if raw < 1000:
        return "$%d" % round(raw)
    return "$%.1fk" % (raw / 1000)


def badge(model, effort_label):
    """The one-line sidebar label: ``opus 5 · high``."""
    parts = [part for part in (model, effort_label) if part]
    return " · ".join(parts) if parts else None
