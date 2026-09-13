"""DuckDB DDL for amazon.* tables."""

from __future__ import annotations

import duckdb


def create_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE amazon.dump_inventory (
            zip_part VARCHAR,
            path VARCHAR,
            ext VARCHAR,
            category VARCHAR,
            bytes BIGINT,
            ingested BOOLEAN,
            skip_reason VARCHAR
        );
        CREATE TABLE amazon.ingest_meta (
            logical_name VARCHAR,
            source_path VARCHAR,
            rows_raw BIGINT,
            rows_kept BIGINT,
            note VARCHAR
        );
        CREATE TABLE amazon.order_items (
            order_id VARCHAR,
            asin VARCHAR,
            product_name VARCHAR,
            department VARCHAR,
            dept_family VARCHAR,
            quantity BIGINT,
            currency VARCHAR,
            unit_price DOUBLE,
            unit_tax DOUBLE,
            line_total DOUBLE,
            shipping_charge DOUBLE,
            discounts DOUBLE,
            order_status VARCHAR,
            is_cancelled BOOLEAN,
            website VARCHAR,
            marketplace VARCHAR,
            order_ts_utc TIMESTAMP,
            order_ts_local TIMESTAMP,
            ship_ts_utc TIMESTAMP,
            year BIGINT,
            month BIGINT,
            surface VARCHAR
        );
        CREATE TABLE amazon.orders (
            order_id VARCHAR,
            order_ts_utc TIMESTAMP,
            order_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT,
            marketplace VARCHAR,
            website VARCHAR,
            currency VARCHAR,
            n_items BIGINT,
            total_amount DOUBLE,
            is_cancelled BOOLEAN,
            status VARCHAR
        );
        CREATE TABLE amazon.digital_items (
            order_id VARCHAR,
            asin VARCHAR,
            product_name VARCHAR,
            marketplace VARCHAR,
            currency VARCHAR,
            price DOUBLE,
            quantity BIGINT,
            order_status VARCHAR,
            order_ts_utc TIMESTAMP,
            order_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT,
            is_gift BOOLEAN,
            surface VARCHAR
        );
        CREATE TABLE amazon.returns (
            order_id VARCHAR,
            asin VARCHAR,
            product_name VARCHAR,
            return_reason VARCHAR,
            refund_amount DOUBLE,
            currency VARCHAR,
            status VARCHAR,
            return_ts_utc TIMESTAMP,
            return_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT,
            source_kind VARCHAR
        );
        CREATE TABLE amazon.cart_events (
            asin VARCHAR,
            product_name VARCHAR,
            quantity BIGINT,
            cart_source VARCHAR,
            added_ts_utc TIMESTAMP,
            added_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.searches (
            query_id VARCHAR,
            keywords VARCHAR,
            department VARCHAR,
            marketplace VARCHAR,
            device_category VARCHAR,
            clicked BOOLEAN,
            added BOOLEAN,
            purchased BOOLEAN,
            abandoned BOOLEAN,
            reformulated BOOLEAN,
            n_clicked BIGINT,
            n_ordered BIGINT,
            search_ts_utc TIMESTAMP,
            search_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.search_clicks (
            clicked_asin VARCHAR,
            added_asin VARCHAR,
            borrowed_asin VARCHAR
        );
        CREATE TABLE amazon.video_views (
            title VARCHAR,
            seconds_viewed BIGINT,
            device_model VARCHAR,
            content_quality VARCHAR,
            country_code VARCHAR,
            start_ts_utc TIMESTAMP,
            start_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.video_searches (
            query VARCHAR,
            device_name VARCHAR,
            search_ts_utc TIMESTAMP,
            search_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.audible_listens (
            asin VARCHAR,
            product_name VARCHAR,
            duration_ms BIGINT,
            narration_speed DOUBLE,
            start_ts_utc TIMESTAMP,
            start_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.audible_library (
            asin VARCHAR,
            title VARCHAR,
            authors VARCHAR,
            length_minutes BIGINT,
            purchase_ts_utc TIMESTAMP,
            year BIGINT
        );
        CREATE TABLE amazon.music_plays (
            asin VARCHAR,
            product_name VARCHAR,
            device_type VARCHAR,
            listen_ms BIGINT,
            track_ms BIGINT,
            play_ts_utc TIMESTAMP,
            play_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.music_searches (
            query VARCHAR,
            search_ts_utc TIMESTAMP,
            search_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.music_library (
            asin VARCHAR,
            title VARCHAR,
            artist_name VARCHAR,
            album_name VARCHAR,
            primary_genre VARCHAR,
            saved_ts_utc TIMESTAMP,
            year BIGINT
        );
        CREATE TABLE amazon.alexa_intents (
            utterance VARCHAR,
            utterance_tag VARCHAR,
            playing_song VARCHAR,
            intent_ts_utc TIMESTAMP,
            intent_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT,
            hour BIGINT,
            dow BIGINT
        );
        CREATE TABLE amazon.alexa_sessions (
            device_type VARCHAR,
            device_app VARCHAR,
            locale VARCHAR,
            marketplace VARCHAR,
            event_ts_utc TIMESTAMP,
            event_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.alexa_show_daily (
            event_ts_utc TIMESTAMP,
            event_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT,
            voice_count BIGINT,
            touch_count BIGINT,
            impression_count BIGINT
        );
        CREATE TABLE amazon.alexa_skills (
            skill_name VARCHAR,
            stage VARCHAR,
            status VARCHAR,
            enabled_ts_utc TIMESTAMP,
            year BIGINT
        );
        CREATE TABLE amazon.alexa_routines (
            routine_name VARCHAR,
            status VARCHAR,
            payload_preview VARCHAR
        );
        CREATE TABLE amazon.alexa_app_events (
            event_name VARCHAR,
            platform VARCHAR,
            device_make VARCHAR,
            device_model VARCHAR,
            event_ts_utc TIMESTAMP,
            event_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.kindle_sessions (
            content_id VARCHAR,
            duration_ms BIGINT,
            session_ts_utc TIMESTAMP,
            session_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.wishlists (
            list_name VARCHAR,
            asin VARCHAR,
            title VARCHAR,
            raw_json VARCHAR
        );
        CREATE TABLE amazon.rufus_queries (
            query VARCHAR,
            asin VARCHAR,
            product_name VARCHAR,
            query_ts_utc TIMESTAMP,
            query_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.subscriptions (
            subscription_id VARCHAR,
            status VARCHAR,
            start_ts_utc TIMESTAMP,
            end_ts_utc TIMESTAMP,
            year BIGINT
        );
        CREATE TABLE amazon.product_impressions (
            kind VARCHAR,
            asin VARCHAR,
            product_name VARCHAR,
            marketplace VARCHAR,
            country_code VARCHAR,
            device_type VARCHAR,
            currency VARCHAR,
            list_price DOUBLE,
            seen_ts_utc TIMESTAMP,
            seen_ts_local TIMESTAMP,
            year BIGINT,
            month BIGINT
        );
        CREATE TABLE amazon.devices_summary (
            surface VARCHAR,
            device_model VARCHAR,
            amazon_model_name VARCHAR,
            state VARCHAR,
            customer_type VARCHAR,
            serial_hash VARCHAR,
            first_registered_utc TIMESTAMP,
            last_registered_utc TIMESTAMP,
            year BIGINT
        );
        """)
