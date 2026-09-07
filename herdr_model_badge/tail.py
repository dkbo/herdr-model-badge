"""Read the end of an append-only JSONL session log without parsing the whole file.

Claude Code transcript lines routinely run past 10 KB, so a 400 KB session is only
a few dozen records; reading a fixed tail and walking it backwards finds the newest
record of interest in one pass and keeps a hook's cost flat as a session grows.
"""

import json

#: Enough to cover several of the largest records we have seen, small enough that a
#: hook stays imperceptible.
DEFAULT_TAIL_BYTES = 262_144


def lines(path, max_bytes=DEFAULT_TAIL_BYTES):
    """Yield non-blank lines from the last ``max_bytes`` of ``path``, newest first."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            chunk = handle.read()
    except OSError:
        return

    text = chunk.decode("utf-8", "replace")
    rows = text.split("\n")
    if start > 0 and rows:
        # Starting mid-file almost certainly split a record; that fragment is not JSON.
        rows.pop(0)
    for row in reversed(rows):
        row = row.strip()
        if row:
            yield row


def scan(path, wanted, max_bytes=DEFAULT_TAIL_BYTES):
    """Find the newest record matching each predicate in ``wanted``.

    ``wanted`` maps a name to a predicate over one decoded record. Returns a dict
    with an entry for each name that matched, and stops reading as soon as every
    name is accounted for.
    """
    found = {}
    pending = dict(wanted)
    for row in lines(path, max_bytes):
        if not pending:
            break
        try:
            record = json.loads(row)
        except ValueError:
            continue
        for name, predicate in list(pending.items()):
            try:
                matched = predicate(record)
            except Exception:
                matched = False
            if matched:
                found[name] = record
                del pending[name]
    return found
