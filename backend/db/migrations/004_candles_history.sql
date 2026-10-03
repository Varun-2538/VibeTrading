-- Candle history for backtests.
--
-- Separate from ohlc_data, which the live scheduler trims to 30 days. This
-- table holds the depth a backtest needs (5m 6 months, 15m 1 year, 1h 3 years,
-- 1d all) and only closed bars. Applied idempotently at startup by
-- Database.bootstrap_schema().
CREATE TABLE IF NOT EXISTS candles_history (
    symbol     TEXT             NOT NULL,
    timeframe  TEXT             NOT NULL,
    time       TIMESTAMPTZ      NOT NULL,
    open       DOUBLE PRECISION NOT NULL,
    high       DOUBLE PRECISION NOT NULL,
    low        DOUBLE PRECISION NOT NULL,
    close      DOUBLE PRECISION NOT NULL,
    volume     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, timeframe, time)
);

SELECT create_hypertable(
    'candles_history', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);
