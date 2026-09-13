"""Retail searches, clicks, wishlists, Rufus, subscriptions, impressions, devices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import helpers as H
from .meta import AmazonMetaMixin


class SearchesMixin(AmazonMetaMixin):
    def _searches(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "query_id",
            "keywords",
            "department",
            "marketplace",
            "device_category",
            "clicked",
            "added",
            "purchased",
            "abandoned",
            "reformulated",
            "n_clicked",
            "n_ordered",
            "search_ts_utc",
            "search_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Your Shopping Search/Search Queries.csv", "Search Queries.csv"
        )
        if raw is None:
            self._meta(meta, "searches", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(
                H._cell(rec, "First Search Time (GMT)", "Last search Time (GMT)")
            )
            year, month = H._year_month(utc, local)
            country = H._cell(rec, "Country Code")
            rows.append(
                {
                    "query_id": H._cell(rec, "Query ID"),
                    "keywords": H._cell(rec, "Keywords", "First Search Query String"),
                    "department": H._cell(
                        rec, "Department", "All Department (APS) or Category"
                    ),
                    "marketplace": (country or "").casefold() or None,
                    "device_category": H._cell(
                        rec, "Device Category", "Application / Browser Name"
                    ),
                    "clicked": (H._cell(rec, "Clicked Any Item (Y/N)") or "").upper()
                    == "Y",
                    "added": (H._cell(rec, "Added Any Item (Y/N)") or "").upper()
                    == "Y",
                    "purchased": (
                        H._cell(rec, "Purchased Any Item (Y/N)") or ""
                    ).upper()
                    == "Y",
                    "abandoned": (H._cell(rec, "Query Abandoned (Y/N)") or "").upper()
                    == "Y",
                    "reformulated": (
                        H._cell(rec, "Query Reformulated (Y/N)") or ""
                    ).upper()
                    == "Y",
                    "n_clicked": H._intish(H._cell(rec, "Number of Clicked Items")),
                    "n_ordered": H._intish(H._cell(rec, "Number of Items Ordered")),
                    "search_ts_utc": utc,
                    "search_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "searches", "Search Queries.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _search_clicks(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["clicked_asin", "added_asin", "borrowed_asin"]
        raw = bundle.read(
            "Your Shopping Search/Search Product Clicks.csv",
            "Search Product Clicks.csv",
        )
        if raw is None:
            self._meta(meta, "search_clicks", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows = [
            {
                "clicked_asin": H._cell(rec, "Clicked Items"),
                "added_asin": H._cell(rec, "Items Added to Cart or List"),
                "borrowed_asin": H._cell(rec, "Items Borrowed"),
            }
            for rec in records
        ]
        self._meta(
            meta, "search_clicks", "Search Product Clicks.csv", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _wishlists(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = ["list_name", "asin", "title", "raw_json"]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for cand in (
            "Additional Data/Amazon.Lists.Wishlist.2.2/Amazon.Lists.Wishlist.json",
            "Additional Data/Amazon.Lists.Wishlist.2.1/Amazon.Lists.Wishlist.json",
            "Additional Data/Amazon.Lists.Wishlist.1.1/Amazon.Lists.Wishlist.json",
            "Amazon.Lists.Wishlist.json",
        ):
            raw = bundle.read(cand)
            if raw is None:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            raw_n += 1
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "list_name": str(
                            item.get("listName")
                            or item.get("name")
                            or item.get("title")
                            or Path(cand).parent.name
                        ),
                        "asin": item.get("asin") or item.get("ASIN"),
                        "title": item.get("title") or item.get("productName"),
                        "raw_json": json.dumps(item)[:1000],
                    }
                )
        self._meta(meta, "wishlists", "Wishlist.json", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _rufus(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "query",
            "asin",
            "product_name",
            "query_ts_utc",
            "query_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read(
            "Additional Data/SearchHistory.RufusConversations/Rufus.Conversation.Queries.csv",
            "Rufus.Conversation.Queries.csv",
        )
        if raw is None:
            self._meta(meta, "rufus_queries", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            q = H._cell(
                rec,
                "Typed Query",
                "Autocompleted Query",
                "Query",
                "query",
                "Question",
                "Utterance",
                "Customer Query",
            )
            # Fall back to product context when typed query blank
            if q is None:
                q = H._cell(rec, "Product Name")
            utc, local = H._ts_pair(
                H._cell(
                    rec,
                    "Request Date",
                    "Timestamp",
                    "Event Date",
                    "Date",
                    "Creation Date",
                    "Query Date",
                )
            )
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "query": q,
                    "asin": H._cell(rec, "ASIN", "asin"),
                    "product_name": H._cell(rec, "Product Name"),
                    "query_ts_utc": utc,
                    "query_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "rufus_queries", "Rufus Queries", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _subscriptions(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "subscription_id",
            "status",
            "start_ts_utc",
            "end_ts_utc",
            "year",
        ]
        raw = bundle.read(
            "Additional Data/Digital.Subscriptions.2/Subscriptions.csv",
            "Subscriptions.csv",
        )
        if raw is None:
            self._meta(meta, "subscriptions", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            start, _ = H._ts_pair(
                H._cell(
                    rec, "Subscription Start Date", "Contract Start Date", "Start Date"
                )
            )
            end, _ = H._ts_pair(
                H._cell(rec, "Subscription End Date", "Contract End Date", "End Date")
            )
            rows.append(
                {
                    "subscription_id": H._cell(
                        rec, "Subscription ID", "SubscriptionId", "subscriptionId"
                    ),
                    "status": H._cell(rec, "Status", "Subscription Status"),
                    "start_ts_utc": start,
                    "end_ts_utc": end,
                    "year": start.year if start else None,
                }
            )
        self._meta(meta, "subscriptions", "Subscriptions.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _product_impressions(
        self, bundle: Any, meta: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Detail-page / buy-again impressions — no city/postal/UA/referer."""
        cols = [
            "kind",
            "asin",
            "product_name",
            "marketplace",
            "country_code",
            "device_type",
            "currency",
            "list_price",
            "seen_ts_utc",
            "seen_ts_local",
            "year",
            "month",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        sources = (
            (
                "detail_page",
                (
                    "Additional Data/Request All Your Data.Detail Page Glance View Impressions/"
                    "Request All Your Data.Detail Page Glance View Impressions.csv",
                    "Request All Your Data.Detail Page Glance View Impressions.csv",
                ),
            ),
            (
                "buy_again",
                (
                    "Additional Data/Request All Your Data.Buy Again Customer Shopping Impressions/"
                    "Request All Your Data.Buy Again Customer Shopping Impressions.csv",
                    "Request All Your Data.Buy Again Customer Shopping Impressions.csv",
                ),
            ),
        )
        for kind, candidates in sources:
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = H._read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                utc, local = H._ts_pair(H._cell(rec, "creation_date", "Creation Date"))
                year, month = H._year_month(utc, local)
                mkt = H._cell(rec, "marketplace_id", "Marketplace")
                rows.append(
                    {
                        "kind": kind,
                        "asin": H._cell(rec, "ASIN", "asin"),
                        "product_name": H._cell(rec, "product_name", "Product Name"),
                        "marketplace": H._marketplace_from_website(mkt) or mkt,
                        "country_code": H._cell(
                            rec, "customer_country_code", "country_code", "Country Code"
                        ),
                        "device_type": H._cell(rec, "device_type", "Device Type"),
                        "currency": H._cell(
                            rec,
                            "website_list_price_currency_code",
                            "list_price_currency_code",
                        ),
                        "list_price": H._money(
                            H._cell(
                                rec,
                                "website_list_price",
                                "list_price_amount",
                                "merchant_asin_price",
                            )
                        ),
                        "seen_ts_utc": utc,
                        "seen_ts_local": local,
                        "year": year,
                        "month": month,
                    }
                )
        self._meta(meta, "product_impressions", "impressions/*", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _devices_summary(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        """Fire device registration — no serial plaintext, no IP."""
        cols = [
            "surface",
            "device_model",
            "amazon_model_name",
            "state",
            "customer_type",
            "serial_hash",
            "first_registered_utc",
            "last_registered_utc",
            "year",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for surface, candidates in (
            (
                "fire_tv",
                ("Your Fire TV Device & Setup/Device Registration.csv",),
            ),
            (
                "fire_tablet",
                ("Your Fire Tablet Device & Setup/Device Registration.csv",),
            ),
        ):
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = H._read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                first, _ = H._ts_pair(H._cell(rec, "First Time Registered"))
                last, _ = H._ts_pair(H._cell(rec, "Last Time Registered"))
                serial = H._cell(rec, "Device Serial Number")
                rows.append(
                    {
                        "surface": surface,
                        "device_model": H._cell(rec, "Device Model"),
                        "amazon_model_name": H._cell(rec, "Amazon Device Model Name"),
                        "state": H._cell(rec, "State"),
                        "customer_type": H._cell(rec, "Customer Type"),
                        "serial_hash": H._hash_id(serial),
                        "first_registered_utc": first,
                        "last_registered_utc": last,
                        "year": first.year if first else None,
                    }
                )
        if rows:
            df = pd.DataFrame(rows, columns=cols)
            df = df.drop_duplicates(
                subset=["surface", "serial_hash", "first_registered_utc"],
                keep="first",
            )
            self._meta(meta, "devices_summary", "Device Registration", raw_n, len(df))
            return df
        self._meta(meta, "devices_summary", None, 0, 0, "missing")
        return H._empty(cols)
