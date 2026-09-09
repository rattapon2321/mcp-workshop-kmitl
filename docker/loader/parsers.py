"""Turn raw log lines into OpenSearch documents.

Design rules, learned the hard way in real ingestion work:

1. Never drop a line silently. A line that matches no pattern is still
   indexed with parse_status="failed" and its raw text preserved, so the
   gap is visible instead of invisible.

2. Patterns live in YAML, not here. Adding a vendor format must not require
   touching Python or rebuilding the image.

3. Document ids are content-derived, so re-running the loader on the same
   file updates rather than duplicates.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

BANGKOK = timezone(timedelta(hours=7))


class PatternSet:
    def __init__(self, config_path: Path):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.patterns = []
        for entry in config["patterns"]:
            # re.VERBOSE lets the YAML keep the pattern readable across lines.
            entry["compiled"] = re.compile(entry["regex"], re.VERBOSE)
            self.patterns.append(entry)
        self.severity_map = config.get("severity_map", {})
        self.interface_re = re.compile(config["interface_regex"])
        self.device_from_filename_re = re.compile(config["device_from_filename_regex"])

    # ------------------------------------------------------------------

    def _parse_timestamp(self, text: str, pattern: dict, reference: datetime) -> datetime:
        fmt = pattern["timestamp_format"]
        if fmt == "iso8601":
            ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=BANGKOK)

        ts = datetime.strptime(text, fmt).replace(tzinfo=BANGKOK)
        if pattern.get("timestamp_missing_year"):
            # Classic syslog omits the year. Assume the most recent occurrence
            # that is not in the future relative to the reference time.
            # Compare only after attaching a timezone, otherwise this raises
            # "can't compare offset-naive and offset-aware datetimes".
            ts = ts.replace(year=reference.year)
            if ts > reference + timedelta(days=1):
                ts = ts.replace(year=reference.year - 1)
        return ts

    def parse_line(
        self,
        line: str,
        source_file: str,
        line_no: int,
        reference: datetime,
        fallback_device: str | None = None,
    ) -> dict:
        raw = line.rstrip("\n")

        for pattern in self.patterns:
            match = pattern["compiled"].match(raw)
            if not match:
                continue
            groups = match.groupdict()
            try:
                ts = self._parse_timestamp(groups["ts"], pattern, reference)
            except ValueError:
                continue

            message = groups.get("msg", "")
            severity_num = groups.get("sev")
            interface = groups.get("interface")
            if not interface:
                found = self.interface_re.search(message)
                interface = found.group(1) if found else None

            facility = groups.get("facility")
            mnemonic = groups.get("mnemonic")

            return {
                "@timestamp": ts.isoformat(),
                "device_id": groups.get("host") or fallback_device,
                "severity": self.severity_map.get(str(severity_num), "info"),
                "severity_num": int(severity_num) if severity_num else 6,
                "facility": facility,
                "mnemonic": mnemonic,
                "event_type": f"{facility}-{mnemonic}" if facility and mnemonic else None,
                "interface": interface,
                "message": message,
                "raw_message": raw,
                "source_file": source_file,
                "line_no": line_no,
                "parse_status": "ok",
                "parser": pattern["name"],
            }

        # Nothing matched. Keep the line anyway.
        return {
            "@timestamp": reference.isoformat(),
            "device_id": fallback_device,
            "severity": "info",
            "severity_num": 6,
            "message": raw,
            "raw_message": raw,
            "source_file": source_file,
            "line_no": line_no,
            "parse_status": "failed",
            "parser": None,
        }

    # ------------------------------------------------------------------

    def device_from_filename(self, filename: str) -> str | None:
        match = self.device_from_filename_re.search(filename.upper())
        return match.group(1) if match else None


def doc_id(source_file: str, line_no: int, raw: str) -> str:
    """Stable id so re-loading a file updates instead of duplicating."""
    digest = hashlib.sha1(f"{source_file}:{line_no}:{raw}".encode()).hexdigest()
    return digest[:24]
