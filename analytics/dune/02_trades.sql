-- Every position opened and closed inside a VibeTrading vault on Robinhood Chain,
-- and who closed it. The exit is the point: stops, targets and deadlines are
-- written into the vault and anyone may push them, so this shows whether exits
-- came from our executor or from a stranger collecting the bounty.
--
--   Opened(uint256 spent, uint256 qty, uint256 entryPrice, uint256 stopPrice,
--          uint256 targetPrice, uint64 deadline)
--   Closed(string reason, uint256 qty, uint256 received, uint256 price,
--          address closedBy, uint256 bountyPaid)
-- Stable is USDG (6 decimals); Chainlink prices are 8 decimals.
WITH vaults AS (
    SELECT bytearray_substring(data, 13, 20) AS vault
    FROM robinhood.logs
    WHERE contract_address = 0x04c96936670c38982d1e7ef23cadd84d6891c818
      AND topic0 = 0x2c2642e51c5da7f061023663faf2699e94a26a02c688fc21790dcdec49fade6b
),
opened AS (
    SELECT
        l.contract_address AS vault,
        l.block_time,
        l.tx_hash,
        bytearray_to_uint256(bytearray_substring(l.data, 1, 32))   / 1e6 AS spent_usdg,
        bytearray_to_uint256(bytearray_substring(l.data, 65, 32))  / 1e8 AS entry_price,
        bytearray_to_uint256(bytearray_substring(l.data, 97, 32))  / 1e8 AS stop_price,
        bytearray_to_uint256(bytearray_substring(l.data, 129, 32)) / 1e8 AS target_price,
        ROW_NUMBER() OVER (PARTITION BY l.contract_address ORDER BY l.block_number, l.index) AS n
    FROM robinhood.logs l
    JOIN vaults v ON v.vault = l.contract_address
    WHERE l.topic0 = 0x06453d2b71f23b1525831572ca829c929bc7fbbc813f7625af2d97e0391736c5
),
closed AS (
    SELECT
        l.contract_address AS vault,
        l.block_time,
        l.tx_hash,
        from_utf8(bytearray_substring(
            l.data, 225,
            CAST(bytearray_to_uint256(bytearray_substring(l.data, 193, 32)) AS integer)
        )) AS reason,
        bytearray_to_uint256(bytearray_substring(l.data, 65, 32))  / 1e6 AS received_usdg,
        bytearray_to_uint256(bytearray_substring(l.data, 97, 32))  / 1e8 AS exit_price,
        bytearray_substring(l.data, 141, 20)                             AS closed_by,
        bytearray_to_uint256(bytearray_substring(l.data, 161, 32)) / 1e6 AS bounty_usdg,
        ROW_NUMBER() OVER (PARTITION BY l.contract_address ORDER BY l.block_number, l.index) AS n
    FROM robinhood.logs l
    JOIN vaults v ON v.vault = l.contract_address
    WHERE l.topic0 = 0x2b67be3dd71fc0a4ae0cba73db29b8616daea57cbba81925c55a70acebce28de
)
-- A vault holds one position at a time, so its nth open pairs with its nth close.
SELECT
    o.vault,
    o.block_time                       AS opened_at,
    o.spent_usdg,
    o.entry_price,
    o.stop_price,
    o.target_price,
    c.block_time                       AS closed_at,
    c.reason,
    c.exit_price,
    c.received_usdg,
    c.received_usdg - o.spent_usdg     AS pnl_usdg,
    c.bounty_usdg,
    CASE
        WHEN c.tx_hash IS NULL       THEN 'still open'
        WHEN c.reason = 'operator'   THEN 'our executor (signal exit)'
        WHEN c.reason = 'owner'      THEN 'vault owner'
        WHEN c.bounty_usdg > 0       THEN 'third party, paid the bounty'
        ELSE                              'our executor'
    END                                AS closed_by_whom,
    c.closed_by,
    o.tx_hash                          AS open_tx,
    c.tx_hash                          AS close_tx
FROM opened o
LEFT JOIN closed c ON c.vault = o.vault AND c.n = o.n
ORDER BY o.block_time DESC
