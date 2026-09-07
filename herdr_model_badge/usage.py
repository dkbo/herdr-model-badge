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


def _minutes(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return None
    now = now if now is not None else datetime.datetime.now().timestamp()
    remaining = resets_at - now
    if remaining <= 0:
        # The window rolled over, so whatever percentage came with it is stale.
        return None
    moment = datetime.datetime.fromtimestamp(resets_at)
    if remaining <= CLOCK_HORIZON_SECONDS:
        return moment.strftime("→%H:%M")
    return moment.strftime("→%m-%d")


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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
    best = {}
    for window in windows:
        minutes = _minutes(window.get("minutes"))
        parts = segment(minutes, window.get("percent"), window.get("resets_at"), now)
        if parts[0] is None:
            continue
        slot = classify(minutes)
        if slot not in best or minutes > best[slot][0]:
            best[slot] = (minutes, parts)

    values = {}
    for slot, (_, (pct, reset)) in best.items():
        values["usage_%s" % slot] = joined((pct, reset))
        values["usage_%s_pct" % slot] = pct
        if reset:
            values["usage_%s_at" % slot] = reset

    combined = compact([best[slot][1][0] for slot in ("session", "period") if slot in best])
    if combined:
        values["usage"] = combined
    return values
