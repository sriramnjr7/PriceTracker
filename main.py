"""Entry point: `python main.py <command> [options]`."""

from __future__ import annotations

import sys


def _enable_utf8_stdio() -> None:
    """Windows consoles default to cp1252; force UTF-8 so ₹/emoji print cleanly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover
                pass


def main() -> int:
    _enable_utf8_stdio()
    from cli import build_parser, run

    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())