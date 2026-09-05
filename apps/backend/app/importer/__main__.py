"""CLI: python -m app.importer [--reset] [--owner NAME] <zip|folder> [...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import import_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.importer",
        description="Import a Facebook Messenger export into the local archive.",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="One or more .zip files or already-extracted export folders",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Wipe the database before importing"
    )
    parser.add_argument(
        "--owner",
        help="Your own display name (overrides auto-detection of the archive owner)",
    )
    parser.add_argument(
        "--delete-zips",
        action="store_true",
        help="Delete each zip once it has been unpacked (the setup wizard does this)",
    )
    args = parser.parse_args(argv)

    try:
        import_sources(
            args.sources, reset=args.reset, owner=args.owner, delete_zips=args.delete_zips
        )
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
