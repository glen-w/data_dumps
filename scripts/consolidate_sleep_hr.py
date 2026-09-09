#!/usr/bin/env python3
"""One-shot: collect Sleep as Android + Mi Band HR into data_dumps_raw.

Merges session exports → sleep-export.zip; unions HR → heart_rate.csv;
archives originals.zip; deletes loose warehouse copies and collected sources.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

DATA_ROOT = Path.home() / "Documents" / "data_dumps_raw"
SLEEP_DIR = DATA_ROOT / "sleep_as_android"
HR_DIR = DATA_ROOT / "miband_hr"
QB = Path.home() / "Documents" / "quick backups"
DESKTOP = Path.home() / "Desktop"

CORE_COLS = [
    "Id",
    "Tz",
    "From",
    "To",
    "Sched",
    "Hours",
    "Rating",
    "Comment",
    "Framerate",
    "Snore",
    "Noise",
    "Cycles",
    "DeepSleep",
    "LenAdjust",
    "Geo",
]
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


@dataclass
class Session:
    core: dict[str, str]
    actigraphy: dict[str, str] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    priority: int = 99
    source: str = ""


def _classify_header(header: list[str]) -> tuple[list[str], list[int], list[int]]:
    """Return (normalized_names, actigraphy_idxs, event_idxs)."""
    names: list[str] = []
    act_idxs: list[int] = []
    ev_idxs: list[int] = []
    for i, raw in enumerate(header):
        h = (raw or "").strip().strip('"')
        names.append(h)
        if h in CORE_COLS:
            continue
        if TIME_RE.match(h):
            act_idxs.append(i)
        elif h == "Event" or h.startswith("Event"):
            ev_idxs.append(i)
        elif h and ":" in h and any(c.isdigit() for c in h):
            act_idxs.append(i)
    return names, act_idxs, ev_idxs


def _parse_rows(
    header: list[str],
    rows: list[list[str]],
    *,
    priority: int,
    source: str,
) -> dict[str, Session]:
    names, act_idxs, ev_idxs = _classify_header(header)
    core_idx = {name: names.index(name) for name in CORE_COLS if name in names}
    out: dict[str, Session] = {}
    for row in rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        core = {c: "" for c in CORE_COLS}
        for name, idx in core_idx.items():
            if idx < len(row):
                core[name] = (row[idx] or "").strip()
        sid = core.get("Id") or ""
        if not sid:
            sid = f"synth:{core.get('From', '')}|{core.get('To', '')}"
            core["Id"] = sid
        act = {}
        for i in act_idxs:
            if i < len(row) and (row[i] or "").strip():
                act[names[i]] = row[i].strip()
        events = []
        for i in ev_idxs:
            if i < len(row) and (row[i] or "").strip():
                events.append(row[i].strip())
        out[sid] = Session(
            core=core,
            actigraphy=act,
            events=events,
            priority=priority,
            source=source,
        )
    return out


def read_sleep_csv_bytes(
    data: bytes, *, priority: int, source: str
) -> dict[str, Session]:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {}
    return _parse_rows(header, list(reader), priority=priority, source=source)


def read_sleep_xlsx(path: Path, *, priority: int, source: str) -> dict[str, Session]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header_raw = next(rows_iter, None)
    if not header_raw:
        wb.close()
        return {}
    header = ["" if c is None else str(c) for c in header_raw]
    data_rows: list[list[str]] = []
    for row in rows_iter:
        if row is None:
            continue
        cells = ["" if c is None else str(c) for c in row]
        if all(not c.strip() for c in cells):
            continue
        data_rows.append(cells)
    wb.close()
    if len(data_rows) < 2:
        return {}
    return _parse_rows(header, data_rows, priority=priority, source=source)


def merge_sessions(batches: list[dict[str, Session]]) -> dict[str, Session]:
    merged: dict[str, Session] = {}
    for batch in batches:
        for sid, sess in batch.items():
            prev = merged.get(sid)
            if prev is None or sess.priority < prev.priority:
                merged[sid] = sess
    return merged


def write_sleep_csv(sessions: dict[str, Session], path: Path) -> None:
    ordered = sorted(
        sessions.values(), key=lambda s: s.core.get("From") or "", reverse=True
    )
    all_times: set[str] = set()
    max_events = 0
    for s in ordered:
        all_times.update(s.actigraphy.keys())
        max_events = max(max_events, len(s.events))

    def time_key(t: str) -> tuple[int, int]:
        try:
            h, m = t.split(":")
            return int(h), int(m)
        except ValueError:
            return (99, 99)

    times = sorted(all_times, key=time_key)
    header = CORE_COLS + times + ["Event"] * max(max_events, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for s in ordered:
            row = [s.core.get(c, "") for c in CORE_COLS]
            row.extend(s.actigraphy.get(t, "") for t in times)
            ev = list(s.events)
            while len(ev) < max(max_events, 1):
                ev.append("")
            row.extend(ev[: max(max_events, 1)])
            w.writerow(row)


def build_sleep_zip(csv_path: Path, sidecars: dict[str, bytes], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(csv_path, arcname="sleep-export.csv")
        for name, data in sidecars.items():
            zf.writestr(name, data)


def collect_hr_rows(paths: list[Path]) -> dict[str, tuple[str, str]]:
    by_dt: dict[str, tuple[str, str]] = {}
    for path in paths:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    dt = (row.get("dateTime") or "").strip()
                    if not dt:
                        continue
                    by_dt[dt] = (
                        (row.get("rate") or "").strip(),
                        (row.get("rateZone") or "").strip(),
                    )
        elif path.suffix.lower() == ".xlsx":
            wb = load_workbook(path, read_only=True, data_only=True)
            for sheet in wb.worksheets:
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, None)
                if not header:
                    continue
                cols = ["" if c is None else str(c).strip() for c in header]
                if "dateTime" not in cols or "rate" not in cols:
                    continue
                i_dt, i_rate = cols.index("dateTime"), cols.index("rate")
                i_zone = cols.index("rateZone") if "rateZone" in cols else None
                for row in rows:
                    if not row or row[i_dt] is None:
                        continue
                    dt = str(row[i_dt]).strip()
                    rate = "" if row[i_rate] is None else str(row[i_rate]).strip()
                    zone = (
                        ""
                        if i_zone is None or row[i_zone] is None
                        else str(row[i_zone]).strip()
                    )
                    by_dt[dt] = (rate, zone)
            wb.close()
    return by_dt


def write_hr_csv(by_dt: dict[str, tuple[str, str]], path: Path) -> None:
    def dt_key(s: str) -> str:
        parts = s.split(" ", 1)
        if len(parts) == 2 and "." in parts[0]:
            d, m, y = parts[0].split(".")
            return f"{y}-{m}-{d} {parts[1]}"
        return s

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dateTime", "rate", "rateZone"])
        for dt in sorted(by_dt.keys(), key=dt_key, reverse=True):
            rate, zone = by_dt[dt]
            w.writerow([dt, rate, zone])


def zip_dir_files(files: list[Path], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)


def main() -> None:
    SLEEP_DIR.mkdir(parents=True, exist_ok=True)
    HR_DIR.mkdir(parents=True, exist_ok=True)
    sleep_stage = SLEEP_DIR / "_staging"
    hr_stage = HR_DIR / "_staging"
    if sleep_stage.exists():
        shutil.rmtree(sleep_stage)
    if hr_stage.exists():
        shutil.rmtree(hr_stage)
    sleep_stage.mkdir()
    hr_stage.mkdir()

    desktop_zip = DESKTOP / "sleep-export.zip"
    old_zip = QB / "Sleep as Android" / "Sleep as Android Data.zip"
    spreadsheet = QB / "Sleep as Android" / "Sleep as Android Spreadsheet.xlsx"
    exports_xlsx = QB / "exports" / "sleep-export.xlsx"
    copia = DESKTOP / "🗄️" / "Copia de sleep-export (2).csv"

    sleep_sources: list[tuple[Path, int]] = []
    for path, pri in [
        (desktop_zip, 0),
        (old_zip, 1),
        (spreadsheet, 2),
        (exports_xlsx, 3),
        (copia, 4),
    ]:
        if path.exists():
            sleep_sources.append((path, pri))
        else:
            print(f"warn: missing sleep source {path}")

    batches: list[dict[str, Session]] = []
    staged_sleep: list[Path] = []
    sidecars: dict[str, bytes] = {}

    for path, pri in sleep_sources:
        dest = sleep_stage / path.name
        shutil.copy2(path, dest)
        staged_sleep.append(dest)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                csv_name = next(
                    n
                    for n in names
                    if n.endswith("sleep-export.csv") or Path(n).suffix == ".csv"
                )
                batches.append(
                    read_sleep_csv_bytes(
                        zf.read(csv_name), priority=pri, source=path.name
                    )
                )
                if pri == 0:
                    for side in ("prefs.xml", "noise.json", "alarms.json"):
                        if side in names:
                            sidecars[side] = zf.read(side)
        elif path.suffix.lower() == ".csv":
            batches.append(
                read_sleep_csv_bytes(path.read_bytes(), priority=pri, source=path.name)
            )
        elif path.suffix.lower() == ".xlsx":
            batches.append(read_sleep_xlsx(path, priority=pri, source=path.name))

    merged = merge_sessions(batches)
    print(f"sleep merged sessions: {len(merged)}")
    merged_csv = SLEEP_DIR / "sleep-export.csv"
    write_sleep_csv(merged, merged_csv)
    sleep_zip = SLEEP_DIR / "sleep-export.zip"
    build_sleep_zip(merged_csv, sidecars, sleep_zip)
    print(f"wrote {sleep_zip}")

    originals_sleep = SLEEP_DIR / "originals.zip"
    zip_dir_files(staged_sleep, originals_sleep)
    print(f"wrote {originals_sleep}")

    hr_files = sorted((QB / "exports").glob("Export-*.csv")) + sorted(
        (QB / "exports").glob("Export-*.xlsx")
    )
    staged_hr: list[Path] = []
    for path in hr_files:
        dest = hr_stage / path.name
        shutil.copy2(path, dest)
        staged_hr.append(dest)
    by_dt = collect_hr_rows(sorted(hr_files, key=lambda p: p.name))
    hr_csv = HR_DIR / "heart_rate.csv"
    write_hr_csv(by_dt, hr_csv)
    print(f"hr unique readings: {len(by_dt)} → {hr_csv}")
    originals_hr = HR_DIR / "originals.zip"
    zip_dir_files(staged_hr, originals_hr)
    print(f"wrote {originals_hr}")

    shutil.rmtree(sleep_stage)
    shutil.rmtree(hr_stage)

    for path, _ in sleep_sources:
        try:
            path.unlink()
            print(f"deleted source {path}")
        except OSError as e:
            print(f"warn: could not delete {path}: {e}")
    for path in hr_files:
        try:
            path.unlink()
            print(f"deleted source {path}")
        except OSError as e:
            print(f"warn: could not delete {path}: {e}")

    print("done")


if __name__ == "__main__":
    main()
