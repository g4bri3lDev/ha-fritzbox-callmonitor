#!/usr/bin/env python3
"""Print the raw FRITZ!Box call list, and how this integration reads it.

Read-only: it issues TR-064 GetCallList and nothing else. Use it to check the
normalization against your own FRITZ!OS version without running Home Assistant.

    uv run python scripts/probe.py --host 192.168.178.1 --user someone

The password is read from the FRITZ_PASSWORD environment variable, or asked for
interactively, so it never lands in your shell history.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fritzconnection import FritzConnection  # noqa: E402
from fritzconnection.lib.fritzcall import FritzCall  # noqa: E402


def main() -> int:
    """Fetch the call list and print it raw and normalized."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.178.1")
    parser.add_argument("--user", required=True)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    password = os.environ.get("FRITZ_PASSWORD") or getpass("FRITZ!Box password: ")

    connection = FritzConnection(address=args.host, user=args.user, password=password)
    calls = FritzCall(fc=connection).get_calls(days=args.days)

    print(f"{len(calls)} calls in the last {args.days} days\n")  # noqa: T201

    for call in calls:
        print("raw:", {  # noqa: T201
            name: getattr(call, name)
            for name in (
                "Id",
                "Type",
                "Caller",
                "Called",
                "CallerNumber",
                "CalledNumber",
                "Name",
                "Device",
                "Date",
                "Duration",
            )
        })

        # Imported here so the raw dump still works if the integration cannot
        # be imported for some reason.
        from custom_components.fritzbox_callmonitor.models import CallRecord

        print("normalized:", CallRecord.from_call(call).as_dict(), "\n")  # noqa: T201

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
