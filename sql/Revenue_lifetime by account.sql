-- db: prod  (SQL Server invade_billing)
-- 卡片:每个账号在老服(不含 601)的历史累计付费。TopUpRecord 从 2023-11-10 起有全部渠道订单,按账号汇总后几千行。
-- 用途:601 页「老付费者回流 vs 真新用户」(同账号或同设备上的账号以前付过费没有)、老服大 R 进入 601 的比例、召回大 R 回充。
-- 2026-10-22 初版(用户批准执行)。
SELECT monetId, COUNT(*) AS orders, SUM(price) AS usd, MIN(createTime) AS first_at, MAX(createTime) AS last_at
FROM invade_billing.dbo.TopUpRecord
WHERE serverId <> 601
GROUP BY monetId
