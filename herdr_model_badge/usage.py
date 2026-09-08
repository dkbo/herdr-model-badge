"""Rate-limit windows: raw percentages and reset times in, sidebar segments out.

Reset times are rendered absolutely (``→04:29``) rather than as a countdown. A
countdown is only correct at the instant it is computed, and the badge is refreshed
by events rather than a clock, so an idle pane would sit there showing a countdown
that quietly expired. An absolute time stays true however long nothing happens.
"""

import datetime

#: Windows no longer than this are the short "current session" bucket; anything
#: longer is the billing-period bucket. Keeps 5h and 7d/30d in separate slots
#: without hard-coding either provider's plan shape.
SESSION_WINDOW_MINUTES = 1440

#: Beyond this, a clock time is ambiguous, so the reset shows a date instead.
CLOCK_HORIZON_SECONDS = 86400

#: How long a reading may go unrefreshed before it is dropped rather than shown.
#: These limits belong to the account, not the pane, so any other agent spending
#: against them moves the number without this pane ever hearing about it.
MAX_STALE_SECONDS = 1800

#: The tokens this module produces. ``badge`` reports them under their own source
#: precisely so herdr can drop this group alone when its expiry passes.
#:
#: Each window is reported three ways because herdr's sidebar rules cannot take a
#: value apart: a ``gt = 80`` rule only matches a value that parses completely as a
#: number, so "5h:87%" can never trip a threshold. The ``_label`` and ``_num`` pair
#: is that same reading with the unit removed — the number a rule can compare, and
#: the label it would otherwise have lost.
TOKEN_NAMES = (
    "usage",
    "usage_session",
    "usage_session_pct",
    "usage_session_at",
    "usage_session_label",
    "usage_session_num",
    "usage_period",
    "usage_period_pct",
    "usage_period_at",
    "usage_period_label",
    "usage_period_num",
)

#: Where a reading carries the moment it stops counting. Not one of TOKEN_NAMES, so
#: it never reaches herdr; it rides along in the same values dict, which means the
#: statusline cache dates its entries without needing a format of its own.
EXPIRES_KEY = "_usage_expires_at"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _now(now=None):
    return now if now is not None else datetime.datetime.now().timestamp()


def _minutes(value):
    if not _number(value):
        return None
    minutes = int(value)
    return minutes if minutes > 0 else None


def window_label(minutes):
    """``300`` -> ``5h``, ``10080`` -> ``wk``, ``43200`` -> ``30d``."""
    minutes = _minutes(minutes)
    if minutes is None:
        return None
    if minutes <= SESSION_WINDOW_MINUTES:
        return "%dh" % max(1, round(minutes / 60))
    if minutes == 10080:
        return "wk"
    return "%dd" % round(minutes / 1440)


def classify(minutes):
    """Which of the two slots a window belongs in."""
    minutes = _minutes(minutes)
    if minutes is not None and minutes <= SESSION_WINDOW_MINUTES:
        return "session"
    return "period"


def reset_label(resets_at, now=None):
    """``→04:29`` for today, ``→09-13`` further out, nothing once it has passed."""
    if not _number(resets_at):
        return None
    now = _now(now)
    remaining = resets_at - now
    if remaining <= 0:
        # The window rolled over, so whatever percentage came with it is stale.
        return None
    moment = datetime.datetime.fromtimestamp(resets_at)
    if remaining <= CLOCK_HORIZON_SECONDS:
        return moment.strftime("→%H:%M")
    return moment.strftime("→%m-%d")


def _percent(value):
    if not _number(value):
        return None
    return max(0, round(value))


def segment(minutes, percent, resets_at, now=None):
    """One window, split into ``("5h:6%", "→04:29")``.

    The two halves are reported as separate tokens because herdr styles a sidebar
    token as a whole: keeping them apart is what lets the number carry a colour
    while the reset time stays quiet.
    """
    label = window_label(minutes)
    pct = _percent(percent)
    if label is None or pct is None:
        return None, None
    reset = reset_label(resets_at, now)
    if resets_at is not None and reset is None:
        # A passed reset means this reading belongs to a window that no longer exists.
        return None, None
    return "%s:%d%%" % (label, pct), reset


def joined(parts):
    """The two halves back as one value: ``5h:6% (→04:29)``."""
    pct, reset = parts
    if pct is None:
        return None
    return "%s (%s)" % (pct, reset) if reset else pct


def compact(percentages):
    """The one-row form: percentages only, so two windows fit a narrow sidebar."""
    parts = [text for text in percentages if text]
    return "  ".join(parts) if parts else None


def tokens(windows, now=None):
    """Turn provider windows into the ``usage*`` tokens.

    Each window is ``{"minutes": int, "percent": number, "resets_at": epoch}``.
    Where a provider reports several windows in one slot, the longest wins — that
    is the limit a user is further from and more likely to be surprised by.
    """
    now = _now(now)
    best = {}
    for window in windows:
        minutes = _minutes(window.get("minutes"))
        resets_at = window.get("resets_at")
        parts = segment(minutes, window.get("percent"), resets_at, now)
        if parts[0] is None:
            continue
        slot = classify(minutes)
        if slot not in best or minutes > best[slot][0]:
            best[slot] = (minutes, parts, resets_at, window.get("percent"))

    values = {}
    for slot, (minutes, (pct, reset), _resets_at, percent) in best.items():
        values["usage_%s" % slot] = joined((pct, reset))
        values["usage_%s_pct" % slot] = pct
        if reset:
            values["usage_%s_at" % slot] = reset
        values["usage_%s_label" % slot] = window_label(minutes)
        values["usage_%s_num" % slot] = "%d" % _percent(percent)

    combined = compact([best[slot][1][0] for slot in ("session", "period") if slot in best])
    if combined:
        values["usage"] = combined
    if best:
        values[EXPIRES_KEY] = _expires_at(best.values(), now)
    return values


def _expires_at(readings, now):
    """The earlier of the two clocks that can invalidate a reading.

    A window's own reset is exact: past it, the percentage describes a window that
    no longer exists. The drift bound covers the rest, because a reading only stays
    true for as long as nothing else spends the same account's limits.
    """
    moments = [now + MAX_STALE_SECONDS]
    moments.extend(resets_at for _, _, resets_at, _pct in readings if _number(resets_at))
    return min(moments)


def ttl_ms(values, now=None):
    """How long herdr should hold these usage tokens before dropping them itself.

    Without this the badge on a pane nobody is using would keep asserting a
    percentage from whenever that pane last ran, which is the one number here that
    goes wrong on its own.
    """
    expires_at = values.get(EXPIRES_KEY)
    if not _number(expires_at):
        return None
    return max(1, int((expires_at - _now(now)) * 1000))


def drop_stale(values, now=None):
    """``values`` without the usage a clock has invalidated.

    Reported tokens expire in herdr on their own, but a cached reading would hand
    the same expired numbers straight back on the next event, with a fresh ttl. A
    reading carrying usage but no expiry predates this bookkeeping: there is no way
    to date it, so it counts as stale.
    """
    if not any(name in values for name in TOKEN_NAMES):
        return values
    expires_at = values.get(EXPIRES_KEY)
    if _number(expires_at) and expires_at > _now(now):
        return values
    stale = set(TOKEN_NAMES) | {EXPIRES_KEY}
    return {name: value for name, value in values.items() if name not in stale}


def displayed(values):
    """``values`` without the bookkeeping, for comparing one reading with another."""
    return {name: value for name, value in values.items() if name != EXPIRES_KEY}
