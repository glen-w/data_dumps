"""Alexa intents, sessions, show engagement, skills, routines, app events."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from . import helpers as H
from .meta import AmazonMetaMixin


class AlexaMixin(AmazonMetaMixin):
    def _alexa_intents(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "utterance",
            "utterance_tag",
            "playing_song",
            "intent_ts_utc",
            "intent_ts_local",
            "year",
            "month",
            "hour",
            "dow",
        ]
        opened = bundle.open_member(
            "Additional Data/Alexa/Alexa/NLU/Intent-2-1.csv",
            "Intent-2-1.csv",
        )
        if opened is None:
            self._meta(meta, "alexa_intents", None, 0, 0, "missing")
            return H._empty(cols)
        fh, info = opened
        rows: list[dict[str, Any]] = []
        raw_n = 0
        with fh:
            for rec in H._iter_csv_dicts(fh):
                raw_n += 1
                utterance = H._cell(rec, "Utterance text")
                utc, local = H._ts_pair(H._cell(rec, "Utterance Creation Date"))
                year, month = H._year_month(utc, local)
                src = local or utc
                rows.append(
                    {
                        "utterance": utterance,
                        "utterance_tag": H._utterance_tag(utterance),
                        "playing_song": H._cell(rec, "Currently Playing Song"),
                        "intent_ts_utc": utc,
                        "intent_ts_local": local,
                        "year": year,
                        "month": month,
                        "hour": src.hour if src else None,
                        "dow": src.isoweekday() if src else None,
                    }
                )
        self._meta(meta, "alexa_intents", info.filename, raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _alexa_sessions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "device_type",
            "device_app",
            "locale",
            "marketplace",
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Alexa and Echo Devices.Device_Session_Events/"
            "Alexa and Echo Devices.Device_Session_Events.csv",
            "Alexa and Echo Devices.Device_Session_Events.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_sessions", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(
                H._cell(rec, "Event Creation Date", "Event Recording Date")
            )
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "device_type": H._cell(rec, "Device Type"),
                    "device_app": H._cell(rec, "Device Application"),
                    "locale": H._cell(rec, "Device Locale"),
                    "marketplace": H._cell(rec, "Marketplace"),
                    "event_ts_utc": utc,
                    "event_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(
            meta, "alexa_sessions", "Device_Session_Events", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _alexa_show_daily(
        self, bundle: Any, meta: list[dict[str, Any]]
    ) -> pd.DataFrame:
        cols = [
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
            "voice_count",
            "touch_count",
            "impression_count",
        ]
        opened = bundle.open_member(
            "Additional Data/Alexa and Echo Devices.Echo_Show_Generic_Events/"
            "Alexa and Echo Devices.Echo_Show_Generic_Events.csv",
            "Alexa and Echo Devices.Echo_Show_Generic_Events.csv",
        )
        if opened is None:
            self._meta(meta, "alexa_show_daily", None, 0, 0, "missing")
            return H._empty(cols)
        fh, info = opened
        rows: list[dict[str, Any]] = []
        raw_n = 0
        with fh:
            for rec in H._iter_csv_dicts(fh):
                raw_n += 1
                utc, local = H._ts_pair(H._cell(rec, "Event Creation Date"))
                year, month = H._year_month(utc, local)
                rows.append(
                    {
                        "event_ts_utc": utc,
                        "event_ts_local": local,
                        "year": year,
                        "month": month,
                        "voice_count": H._intish(H._cell(rec, "Voice Engagement Count"))
                        or 0,
                        "touch_count": H._intish(H._cell(rec, "Touch Engagement Count"))
                        or 0,
                        "impression_count": H._intish(H._cell(rec, "Impression Count"))
                        or 0,
                    }
                )
        self._meta(meta, "alexa_show_daily", info.filename, raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _alexa_skills(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["skill_name", "stage", "status", "enabled_ts_utc", "year"]
        raw = bundle.read(
            "Additional Data/Alexa/Skills/Skills-2.csv",
            "Skills-2.csv",
            "Skills.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_skills", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = H._ts_pair(H._cell(rec, "Enablement Date"))
            rows.append(
                {
                    "skill_name": H._cell(rec, "SkillName", "Skill Name"),
                    "stage": H._cell(rec, "SkillStage"),
                    "status": H._cell(rec, "EnablementStatus"),
                    "enabled_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "alexa_skills", "Skills", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _alexa_routines(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["routine_name", "status", "payload_preview"]
        raw = bundle.read(
            "Additional Data/Alexa/Routines/Routines-4.json",
            "Additional Data/Alexa/Routines/Routines-2.json",
            "Routines.json",
        )
        if raw is None:
            self._meta(meta, "alexa_routines", None, 0, 0, "missing")
            return H._empty(cols)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._meta(meta, "alexa_routines", "Routines.json", 0, 0, "bad_json")
            return H._empty(cols)
        items = (
            data
            if isinstance(data, list)
            else data.get("routines") or data.get("Automations") or [data]
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("friendlyName")
                or item.get("name")
                or item.get("routineName")
                or item.get("Name")
            )
            status = item.get("status") or item.get("Status")
            preview = json.dumps(item)[:500]
            rows.append(
                {
                    "routine_name": str(name) if name else None,
                    "status": str(status) if status else None,
                    "payload_preview": preview,
                }
            )
        self._meta(meta, "alexa_routines", "Routines.json", len(items), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _alexa_app_events(
        self, bundle: Any, meta: list[dict[str, Any]]
    ) -> pd.DataFrame:
        cols = [
            "event_name",
            "platform",
            "device_make",
            "device_model",
            "event_ts_utc",
            "event_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Alexa/Devices/Mobile/CustomerInteraction_000-1.csv",
            "CustomerInteraction_000-1.csv",
        )
        if raw is None:
            self._meta(meta, "alexa_app_events", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "interaction_date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "event_name": H._cell(rec, "event_name"),
                    "platform": H._cell(rec, "device_platform_name"),
                    "device_make": H._cell(rec, "device_make"),
                    "device_model": H._cell(rec, "device_model"),
                    "event_ts_utc": utc,
                    "event_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(
            meta, "alexa_app_events", "CustomerInteraction", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)
