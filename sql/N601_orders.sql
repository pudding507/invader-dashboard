-- db: prod  (SQL Server invade_billing)
-- 卡片:601 服全部订单(几十行)。含支付联调期和测试号订单,剔除规则在计算层(compute.py N601_*),
--       剔除后也只算「待核实充值」:Google 可能是测试卡、PayerMax 是否真实扣款未确认。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, orderId AS order_id, channel, productId AS product_id, price, createTime AS created_at
FROM invade_billing.dbo.TopUpRecord
WHERE serverId = 601
