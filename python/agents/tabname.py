"""The one stamp behind #303: a herdr tab and the Claude session inside it share the name `<base>-<stamp>`, so the
tab's name names the session and resumes it. `herdrtab.py tab` builds the name here; the session-name mod
(unix/home/.local/share/claude-mods/session-name) holds the session to it from inside.

  stamp(now)           -> "YYYYmmddTHHMMSS.NNNNNNNNN±HH", the D61 shape of `/bin/date +%Y%m%dT%H%M%S.%N%z` with its
                          offset cut to the hour, e.g. "20261119T120850.005365000-06": the nine-digit fraction is
                          the microseconds times 1000, and a naive `now` reads as UTC.
  make_name(base, now) -> f"{base}-{stamp(now)}"; refuses an empty base or one that already carries a stamp.
  is_stamped(name)     -> True when `name` ends in a stamp (`-\\d{8}T\\d{6}\\.\\d{9}[+-]\\d{2}`).
  base_of(name)        -> `name` without its stamp (unchanged when it has none).
"""

import re
from datetime import datetime, timedelta

# A stamp at the end of a name: the D61 date shape with its offset already cut to the hour.
STAMPED = re.compile(r"-\d{8}T\d{6}\.\d{9}[+-]\d{2}$")


def stamp(now: datetime) -> str:
    """The D61 stamp of `now`: the wall clock, a nine-digit fraction, and the UTC offset cut to the hour, sign kept."""
    offset = now.utcoffset()
    if offset is None:  # a naive datetime has no offset to keep; it reads as UTC
        offset = timedelta(0)
    seconds = (
        offset.days * 86400 + offset.seconds
    )  # exact; a sub-minute offset is cut, as the fraction's tail is
    sign = "+" if seconds >= 0 else "-"
    wall = f"{now.year:04d}{now.month:02d}{now.day:02d}T{now.hour:02d}{now.minute:02d}{now.second:02d}"
    return f"{wall}.{now.microsecond * 1000:09d}{sign}{abs(seconds) // 3600:02d}"


def make_name(base: str, now: datetime) -> str:
    """`<base>-<stamp(now)>`; an empty base, or one that already carries a stamp, is a ValueError."""
    if not base:
        msg = "the base name is empty"
        raise ValueError(msg)
    if is_stamped(base):
        msg = f"the base name already carries a stamp: {base}"
        raise ValueError(msg)
    return f"{base}-{stamp(now)}"


def is_stamped(name: str) -> bool:
    """True when `name` ends in a stamp."""
    return STAMPED.search(name) is not None


def base_of(name: str) -> str:
    """`name` without its stamp; a name that carries none comes back unchanged."""
    return STAMPED.sub("", name, count=1)
