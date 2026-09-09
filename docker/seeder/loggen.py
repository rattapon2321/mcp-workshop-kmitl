"""Generate log documents from the declarative scenario files.

Three generation shapes are supported, one per scenario style:

  bursts   - S1: a repeated multi-line event (link down ... link up)
  ramp     - S2: a rate that climbs over the window, so the TREND is the signal
  periodic - S3: a fixed retry interval with jitter
  window   - S4: everything squeezed into one narrow time window
  spread   - baseline and filler: uniform noise

Keeping this in code and the parameters in YAML means an instructor can
retune a scenario without touching Python.
"""

from __future__ import annotations

from datetime import timedelta

from common import (
    ACCESS_DEVICES,
    DEVICE_BY_ID,
    DEVICES,
    anchor_now,
    hours_ago,
    log_line_defaults,
    random_hours_ago,
    rng,
    weighted_choice,
)


def _doc(device_id: str, ts, template: dict, scenario_id: str, overrides: dict | None = None) -> dict:
    """Render one template into an OpenSearch document."""
    dev = DEVICE_BY_ID[device_id]
    fields = log_line_defaults(device_id)
    if overrides:
        fields.update(overrides)
    message = template["message"].format(**fields)
    return {
        "@timestamp": ts.isoformat(),
        "device_id": device_id,
        "site_code": dev["site"],
        "device_role": dev["role"],
        "severity": template["severity"],
        "severity_num": template["severity_num"],
        "facility": template["facility"],
        "mnemonic": template["mnemonic"],
        "event_type": template["event_type"],
        "interface": fields.get("interface"),
        "message": message,
        "raw_message": f"{ts:%b %d %H:%M:%S} {device_id}: %{template['event_type']}: {message}",
        "source_file": f"seed:{scenario_id}",
        "parse_status": "ok",
        "scenario": scenario_id,
        "ingested_at": anchor_now().isoformat(),
    }


def _spread(spec: dict) -> list[dict]:
    """Uniform noise across a window and a set of devices."""
    device_ids = (
        [d["id"] for d in DEVICES]
        if spec.get("devices") in (None, "all")
        else list(spec["devices"])
    )
    window = spec["spread_hours_ago"] if "spread_hours_ago" in spec else spec["window_hours_ago"]
    docs = []
    for _ in range(spec["total_lines"]):
        device_id = rng.choice(device_ids)
        ts = hours_ago(random_hours_ago(window))
        docs.append(_doc(device_id, ts, weighted_choice(spec["templates"]), spec["id"]))
    return docs


def _bursts(spec: dict) -> list[dict]:
    """A repeated multi-line event, e.g. an interface flap."""
    device_id = spec["device"]
    burst = spec["bursts"]
    start_h, end_h = spec["window_hours_ago"]
    count = burst["count"]
    jitter = burst.get("jitter_minutes", 0)

    # Space bursts evenly across the window, then jitter each one so the
    # pattern does not look machine generated.
    span = abs(start_h - end_h)
    spacing = span / max(count, 1)

    docs = []
    for i in range(count):
        base_h = max(start_h - i * spacing, end_h)
        base_ts = hours_ago(base_h) + timedelta(minutes=rng.uniform(-jitter, jitter))
        for line in burst["lines"]:
            ts = base_ts + timedelta(seconds=line["offset_seconds"])
            docs.append(
                _doc(device_id, ts, line, spec["id"], {"interface": spec["interface"]})
            )
    return docs


def _ramp(spec: dict) -> list[dict]:
    """A rate that climbs across the window.

    The point of scenario S2 is that the total count is unremarkable but the
    slope is alarming. Placement is biased toward the recent end of the
    window using a power curve.
    """
    device_id = spec["device"]
    start_h, end_h = spec["window_hours_ago"]
    span = abs(start_h - end_h)
    total = spec["total_lines"]

    docs = []
    for _ in range(total):
        # u**2 concentrates samples near u=1, i.e. near "now".
        u = rng.random() ** 2
        h = start_h - u * span
        ts = hours_ago(h)
        overrides = {}
        if "interface" in spec:
            overrides["interface"] = spec["interface"]
        # Severity of the numbers themselves grows with recency.
        overrides["crc_count"] = int(3 + u * 500)
        overrides["cpu"] = int(70 + u * 26)
        docs.append(_doc(device_id, ts, weighted_choice(spec["templates"]), spec["id"], overrides))
    return docs


def _periodic(spec: dict) -> list[dict]:
    """A fixed retry interval with jitter, e.g. an adjacency that keeps failing."""
    device_id = spec["device"]
    start_h, end_h = spec["window_hours_ago"]
    interval_h = spec["periodic"]["interval_minutes"] / 60
    jitter_min = spec["periodic"].get("jitter_minutes", 0)

    docs = []
    h = start_h
    while h > end_h and len(docs) < spec["total_lines"]:
        ts = hours_ago(h) + timedelta(minutes=rng.uniform(-jitter_min, jitter_min))
        docs.append(
            _doc(device_id, ts, weighted_choice(spec["templates"]), spec["id"],
                 {"interface": spec.get("interface")})
        )
        h -= interval_h
    return docs


def _window(spec: dict) -> list[dict]:
    """Everything concentrated inside one narrow window (a maintenance night)."""
    device_id = spec["device"]
    docs = []
    for _ in range(spec["total_lines"]):
        ts = hours_ago(random_hours_ago(spec["window_hours_ago"]))
        docs.append(_doc(device_id, ts, weighted_choice(spec["templates"]), spec["id"]))
    return docs


def generate(spec: dict) -> list[dict]:
    """Dispatch to the right generator based on which keys the spec defines."""
    if "bursts" in spec:
        docs = _bursts(spec)
    elif "ramp" in spec:
        docs = _ramp(spec)
    elif "periodic" in spec:
        docs = _periodic(spec)
    elif spec.get("burst_window"):
        docs = _window(spec)
    else:
        docs = _spread(spec)

    docs.sort(key=lambda d: d["@timestamp"])
    return docs
