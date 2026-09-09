#!/usr/bin/env python3
"""Watch the incoming folder and load new files automatically.

    make load-logs-watch

Useful while teaching ingestion: drop a file on the host and the class sees
it appear in OpenSearch Dashboards a second later. Not intended for
production - real deployments use Filebeat or Fluent Bit, which handle
back-pressure, retries and file rotation. That comparison is covered in
instructions/day3/scale-notes.md
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from load_logs import INCOMING, PATTERNS_FILE, SUPPORTED_SUFFIXES, load
from parsers import PatternSet

POLL_SECONDS = float(os.getenv("WATCH_POLL_SECONDS", "2"))
# A file may still be copying. Wait until its size stops changing.
STABLE_CHECKS = 2


def main() -> None:
    patterns = PatternSet(PATTERNS_FILE)
    INCOMING.mkdir(parents=True, exist_ok=True)
    sizes: dict[Path, tuple[int, int]] = {}

    print(f"\n  Watching {INCOMING} (Ctrl-C to stop)\n")
    while True:
        for path in sorted(INCOMING.iterdir()):
            if not path.is_file() or path.suffix not in SUPPORTED_SUFFIXES:
                continue
            size = path.stat().st_size
            previous_size, stable = sizes.get(path, (-1, 0))
            if size == previous_size:
                stable += 1
            else:
                stable = 0
            sizes[path] = (size, stable)

            if stable >= STABLE_CHECKS:
                print(f"  [{datetime.now():%H:%M:%S}] new file detected")
                load(path, patterns, shift=None, move=True)
                sizes.pop(path, None)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
