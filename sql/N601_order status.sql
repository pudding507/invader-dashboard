-- db: prod  (SQL Server invade_billing)
-- 卡片:New Era 订单到账状态(Google / Apple 内购),每笔商店订单一行,全表几十行。
-- 订单 UnityBillingOrderV1 → 收据 UnityBillingReceiptV1(商店确认后才写,orderId = TopUpRecord.orderId)→ 发货步骤 UnityBillingGrantV1。
-- store_test:收据里 Google 返回了 purchaseType(只有测试卡 / 促销码购买才带这个字段;现有 13 笔都是 0 = 测试卡);Apple 看 environment = sandbox。
-- money_state:发货步骤 google-money-v1 里 Google 订单接口的状态,PROCESSED = 已扣款,REFUNDED = 已退款;Apple 没有这一步。
-- rewards_done:order-rewards-v1 里 rewardsComplete = true(奖励已发放)。
-- 只取判断用的标记,不取收据原文(含购买凭证)。PayerMax 网页支付不经过这几张表(UnityBillingExternalPayerMaxV1 已建、0 行)。
-- 2026-11-03 初版(用户批准把到账状态接进 601 页)。
SELECT r.orderId AS order_id, o.channel, o.environment, o.serverId AS server_id, o.monetId,
       CASE WHEN CHARINDEX('"purchaseType":', r.rawProof) > 0 THEN 1 ELSE 0 END AS store_test,
       r.confirmedAtMs AS confirmed_ms,
       (SELECT COUNT(*) FROM invade_billing.dbo.UnityBillingGrantV1 g
         WHERE g.orderKey = o.orderKey AND g.stepName = 'order-rewards-v1' AND CHARINDEX('"rewardsComplete":true', g.resultJson) > 0) AS rewards_done,
       (SELECT MAX(CASE WHEN CHARINDEX('"platformState":"REFUNDED"', g.resultJson) > 0 THEN 'REFUNDED'
                        WHEN CHARINDEX('"platformState":"PROCESSED"', g.resultJson) > 0 THEN 'PROCESSED' ELSE 'OTHER' END)
          FROM invade_billing.dbo.UnityBillingGrantV1 g WHERE g.orderKey = o.orderKey AND g.stepName = 'google-money-v1') AS money_state
FROM invade_billing.dbo.UnityBillingOrderV1 o
JOIN invade_billing.dbo.UnityBillingReceiptV1 r ON r.orderKey = o.orderKey
