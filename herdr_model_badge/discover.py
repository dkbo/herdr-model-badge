"""Locating an agent's session log when its reported session id no longer resolves.

herdr learns a session id from the agent's own SessionStart hook. That id goes stale
whenever the agent starts a new session without the hook firing again — a resume, a
compaction, an integration installed mid-session — and the pane would then carry no
badge even though it is running happily. Every session log we read records the cwd it
belongs to, so the newest log that names the pane's cwd is a verifiable second guess.
"""

import glob
import os

#: How many candidate logs a fallback search will open. Deep enough to look past a
#: handful of finished sessions in the same directory, shallow enough to stay cheap.
DEFAULT_LIMIT = 12


def newest_first(pattern, recursive=False, limit=DEFAULT_LIMIT):
    """Candidate paths matching a glob, most recently modified first."""
    try:
        paths = glob.glob(pattern, recursive=recursive)
    except OSError:
        return []

    dated = []
    for path in paths:
        try:
            dated.append((os.stat(path).st_mtime, path))
        except OSError:
            continue
    dated.sort(reverse=True)
    return [path for _, path in dated[:limit]]


def first_naming_cwd(paths, cwd, cwd_of):
    """The first path whose own records name ``cwd``, or ``None``.

    ``cwd_of`` reads the cwd a log records for itself, so a match is the log's own
    claim rather than an inference from where the file happens to live.
    """
    if not cwd:
        return None
    wanted = os.path.normpath(cwd)
    for path in paths:
        try:
            recorded = cwd_of(path)
        except OSError:
            continue
        if recorded and os.path.normpath(recorded) == wanted:
            return path
    return None
