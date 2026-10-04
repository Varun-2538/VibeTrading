-- VibeTrading vaults on Robinhood Chain: one row per vault the factory deployed.
-- Reads raw logs, so it needs no decoded ABI.
--   VaultDeployed(address indexed owner, address indexed asset, address vault, bytes32 disclosure)
WITH markets (asset, market) AS (
    VALUES
        (0x0bd7d308f8e1639fab988df18a8011f41eacad73, 'ETH'),
        (0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec, 'NVDA'),
        (0xd5f3879160bc7c32ebb4dc785f8a4f505888de68, 'QQQ'),
        (0x322f0929c4625ed5bad873c95208d54e1c003b2d, 'TSLA'),
        (0x117cc2133c37b721f49de2a7a74833232b3b4c0c, 'SPY'),
        (0xaf3d76f1834a1d425780943c99ea8a608f8a93f9, 'AAPL')
)
SELECT
    l.block_time                                   AS deployed_at,
    bytearray_substring(l.data, 13, 20)            AS vault,
    bytearray_substring(l.topic1, 13, 20)          AS owner,
    COALESCE(m.market, 'other')                    AS market,
    bytearray_substring(l.data, 33, 32)            AS disclosure_hash,
    l.tx_hash
FROM robinhood.logs l
LEFT JOIN markets m ON m.asset = bytearray_substring(l.topic2, 13, 20)
WHERE l.contract_address = 0x04c96936670c38982d1e7ef23cadd84d6891c818
  AND l.topic0 = 0x2c2642e51c5da7f061023663faf2699e94a26a02c688fc21790dcdec49fade6b
ORDER BY l.block_time DESC
