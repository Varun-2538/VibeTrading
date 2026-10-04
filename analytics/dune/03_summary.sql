-- One row of headline numbers for the dashboard's counters.
WITH vaults AS (
    SELECT bytearray_substring(data, 13, 20) AS vault
    FROM robinhood.logs
    WHERE contract_address = 0x04c96936670c38982d1e7ef23cadd84d6891c818
      AND topic0 = 0x2c2642e51c5da7f061023663faf2699e94a26a02c688fc21790dcdec49fade6b
),
events AS (
    SELECT l.*
    FROM robinhood.logs l
    JOIN vaults v ON v.vault = l.contract_address
)
SELECT
    (SELECT COUNT(*) FROM vaults)                                                    AS vaults_deployed,
    SUM(CASE WHEN topic0 = 0x06da3309189fa49284f335d2c2bcb4cb0b8ad2a59ad92a9bdebeeb8f1ceba511
             THEN bytearray_to_uint256(bytearray_substring(data, 1, 32)) / 1e6 END)  AS usdg_deposited,
    COUNT_IF(topic0 = 0x06453d2b71f23b1525831572ca829c929bc7fbbc813f7625af2d97e0391736c5) AS positions_opened,
    COUNT_IF(topic0 = 0x2b67be3dd71fc0a4ae0cba73db29b8616daea57cbba81925c55a70acebce28de) AS positions_closed,
    COUNT_IF(topic0 = 0x2b67be3dd71fc0a4ae0cba73db29b8616daea57cbba81925c55a70acebce28de
             AND bytearray_to_uint256(bytearray_substring(data, 161, 32)) > 0)       AS closed_by_third_party,
    SUM(CASE WHEN topic0 = 0x2b67be3dd71fc0a4ae0cba73db29b8616daea57cbba81925c55a70acebce28de
             THEN bytearray_to_uint256(bytearray_substring(data, 161, 32)) / 1e6 END) AS bounties_paid_usdg
FROM events
