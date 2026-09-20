# Custom sources

Index: [Getting your data](../getting-your-data.md).

| Slug | Timezone | Explorer |
|------|----------|----------|
| `custom` | manifest, default `Europe/Paris` | Custom tab |

This is how you add a source that is not one of the built-in exports. It plugs in, ingests, and shows up on the dashboard without editing the repository. There is no plugin directory and no entry point. Two paths:

1. A **manifest** (no Python) — a folder or zip with `data_dumps.json` and one table file. The Custom tab draws the charts.
2. One **Python file** at `$DATA_DUMPS_ROOT/user_contributions.py` — a real `Source` plus an optional panel, for when the manifest is not enough.

Stop the dashboard before ingest. See [WAREHOUSE.md](../../WAREHOUSE.md).

## Manifest

Point `ingest` at a folder, or a zip, that contains `data_dumps.json` at the root or inside a single enclosing folder.

```json
{
  "slug": "habit",
  "label": "Habit",
  "icon": "lucide:check",
  "timezone": "Europe/Paris",
  "grain": "one row per check-in",
  "file": "events.csv",
  "time": "ts",
  "entity": "name",
  "value": "n"
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `slug` | yes | Lowercase id (`habit`). Not a built-in slug, and not `custom`. |
| `file` | yes | CSV, JSON, or JSONL inside the same folder. No `..`. |
| `time` | yes | Datetime column. Naive values are read in `timezone`. ISO-8601. |
| `label` | no | Tab picker name. Defaults to `slug`. |
| `timezone` | no | IANA name. Default `Europe/Paris`. |
| `entity` | no | Name, place, or other unit for rank / forgotten / comeback. |
| `value` | no | Number summed on the monthly chart. Each row counts as 1 if omitted. |
| `icon` | no | `lucide:…` id stored with the source. The explorer tab icon stays the puzzle piece. |
| `grain` | no | One sentence shown above the charts. |
| `drop` | no | Extra column names to refuse if you mapped them. |

JSON may be a list of objects, or an object with an `events`, `rows`, or `data` list. JSONL is one object per line.

```bash
uv run ingest ~/Documents/data_dumps_raw/inbox/habit
```

**Kept.** One row per parsed timestamp: local and UTC time, year, weekday, hour, optional entity, optional value. Re-ingest of the same slug replaces that slug and leaves the others. Grain is `custom.events` keyed by `source_slug`.

**Dropped.** Every column except time, entity, and value. Email, IP, phone, password, and SSID column names are refused even if you point `time` / `entity` / `value` at them. The copy under `raw/custom/<slug>/` is the cleaned table, not the original file.

**Explorer.** Custom tab. Pick the source, then a year range. Scoreboard (with an equal previous window), monthly counts, entity rank, forgotten entities (silent at least two years), comebacks (a gap of at least two years), streaks, calendar, weekday × hour. Compare has **Custom · events** and a per-source entity series. Correlations has **Custom events**.

## Python plug-in

Create `$DATA_DUMPS_ROOT/user_contributions.py` (next to `raw/` and `warehouse/`, outside git). It must define `CONTRIBUTIONS`, a sequence of `Contribution`. The file is imported by that exact path. Do not add a package of modules for the app to discover — import any helpers yourself from this file.

Do not import Marimo at the top of the file. `uv run ingest` loads it. Import Marimo inside `make_controls` / `render_panel` if you need it.

`detect` runs only after every built-in loader, including the manifest loader, has said no. A slug or Compare id that collides with a built-in is an error.

```python
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
    return mo.ui.checkbox(label="On", value=True)

def render_panel(*, mo, px, conn, bounds, controls, dow_labels):
    return mo.md("## Marker")

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
```

`render_panel` is called from the explorer with those keyword arguments. `make_controls(mo, bounds)` must return the object `render_panel` reads. Do not read `widget.value` in `make_controls`. Same rule as the built-in panels.

Without `make_controls` and `render_panel`, the tab still appears after ingest and tells you the panel is missing. Compare / Correlations series are optional: set `compare_series` and `correlate_metrics` with the factories in `data_dumps.series_catalog` if you want them. Ids must be unique.

Privacy rules are the same as a built-in dump: do not put email, IP, phone, or KYC columns on the tables you create.
