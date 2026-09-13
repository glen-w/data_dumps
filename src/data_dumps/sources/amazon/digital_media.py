"""Video, Audible, Music, and Kindle frame builders."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import helpers as H
from .meta import AmazonMetaMixin


class DigitalMediaMixin(AmazonMetaMixin):
    def _video_views(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "title",
            "seconds_viewed",
            "device_model",
            "content_quality",
            "country_code",
            "start_ts_utc",
            "start_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Prime Video Viewing Activity/Viewing History.csv",
            "Viewing History.csv",
        )
        if raw is None:
            self._meta(meta, "video_views", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Playback Start Datetime (UTC)"))
            year, month = H._year_month(utc, local)
            title = H._cell(rec, "Title")
            if title:
                title = title.strip('"')
            rows.append(
                {
                    "title": title,
                    "seconds_viewed": H._intish(H._cell(rec, "Seconds Viewed")),
                    "device_model": (H._cell(rec, "Device Model") or "").strip('"')
                    or None,
                    "content_quality": (
                        H._cell(rec, "Content Quality Delivered") or ""
                    ).strip('"')
                    or None,
                    "country_code": (H._cell(rec, "Country Code") or "").strip('"')
                    or None,
                    "start_ts_utc": utc,
                    "start_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "video_views", "Viewing History.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _video_searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "query",
            "device_name",
            "search_ts_utc",
            "search_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Prime Video Viewing Activity/Search History.csv",
            "Search History.csv",
        )
        # Ambiguous basename — prefer Prime Video path via find order above
        if raw is None:
            self._meta(meta, "video_searches", None, 0, 0, "missing")
            return H._empty(cols)
        # If we accidentally got Music search (2 cols), skip incompatible
        records = H._read_csv_dicts(raw)
        if records and "Search Query from Customer" not in records[0]:
            # Music search history — leave for music_searches
            self._meta(meta, "video_searches", None, 0, 0, "wrong_file")
            return H._empty(cols)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Search Request Date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "query": H._cell(rec, "Search Query from Customer"),
                    "device_name": H._cell(rec, "Device Name"),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "video_searches", "PV Search History", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _audible_listens(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "duration_ms",
            "narration_speed",
            "start_ts_utc",
            "start_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Audible Library & Listening/Listening History.csv",
        )
        if raw is None:
            self._meta(meta, "audible_listens", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Start Date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "asin": H._cell(rec, "ASIN"),
                    "product_name": H._cell(rec, "Product Name"),
                    "duration_ms": H._intish(
                        H._cell(rec, "Event Duration Milliseconds")
                    ),
                    "narration_speed": H._money(H._cell(rec, "Narration Speed")),
                    "start_ts_utc": utc,
                    "start_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(
            meta,
            "audible_listens",
            "Audible Listening History",
            len(records),
            len(rows),
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _audible_library(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["asin", "title", "authors", "length_minutes", "purchase_ts_utc", "year"]
        raw = bundle.read("Your Audible Library & Listening/Library.csv", "Library.csv")
        if raw is None:
            self._meta(meta, "audible_library", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = H._ts_pair(H._cell(rec, "Purchase Date", "Last Updated"))
            rows.append(
                {
                    "asin": H._cell(rec, "ASIN"),
                    "title": H._cell(rec, "Title", "Product Name"),
                    "authors": H._cell(rec, "Authors"),
                    "length_minutes": H._intish(H._cell(rec, "Length in Minutes")),
                    "purchase_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "audible_library", "Library.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _music_plays(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "device_type",
            "listen_ms",
            "track_ms",
            "play_ts_utc",
            "play_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read("Your Listening Activity/Listening History.csv")
        if raw is None:
            self._meta(meta, "music_plays", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "asin": H._cell(rec, "ASIN"),
                    "product_name": H._cell(rec, "Product Name"),
                    "device_type": H._cell(rec, "Device Type"),
                    "listen_ms": H._intish(
                        H._cell(rec, "Listen Duration in Milliseconds")
                    ),
                    "track_ms": H._intish(H._cell(rec, "Track Length in Milliseconds")),
                    "play_ts_utc": utc,
                    "play_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(
            meta, "music_plays", "Music Listening History", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _music_searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["query", "search_ts_utc", "search_ts_local", "year", "month"]
        raw = bundle.read("Your Listening Activity/Search History.csv")
        if raw is None:
            self._meta(meta, "music_searches", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Event Date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "query": H._cell(rec, "Query"),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(
            meta, "music_searches", "Music Search History", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _music_library(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "title",
            "artist_name",
            "album_name",
            "primary_genre",
            "saved_ts_utc",
            "year",
        ]
        raw = bundle.read("Your Music Library/Saved Music.csv", "Saved Music.csv")
        if raw is None:
            self._meta(meta, "music_library", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, _ = H._ts_pair(H._cell(rec, "Creation Date", "Last Updated Date"))
            rows.append(
                {
                    "asin": H._cell(rec, "ASIN"),
                    "title": H._cell(rec, "Title"),
                    "artist_name": H._cell(rec, "Artist Name"),
                    "album_name": H._cell(rec, "Album Name"),
                    "primary_genre": H._cell(
                        rec, "Primary Genre", "Album Primary Genre"
                    ),
                    "saved_ts_utc": utc,
                    "year": utc.year if utc else None,
                }
            )
        self._meta(meta, "music_library", "Saved Music.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _kindle_sessions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "content_id",
            "duration_ms",
            "session_ts_utc",
            "session_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/Kindle.Devices.ReadingSession/Kindle.Devices.ReadingSession.csv",
            "Kindle.Devices.ReadingSession.csv",
        )
        if raw is None:
            self._meta(meta, "kindle_sessions", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(
                H._cell(
                    rec,
                    "start_timestamp",
                    "startDate",
                    "Start Date",
                    "sessionStart",
                    "timestamp",
                    "Date",
                )
            )
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "content_id": H._cell(
                        rec, "ASIN", "asin", "contentid", "contentId"
                    ),
                    "duration_ms": H._intish(
                        H._cell(
                            rec,
                            "total_reading_millis",
                            "totalReadingMillis",
                            "Total Reading Millis",
                            "duration",
                        )
                    ),
                    "session_ts_utc": utc,
                    "session_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "kindle_sessions", "ReadingSession", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)
