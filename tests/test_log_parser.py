"""Log parsing.

The critical property is not that everything parses - it is that nothing is
lost silently. A line that matches no pattern must still be indexed and
flagged, because invisible data loss in ingestion is far worse than visible
bad data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from parsers import PatternSet, doc_id

ROOT = Path(__file__).resolve().parents[1]
BANGKOK = timezone(timedelta(hours=7))


@pytest.fixture(scope="module")
def patterns() -> PatternSet:
    return PatternSet(ROOT / "data" / "logs" / "patterns.yaml")


@pytest.fixture(scope="module")
def reference() -> datetime:
    return datetime.now(BANGKOK)


@pytest.mark.parametrize("filename,expected_ok", [
    ("01-cisco-ios-APE-NBI-03.log", 14),
    ("02-huawei-vrp-PE-BKK-02.log", 7),
    ("03-rfc5424-CR-BKK-01.log", 5),
    ("04-mixed-and-broken.log", 4),
])
def test_sample_files_parse_as_expected(patterns, reference, filename, expected_ok):
    path = ROOT / "data" / "logs" / "samples" / filename
    fallback = patterns.device_from_filename(path.name)
    ok = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        doc = patterns.parse_line(line, path.name, i, reference, fallback)
        if doc["parse_status"] == "ok":
            ok += 1
    assert ok == expected_ok


def test_unparseable_lines_are_kept_not_dropped(patterns, reference):
    doc = patterns.parse_line(
        "!!! CORRUPTED BLOCK !!! binary garbage", "x.log", 1, reference, None
    )
    assert doc["parse_status"] == "failed"
    assert doc["raw_message"]          # the original line survives
    assert doc["@timestamp"]           # still indexable


def test_cisco_fields_extracted(patterns, reference):
    doc = patterns.parse_line(
        "Aug 23 01:14:02 APE-NBI-03: %LINK-3-UPDOWN: Interface Te0/1/2, changed state to down",
        "x.log", 1, reference, None,
    )
    assert doc["device_id"] == "APE-NBI-03"
    assert doc["event_type"] == "LINK-UPDOWN"
    assert doc["severity"] == "error"
    assert doc["interface"] == "Te0/1/2"


def test_doc_id_is_stable(patterns):
    """Re-loading the same file must update, not duplicate."""
    a = doc_id("f.log", 1, "same line")
    b = doc_id("f.log", 1, "same line")
    c = doc_id("f.log", 2, "same line")
    assert a == b and a != c
