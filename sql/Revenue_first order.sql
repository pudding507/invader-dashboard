-- db: prod  (SQL Server invade_billing)
-- 卡片:每个付费账号在统一订单表里的第一笔订单时间(判断「新付费」)。
-- 统一订单表从 2023-11-10 开始,更早的首充看不到,所以 2023-11 前就付过费的人会被当成那之后才首充;
-- 近 150 天的窗口离 2023-11 很远,影响只在于极少数两年多没付费又回来付费的人。不含 601。
-- 2026-10-20 初版。
SELECT monetId, MIN(createTime) AS first_order_at
FROM invade_billing.dbo.TopUpRecord
WHERE serverId <> 601
GROUP BY monetId
