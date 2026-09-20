"""Manifest custom sources and the single user contribution file."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb
import marimo as mo
import plotly.express as px
import pytest

from data_dumps.compare_queries import fetch_monthly, list_available_series
from data_dumps.contributions import user_explorer_contributions
from data_dumps.correlation_queries import fetch_panel, list_available_metrics
from data_dumps.custom_queries import (
    comeback_entities,
    data_bounds,
    events_by_entity,
    filter_from_widgets,
    forgotten_entities,
    scoreboard,
)
from data_dumps.explorer_panels.custom import make_custom_controls, render_custom_panel
from data_dumps.ingest import main, pick_source
from data_dumps.paths import raw_dir
from data_dumps.series_catalog import SeriesSelection
from data_dumps.sources.custom import CustomSource, forbidden_column
from data_dumps.user_extensions import load_user_contributions

MINI_CSV = """ts,name,n,email,ip,phone,note
2020-01-01T08:00:00,run,1,secret@example.com,1.2.3.4,+33600000000,drop-me
2020-01-02T09:00:00,run,2,secret@example.com,1.2.3.4,+33600000000,drop-me
2020-03-01T10:00:00,old,1,other@example.com,8.8.8.8,+33600000001,drop-me
2023-01-01T11:00:00,run,3,secret@example.com,1.2.3.4,+33600000000,drop-me
"""

MANIFEST = {
    "slug": "habit",
    "label": "Habit",
    "timezone": "Europe/Paris",
    "grain": "one row per check-in",
    "file": "events.csv",
    "time": "ts",
    "entity": "name",
    "value": "n",
}

ISO_DOW = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def make_mini_custom_dir(
    path: Path, *, slug: str = "habit", label: str = "Habit"
) -> Path:
    folder = path / slug
    folder.mkdir(parents=True)
    manifest = {**MANIFEST, "slug": slug, "label": label}
    (folder / "data_dumps.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "events.csv").write_text(MINI_CSV, encoding="utf-8")
    return folder


def make_mini_custom_zip(path: Path) -> Path:
    folder = make_mini_custom_dir(path / "src")
    zip_path = path / "habit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(folder / "data_dumps.json", "Export/data_dumps.json")
        zf.write(folder / "events.csv", "Export/events.csv")
    return zip_path


def test_forbidden_column_names():
    assert forbidden_column("Email")
    assert forbidden_column("client_ip")
    assert forbidden_column("phone_number")
    assert not forbidden_column("name")
    assert not forbidden_column("ts")


def test_detect_dir_and_zip(tmp_path):
    folder = make_mini_custom_dir(tmp_path)
    zip_path = make_mini_custom_zip(tmp_path / "zip")
    source = CustomSource()
    assert source.detect(folder)
    assert source.detect(zip_path)
    assert not source.detect(tmp_path / "missing")
    assert pick_source(folder) is not None
    assert pick_source(folder).name == "custom"


def test_detect_rejects_unrelated(tmp_path):
    zip_path = tmp_path / "sleep-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sleep-export.csv", "Id,From\n1,x\n")
    assert not CustomSource().detect(zip_path)
    assert pick_source(zip_path).name == "sleep"


def test_load_drops_pii_and_keeps_other_slug(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    source = CustomSource()
    source.load(make_mini_custom_dir(tmp_path), conn)
    source.load(
        make_mini_custom_dir(tmp_path / "second", slug="reading", label="Reading"),
        conn,
    )
    inv = source.inventory(conn)
    assert inv["n_sources"] == 2
    assert inv["n_events"] == 8
    assert "loaded=reading" in inv["summary"]
    cols = [row[0] for row in conn.execute("DESCRIBE custom.events").fetchall()]
    assert "email" not in cols
    assert "ip" not in cols
    assert "phone" not in cols
    blob = conn.execute("SELECT * FROM custom.events").df().to_csv(index=False)
    assert "secret@example.com" not in blob
    assert "1.2.3.4" not in blob
    assert "+336" not in blob
    assert "drop-me" not in blob
    raw_csv = (raw_dir("custom") / "habit" / "events.csv").read_text(encoding="utf-8")
    assert "email" not in raw_csv.splitlines()[0]
    assert "secret@example.com" not in raw_csv
    habit = conn.execute(
        "SELECT count(*) FROM custom.events WHERE source_slug = 'habit'"
    ).fetchone()
    assert habit is not None and habit[0] == 4
    conn.close()


def test_load_rejects_email_entity(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    folder = make_mini_custom_dir(tmp_path)
    manifest = json.loads((folder / "data_dumps.json").read_text(encoding="utf-8"))
    manifest["entity"] = "email"
    (folder / "data_dumps.json").write_text(json.dumps(manifest), encoding="utf-8")
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    with pytest.raises(ValueError, match="email"):
        CustomSource().load(folder, conn)
    conn.close()


def test_queries_and_panel(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    CustomSource().load(make_mini_custom_dir(tmp_path), conn)
    bounds = data_bounds(conn)
    assert bounds["min_year"] == 2020
    assert bounds["max_year"] == 2023
    assert bounds["source_by_label"]["Habit"] == "habit"
    filters = filter_from_widgets(
        bounds, year_start=2020, year_end=2023, source_label="Habit"
    )
    score = scoreboard(conn, filters)
    assert int(score.iloc[0]["events"]) == 4
    assert int(score.iloc[0]["longest_streak"]) == 2
    controls = make_custom_controls(mo, bounds)
    html = render_custom_panel(
        mo=mo,
        px=px,
        conn=conn,
        bounds=bounds,
        controls=controls,
        dow_labels=ISO_DOW,
    )._repr_html_()
    for needle in (
        "Habit",
        "Scoreboard",
        "Rhythm",
        "Forgotten",
        "Comebacks",
        "Streaks",
    ):
        assert needle in html, needle
    conn.close()


def test_year_filter_forgotten_and_compare(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    CustomSource().load(make_mini_custom_dir(tmp_path), conn)
    bounds = data_bounds(conn)
    recent = filter_from_widgets(
        bounds, year_start=2023, year_end=2023, source_label="Habit"
    )
    assert int(scoreboard(conn, recent).iloc[0]["events"]) == 1
    full = filter_from_widgets(
        bounds, year_start=2020, year_end=2023, source_label="Habit"
    )
    forgotten = set(forgotten_entities(conn, full)["entity"])
    comebacks = set(comeback_entities(conn, full)["entity"])
    assert "old" in forgotten
    assert "run" in comebacks
    entities = events_by_entity(conn, full)
    assert set(entities["entity"]) == {"old", "run"}
    ids = {spec.id for spec in list_available_series(conn)}
    assert "custom_events" in ids
    assert "custom_source" in ids
    monthly = fetch_monthly(
        conn,
        [SeriesSelection("custom_events"), SeriesSelection("custom_source", "habit")],
    )
    assert not monthly.empty
    assert int(monthly.loc[monthly["series_id"] == "custom_events", "value"].sum()) == 4
    metric_ids = {spec.id for spec in list_available_metrics(conn)}
    assert "custom_events" in metric_ids
    panel = fetch_panel(conn, ["custom_events"], grain="daily")
    assert not panel.empty
    conn.close()


def test_json_and_jsonl_drop_extra_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    folder = tmp_path / "steps"
    folder.mkdir()
    (folder / "data_dumps.json").write_text(
        json.dumps(
            {
                "slug": "steps",
                "label": "Steps",
                "file": "events.json",
                "time": "ts",
                "entity": "who",
            }
        ),
        encoding="utf-8",
    )
    (folder / "events.json").write_text(
        json.dumps(
            [
                {
                    "ts": "2021-02-01T08:00:00",
                    "who": "O'Hara",
                    "email": "a@b.c",
                    "ip": "9.9.9.9",
                },
                {"ts": "2021-02-02T08:00:00", "who": "O'Hara"},
            ]
        ),
        encoding="utf-8",
    )
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    CustomSource().load(folder, conn)
    blob = conn.execute("SELECT * FROM custom.events").df().to_csv(index=False)
    assert "a@b.c" not in blob
    assert "9.9.9.9" not in blob
    assert "O'Hara" in blob
    names = events_by_entity(
        conn,
        filter_from_widgets(
            data_bounds(conn),
            year_start=2021,
            year_end=2021,
            source_label="Steps",
        ),
    )
    assert list(names["entity"]) == ["O'Hara"]

    jsonl = tmp_path / "jsonl"
    jsonl.mkdir()
    (jsonl / "data_dumps.json").write_text(
        json.dumps(
            {"slug": "ticks", "file": "events.jsonl", "time": "ts", "value": "n"}
        ),
        encoding="utf-8",
    )
    (jsonl / "events.jsonl").write_text(
        '{"ts":"2022-01-01T00:00:00","n":4,"phone":"+100"}\n'
        '{"ts":"2022-01-02T00:00:00","n":1,"phone":"+100"}\n',
        encoding="utf-8",
    )
    CustomSource().load(jsonl, conn)
    ticks = conn.execute(
        "SELECT count(*), sum(value) FROM custom.events WHERE source_slug = 'ticks'"
    ).fetchone()
    assert ticks == (2, 5.0)
    stored = conn.execute("SELECT entity, value FROM custom.events").df().to_csv()
    assert "+100" not in stored
    conn.close()


def test_rejects_traversal_and_reserved_slug(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    folder = make_mini_custom_dir(tmp_path)
    manifest = json.loads((folder / "data_dumps.json").read_text(encoding="utf-8"))
    manifest["file"] = "../events.csv"
    (folder / "data_dumps.json").write_text(json.dumps(manifest), encoding="utf-8")
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    with pytest.raises(ValueError, match="relative"):
        CustomSource().load(folder, conn)
    manifest["file"] = "events.csv"
    manifest["slug"] = "spotify"
    (folder / "data_dumps.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="spotify"):
        CustomSource().load(folder, conn)
    conn.close()


def test_reingest_replaces_slug(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    folder = make_mini_custom_dir(tmp_path)
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    source = CustomSource()
    source.load(folder, conn)
    (folder / "events.csv").write_text(
        "ts,name,n,email\n2021-05-01T12:00:00,walk,1,secret@example.com\n",
        encoding="utf-8",
    )
    source.load(folder, conn)
    rows = conn.execute(
        "SELECT entity FROM custom.events WHERE source_slug = 'habit'"
    ).fetchall()
    assert rows == [("walk",)]
    blob = conn.execute("SELECT * FROM custom.events").df().to_csv(index=False)
    assert "secret@example.com" not in blob
    conn.close()


def test_root_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    zip_path = tmp_path / "root.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data_dumps.json", json.dumps(MANIFEST))
        zf.writestr("events.csv", MINI_CSV)
    assert CustomSource().detect(zip_path)
    conn = duckdb.connect(str(tmp_path / "w.duckdb"))
    CustomSource().load(zip_path, conn)
    count = conn.execute("SELECT count(*) FROM custom.events").fetchone()
    assert count is not None and count[0] == 4
    conn.close()


def test_cli_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("DATA_DUMPS_WAREHOUSE", str(tmp_path / "catalog.duckdb"))
    zip_path = make_mini_custom_zip(tmp_path)
    assert main([str(zip_path), "--db", str(tmp_path / "catalog.duckdb")]) == 0


def _write_user_file(root: Path, body: str) -> None:
    (root / "user_contributions.py").write_text(body, encoding="utf-8")


def test_user_file_plugs_in_after_builtins(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    _write_user_file(
        tmp_path,
        """
from data_dumps.contributions import Contribution

class Marker:
    name = "marker"

    def detect(self, path):
        return path.is_file() and path.name == "marker.txt"

    def load(self, path, conn):
        conn.execute("CREATE SCHEMA IF NOT EXISTS marker")
        conn.execute("CREATE TABLE IF NOT EXISTS marker.events (n INTEGER)")
        conn.execute("INSERT INTO marker.events VALUES (1)")

    def tables(self):
        return ["marker.events"]

    def inventory(self, conn):
        return {"summary": "marker: 1"}

def bounds(_conn):
    return {"min_year": 2020, "max_year": 2020, "first_day": None, "last_day": None}

def make_controls(mo, bounds):
    return {"mo": mo, "bounds": bounds}

def render_panel(**kwargs):
    return kwargs["mo"].md("marker panel")

CONTRIBUTIONS = (
    Contribution(
        slug="marker",
        source=Marker(),
        tab_label="Marker",
        tab_icon="lucide:tag",
        gate_table=("marker", "events"),
        data_bounds=bounds,
        make_controls=make_controls,
        render_panel=render_panel,
    ),
)
""",
    )
    loaded = load_user_contributions()
    assert [item.slug for item in loaded] == ["marker"]
    plugs = user_explorer_contributions()
    assert [item.slug for item in plugs] == ["marker"]
    marker = tmp_path / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    source = pick_source(marker)
    assert source is not None and source.name == "marker"
    unrelated = tmp_path / "plain.txt"
    unrelated.write_text("nope", encoding="utf-8")
    assert pick_source(unrelated) is None
    db = tmp_path / "m.duckdb"
    assert main([str(marker), "--db", str(db)]) == 0


def test_user_detect_cannot_steal_builtin(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    _write_user_file(
        tmp_path,
        """
from data_dumps.contributions import Contribution

class Greedy:
    name = "greedy"
    def detect(self, path):
        return True
    def load(self, path, conn):
        raise AssertionError("user loader must not run")
    def tables(self):
        return []
    def inventory(self, conn):
        return {"summary": "no"}

CONTRIBUTIONS = (Contribution(slug="greedy", source=Greedy()),)
""",
    )
    zip_path = tmp_path / "sleep-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sleep-export.csv", "Id,From\n1,x\n")
    source = pick_source(zip_path)
    assert source is not None and source.name == "sleep"


def test_user_file_must_define_contributions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    _write_user_file(tmp_path, "X = 1\n")
    with pytest.raises(RuntimeError, match="CONTRIBUTIONS"):
        load_user_contributions()


def test_user_file_rejects_builtin_slug(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    _write_user_file(
        tmp_path,
        """
from data_dumps.contributions import Contribution
CONTRIBUTIONS = (Contribution(slug="spotify"),)
""",
    )
    with pytest.raises(RuntimeError, match="spotify"):
        load_user_contributions()
