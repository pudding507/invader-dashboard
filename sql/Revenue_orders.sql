-- db: prod  (SQL Server invade_billing)
-- 卡片:近 150 天订单(美元毛流水)。不含 601 新版内测服(含沙盒 / 测试卡付款)。
-- 2026-10-20 初版。
SELECT monetId, serverId AS server_id, channel, productId AS product_id, price, createTime AS created_at
FROM invade_billing.dbo.TopUpRecord
WHERE serverId <> 601
  AND createTime >= DATEADD(day, DATEDIFF(day, 0, GETDATE()) - 150, 0)
  AND createTime <  DATEADD(day, DATEDIFF(day, 0, GETDATE()), 0)
