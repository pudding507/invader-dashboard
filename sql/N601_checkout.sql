-- db: prod  (SQL Server invade_billing)
-- 卡片:New Era 点击付费(Google / Apple 内购发起支付),每次发起一行,全表约一两百行(只有主键,全表扫)。
-- createdAtMs 是 UTC 毫秒,计算层 +8 小时转中国时间;有 orderKey = 生成了订单(不代表到账,到账看 TopUpRecord);
-- deliveredAtMs 每行都有,不是到账时间,不取。PayerMax 网页支付不经过这张表。不按服过滤,计算层只取 601。
-- 2026-10-29 初版(用户批准加进 601 页)。
SELECT serverId AS server_id, monetId, createdAtMs AS created_ms,
       CASE WHEN orderKey IS NULL THEN 0 ELSE 1 END AS has_order
FROM invade_billing.dbo.UnityBillingCheckoutV1
