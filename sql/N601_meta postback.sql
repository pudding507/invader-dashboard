-- db: prod  (SQL Server invade_billing)
-- 卡片:601 付费回传 Meta 的记录(UnityBillingNoticeV1 里 payload 类型是 facebook-purchase 的),按天 × 回传状态。几十行。
-- disposition:facebook-http-accepted = 服务端发给 Meta 并被接受;meta-route-held = 10-29 起改由客户端 Meta SDK 发送(结果不回写库);
--             skipped-no-attribution = 没有归因、没发。同表的 stat-written 是别的记录类型,不是付费回传,不取。
-- createdAtMs 是 UTC 毫秒,这里 +8 小时转中国时间按天。2026-11-05 初版(用户确认,缺失清单 P0-1 回传状态)。
SELECT CONVERT(char(10), DATEADD(hour, 8, DATEADD(second, CAST(createdAtMs / 1000 AS int), '1970-01-01')), 120) AS d,
       disposition, COUNT(*) AS n, COUNT(DISTINCT monetId) AS users
FROM invade_billing.dbo.UnityBillingNoticeV1
WHERE serverId = 601 AND CHARINDEX('facebook-purchase', payloadJson) > 0
GROUP BY CONVERT(char(10), DATEADD(hour, 8, DATEADD(second, CAST(createdAtMs / 1000 AS int), '1970-01-01')), 120), disposition
