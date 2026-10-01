-- TradeSmart.AI database schema
-- Mounted by docker-compose.yml at /docker-entrypoint-initdb.d/init.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- OHLC candlestick data, range-partitioned by month on `time`.
-- Monthly partitions are created by backend/create_partitions.py.
CREATE TABLE IF NOT EXISTS ohlc_data (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    timeframe   TEXT             NOT NULL,
    open        NUMERIC(20, 8)   NOT NULL,
    high        NUMERIC(20, 8)   NOT NULL,
    low         NUMERIC(20, 8)   NOT NULL,
    close       NUMERIC(20, 8)   NOT NULL,
    volume      NUMERIC(30, 8)   NOT NULL,
    PRIMARY KEY (time, symbol, timeframe)
) PARTITION BY RANGE (time);

CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_timeframe_time
    ON ohlc_data (symbol, timeframe, time DESC);

-- Chart annotations. `annotation_data` holds a JSON document that the
-- application serializes/deserializes itself, so it is stored as TEXT.
CREATE TABLE IF NOT EXISTS annotations (
    id              BIGSERIAL    PRIMARY KEY,
    symbol          TEXT         NOT NULL,
    annotation_data TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_annotations_symbol_created
    ON annotations (symbol, created_at DESC);
