#!/usr/bin/env python3
"""Load raw log files from a folder into OpenSearch.

    make load-logs                       load everything in incoming/
    make load-logs FILE=path/to.log      load one file
    make load-logs SHIFT=now             shift timestamps so the newest
                                         line lands at "now"

The SHIFT option is what makes real captured logs usable in a demo.
A log file exported three months ago answers nothing when the question is
"what happened in the last 24 hours". Shifting the whole file preserves the
relative spacing of every event while moving the window to the present.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opensearchpy import OpenSearch, helpers
from parsers import PatternSet, doc_id

BANGKOK = timezone(timedelta(hours=7))

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
INCOMING = LOG_DIR / "incoming"
PROCESSED = LOG_DIR / "processed"
FAILED = LOG_DIR / "failed"
PATTERNS_FILE = LOG_DIR / "patterns.yaml"

INDEX = f"{os.getenv('OPENSEARCH_LOG_INDEX', 'network-logs')}-000001"

SUPPORTED_SUFFIXES = {".log", ".txt", ".ndjson", ".csv", ".gz"}


def client() -> OpenSearch:
    return OpenSearch(
        hosts=[os.getenv("OPENSEARCH_URL", "http://opensearch:9200")],
        http_compress=True,
        timeout=120,
    )


def read_lines(path: Path) -> list[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_file(path: Path, patterns: PatternSet) -> tuple[list[dict], int]:
    """Parse one file. Returns (documents, failed_count)."""
    reference = datetime.now(BANGKOK)
    fallback_device = patterns.device_from_filename(path.name)
    docs, failed = [], 0

    for line_no, line in enumerate(read_lines(path), start=1):
        if not line.strip():
            continue
        doc = patterns.parse_line(
            line, source_file=path.name, line_no=line_no,
            reference=reference, fallback_device=fallback_device,
        )
        if doc["parse_status"] == "failed":
            failed += 1
        docs.append(doc)

    return docs, failed


def shift_timestamps(docs: list[dict], mode: str) -> list[dict]:
    """Move the whole batch in time, preserving the spacing between events.

    mode="now" aligns the newest document with the current time.
    """
    if not docs or mode != "now":
        return docs

    times = [datetime.fromisoformat(d["@timestamp"]) for d in docs]
    newest = max(times)
    delta = datetime.now(BANGKOK) - newest

    for doc, ts in zip(docs, times):
        doc["@timestamp"] = (ts + delta).isoformat()

    print(f"  shifted timestamps by {delta.days}d {delta.seconds // 3600}h "
          f"so the newest line is now")
    return docs


def enrich(docs: list[dict]) -> list[dict]:
    """Fill site_code and device_role from the device id naming convention."""
    for doc in docs:
        device_id = doc.get("device_id") or ""
        parts = device_id.split("-")
        if len(parts) == 3:
            doc["device_role"] = parts[0]
            doc["site_code"] = parts[1]
        doc["ingested_at"] = datetime.now(BANGKOK).isoformat()
    return docs


def load(path: Path, patterns: PatternSet, shift: str | None, move: bool) -> dict:
    print(f"\n  {path.name}")
    docs, failed = parse_file(path, patterns)
    if not docs:
        print("    empty file, skipped")
        return {"total": 0, "failed": 0}

    docs = enrich(shift_timestamps(docs, shift or ""))

    actions = [
        {
            "_index": INDEX,
            "_id": doc_id(doc["source_file"], doc["line_no"], doc["raw_message"]),
            "_source": doc,
        }
        for doc in docs
    ]
    success, errors = helpers.bulk(client(), actions, chunk_size=500, raise_on_error=False)

    print(f"    parsed {len(docs)} lines, indexed {success}, "
          f"parse failures {failed}")
    if errors:
        print(f"    !! {len(errors)} indexing errors, first: {errors[0]}")

    # Write unparsed lines somewhere a human will actually look at them.
    if failed:
        FAILED.mkdir(parents=True, exist_ok=True)
        failed_path = FAILED / f"{path.stem}.unparsed.log"
        failed_path.write_text(
            "\n".join(d["raw_message"] for d in docs if d["parse_status"] == "failed"),
            encoding="utf-8",
        )
        print(f"    unparsed lines written to {failed_path}")
        print("    add a pattern for them in data/logs/patterns.yaml")

    if move:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(BANGKOK).strftime("%Y%m%d-%H%M%S")
        shutil.move(str(path), str(PROCESSED / f"{stamp}-{path.name}"))

    return {"total": len(docs), "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load log files into OpenSearch")
    parser.add_argument("--file", help="load a single file instead of the whole folder")
    parser.add_argument("--shift", choices=["now"],
                        help="shift timestamps so the newest line lands at now")
    parser.add_argument("--keep", action="store_true",
                        help="do not move files to processed/ after loading")
    args = parser.parse_args()

    patterns = PatternSet(PATTERNS_FILE)

    if args.file:
        files = [Path(args.file)]
    else:
        INCOMING.mkdir(parents=True, exist_ok=True)
        files = sorted(
            f for f in INCOMING.iterdir()
            if f.is_file() and f.suffix in SUPPORTED_SUFFIXES
        )

    if not files:
        print(f"\n  No files to load in {INCOMING}")
        print(f"  Drop .log / .txt / .ndjson / .gz files there and run again.")
        print(f"  Sample files are available in {LOG_DIR / 'samples'}\n")
        return 0

    print(f"\n  Loading {len(files)} file(s) into index {INDEX}")
    totals = {"total": 0, "failed": 0}
    for path in files:
        result = load(path, patterns, args.shift, move=not args.keep)
        totals["total"] += result["total"]
        totals["failed"] += result["failed"]

    client().indices.refresh(index=INDEX)
    print(f"\n  Done. {totals['total']} lines indexed, "
          f"{totals['failed']} could not be parsed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
