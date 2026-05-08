from __future__ import annotations

import csv
from pathlib import Path
from typing import List, TextIO

from .models import RequestInput


def _row_to_request(raw: dict[str, str | None]) -> RequestInput:
    norm = {k.strip().lstrip("\ufeff"): (v or "").strip() for k, v in raw.items()}
    t = int(norm["time"])
    pid = norm["id"]
    src = int(norm["source"])
    dest = int(norm["dest"])
    return RequestInput(time=t, passenger_id=pid, source=src, dest=dest)


def load_requests_from_csv(path: str | Path) -> List[RequestInput]:
    p = Path(path)
    rows: List[RequestInput] = []
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        for raw in reader:
            if not raw or not any((v or "").strip() for v in raw.values() if v is not None):
                continue
            rows.append(_row_to_request(raw))
    return rows


def load_requests_from_iterable(lines: TextIO) -> List[RequestInput]:
    reader = csv.DictReader(lines)
    out: List[RequestInput] = []
    for raw in reader:
        if not raw or not any((v or "").strip() for v in raw.values() if v is not None):
            continue
        out.append(_row_to_request(raw))
    return out
