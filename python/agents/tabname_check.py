"""Check tabname.py against #303's acceptance lines, offline: pure functions on fixed datetimes, no herdr tabs and no
processes. Prints one line per case and exits 1 when any fails.
"""

import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I leaves the script's directory off sys.path
import tabname

# 2026-11-19 12:08:50.000005365, six hours behind UTC.
FIXED = datetime(2026, 11, 19, 12, 8, 50, 5365, tzinfo=timezone(timedelta(hours=-6)))
# The same wall clock five and a half hours ahead: the offset is cut to the hour.
HALF = datetime(
    2026, 11, 19, 12, 8, 50, 1, tzinfo=timezone(timedelta(hours=5, minutes=30))
)
NAME = "w1-20261119T120850.005365000-06"


def refused(base: str) -> bool:
    """make_name refuses the base with a ValueError."""
    try:
        tabname.make_name(base, FIXED)
    except ValueError:
        return True
    return False


def cases() -> list[tuple[str, Callable[[], bool]]]:
    return [
        (
            "stamp keeps the sign and cuts -06:00 to -06",
            lambda: tabname.stamp(FIXED) == "20261119T120850.005365000-06",
        ),
        (
            "stamp cuts +05:30 to +05",
            lambda: tabname.stamp(HALF) == "20261119T120850.000001000+05",
        ),
        (
            "microsecond 1 pads to nine digits",
            lambda: (
                tabname.stamp(datetime(2026, 11, 19, 12, 8, 50, 1, tzinfo=UTC))
                == "20261119T120850.000001000+00"
            ),
        ),
        (
            "microsecond 0 pads to nine zeros",
            lambda: (
                tabname.stamp(datetime(2026, 11, 19, 12, 8, 50, tzinfo=UTC))
                == "20261119T120850.000000000+00"
            ),
        ),
        (
            "a naive datetime reads as UTC",
            lambda: (
                tabname.stamp(datetime(2026, 11, 19, 12, 8, 50))
                == "20261119T120850.000000000+00"
            ),
        ),
        (
            "make_name joins base and stamp",
            lambda: tabname.make_name("w1", FIXED) == NAME,
        ),
        ("an empty base is refused", lambda: refused("")),
        ("a base that already carries a stamp is refused", lambda: refused(NAME)),
        (
            "is_stamped takes the cut offset at the end only",
            lambda: (
                tabname.is_stamped(NAME)
                and tabname.is_stamped("a-b-20261119T120850.005365000+05")
                and not tabname.is_stamped("w1")
                and not tabname.is_stamped("w1-20261119T120850")
                and not tabname.is_stamped("w1-20261119T120850.005365000")
                and not tabname.is_stamped("w1-20261119T120850.005365000-0600")
            ),
        ),
        (
            "base_of strips the stamp and round-trips make_name",
            lambda: (
                tabname.base_of(NAME) == "w1"
                and tabname.base_of("w1") == "w1"
                and tabname.base_of(tabname.make_name("w1", FIXED)) == "w1"
            ),
        ),
    ]


def main() -> None:
    failed = 0
    for name, case in cases():
        ok = case()
        failed += not ok
        sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
