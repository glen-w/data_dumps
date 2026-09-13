"""Orders, digital orders, returns, cart, and order rebuild."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from . import helpers as H
from .meta import AmazonMetaMixin


class OrdersMixin(AmazonMetaMixin):
    def _orders(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "department",
            "dept_family",
            "quantity",
            "currency",
            "unit_price",
            "unit_tax",
            "line_total",
            "shipping_charge",
            "discounts",
            "order_status",
            "is_cancelled",
            "website",
            "marketplace",
            "order_ts_utc",
            "order_ts_local",
            "ship_ts_utc",
            "year",
            "month",
            "surface",
        ]
        raw = bundle.read(
            H.CURATED_ORDER,
            f"Your Amazon Orders/{H.ORDER_HISTORY}",
            H.ORDER_HISTORY,
        )
        if raw is None:
            self._meta(meta, "order_items", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            order_id = H._cell(rec, "Order ID")
            if not order_id:
                continue
            utc, local = H._ts_pair(H._cell(rec, "Order Date"))
            year, month = H._year_month(utc, local)
            ship_utc, _ = H._ts_pair(H._cell(rec, "Ship Date"))
            status = H._cell(rec, "Order Status")
            website = H._cell(rec, "Website")
            dept = H._cell(rec, "Department")
            qty = H._intish(H._cell(rec, "Original Quantity")) or 1
            unit = H._money(H._cell(rec, "Unit Price"))
            tax = H._money(H._cell(rec, "Unit Price Tax"))
            total = H._money(H._cell(rec, "Total Amount"))
            if total is None and unit is not None:
                total = unit * qty + (tax or 0) * qty
            rows.append(
                {
                    "order_id": order_id,
                    "asin": H._cell(rec, "ASIN"),
                    "product_name": H._cell(rec, "Product Name"),
                    "department": dept,
                    "dept_family": H._dept_family(dept),
                    "quantity": qty,
                    "currency": H._cell(rec, "Currency"),
                    "unit_price": unit,
                    "unit_tax": tax,
                    "line_total": total,
                    "shipping_charge": H._money(H._cell(rec, "Shipping Charge")),
                    "discounts": H._money(H._cell(rec, "Total Discounts")),
                    "order_status": status,
                    "is_cancelled": (status or "").casefold() == "cancelled",
                    "website": website,
                    "marketplace": H._marketplace_from_website(website),
                    "order_ts_utc": utc,
                    "order_ts_local": local,
                    "ship_ts_utc": ship_utc,
                    "year": year,
                    "month": month,
                    "surface": "retail",
                }
            )
        self._meta(meta, "order_items", H.ORDER_HISTORY, len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _digital(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "marketplace",
            "currency",
            "price",
            "quantity",
            "order_status",
            "order_ts_utc",
            "order_ts_local",
            "year",
            "month",
            "is_gift",
            "surface",
        ]
        raw = bundle.read(
            "Your Amazon Orders/Digital Content Orders.csv",
            "Digital Content Orders.csv",
        )
        if raw is None:
            self._meta(meta, "digital_items", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Order Date"))
            year, month = H._year_month(utc, local)
            mkt = H._cell(rec, "Marketplace")
            rows.append(
                {
                    "order_id": H._cell(rec, "Order ID"),
                    "asin": H._cell(rec, "ASIN"),
                    "product_name": H._cell(rec, "Product Name"),
                    "marketplace": H._marketplace_from_website(mkt) or (mkt or None),
                    "currency": H._cell(
                        rec, "Price Currency Code", "Base Currency Code"
                    ),
                    "price": H._money(H._cell(rec, "Price", "Transaction Amount")),
                    "quantity": H._intish(
                        H._cell(rec, "Quantity Ordered", "Original Quantity")
                    )
                    or 1,
                    "order_status": H._cell(rec, "Order Status"),
                    "order_ts_utc": utc,
                    "order_ts_local": local,
                    "year": year,
                    "month": month,
                    "is_gift": (H._cell(rec, "Gift Item") or "").casefold() == "yes",
                    "surface": "digital",
                }
            )
        self._meta(
            meta, "digital_items", "Digital Content Orders.csv", len(records), len(rows)
        )
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _returns(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "order_id",
            "asin",
            "product_name",
            "return_reason",
            "refund_amount",
            "currency",
            "status",
            "return_ts_utc",
            "return_ts_local",
            "year",
            "month",
            "source_kind",
        ]
        rows: list[dict[str, Any]] = []
        raw_n = 0
        for kind, candidates, mapping in (
            (
                "refund_details",
                ("Your Returns & Refunds/Refund Details.csv", "Refund Details.csv"),
                {
                    "order_id": ("Order ID",),
                    "refund_amount": ("Refund Amount",),
                    "currency": ("Currency",),
                    "status": ("Reversal Status", "Payment Status"),
                    "reason": ("Reversal Reason",),
                    "ts": ("Refund Date", "Creation Date"),
                },
            ),
            (
                "return_requests",
                ("Your Returns & Refunds/Return Requests.csv", "Return Requests.csv"),
                {
                    "order_id": ("Order ID",),
                    "asin": ("ASIN",),
                    "product_name": ("Product Name",),
                    "reason": ("Return Reason Code",),
                },
            ),
            (
                "returns_status",
                ("Your Returns & Refunds/Returns Status.csv", "Returns Status.csv"),
                {
                    "order_id": ("Order ID",),
                    "refund_amount": ("Return Amount",),
                    "currency": ("Return Amount Currency",),
                    "reason": ("Return Reason",),
                    "status": ("Return Resolution", "Return Receivable State"),
                    "ts": ("Date of Return", "Return Creation Date"),
                },
            ),
        ):
            raw = bundle.read(*candidates)
            if raw is None:
                continue
            records = H._read_csv_dicts(raw)
            raw_n += len(records)
            for rec in records:
                utc, local = H._ts_pair(H._cell(rec, *mapping.get("ts", ())))
                year, month = H._year_month(utc, local)
                rows.append(
                    {
                        "order_id": H._cell(
                            rec, *mapping.get("order_id", ("Order ID",))
                        ),
                        "asin": H._cell(rec, *mapping.get("asin", ("ASIN",))),
                        "product_name": H._cell(
                            rec, *mapping.get("product_name", ("Product Name",))
                        ),
                        "return_reason": H._cell(rec, *mapping.get("reason", ("",))),
                        "refund_amount": H._money(
                            H._cell(rec, *mapping.get("refund_amount", ("",)))
                        ),
                        "currency": H._cell(rec, *mapping.get("currency", ("",))),
                        "status": H._cell(rec, *mapping.get("status", ("",))),
                        "return_ts_utc": utc,
                        "return_ts_local": local,
                        "year": year,
                        "month": month,
                        "source_kind": kind,
                    }
                )
        self._meta(meta, "returns", "returns/*", raw_n, len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _cart(self, bundle: Any, meta: list[dict[str, Any]]) -> pd.DataFrame:
        cols = [
            "asin",
            "product_name",
            "quantity",
            "cart_source",
            "added_ts_utc",
            "added_ts_local",
            "year",
            "month",
        ]
        raw = bundle.read("Your Amazon Orders/Cart History.csv", "Cart History.csv")
        if raw is None:
            self._meta(meta, "cart_events", None, 0, 0, "missing")
            return H._empty(cols)
        records = H._read_csv_dicts(raw)
        rows: list[dict[str, Any]] = []
        for rec in records:
            utc, local = H._ts_pair(H._cell(rec, "Date Added to Cart", "Add Date"))
            year, month = H._year_month(utc, local)
            rows.append(
                {
                    "asin": H._cell(rec, "ASIN"),
                    "product_name": H._cell(rec, "Product Name"),
                    "quantity": H._intish(
                        H._cell(rec, "Order Quantity", "Cart Amount")
                    ),
                    "cart_source": H._cell(rec, "Cart Source", "Status"),
                    "added_ts_utc": utc,
                    "added_ts_local": local,
                    "year": year,
                    "month": month,
                }
            )
        self._meta(meta, "cart_events", "Cart History.csv", len(records), len(rows))
        return pd.DataFrame(rows, columns=cols) if rows else H._empty(cols)

    def _rebuild_orders(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("DELETE FROM amazon.orders")
        conn.execute("""
            INSERT INTO amazon.orders
            SELECT
                order_id,
                min(order_ts_utc) AS order_ts_utc,
                min(order_ts_local) AS order_ts_local,
                min(year) AS year,
                min(month) AS month,
                any_value(marketplace) AS marketplace,
                any_value(website) AS website,
                any_value(currency) AS currency,
                count(*)::BIGINT AS n_items,
                sum(CASE WHEN NOT is_cancelled THEN coalesce(line_total, 0) ELSE 0 END)
                    AS total_amount,
                bool_or(is_cancelled) AS is_cancelled,
                any_value(order_status) AS status
            FROM amazon.order_items
            GROUP BY order_id
            """)
