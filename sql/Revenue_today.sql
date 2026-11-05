-- db: prod  (SQL Server invade_billing)
-- 卡片:今天 0 点(中国时间)到抓数时刻的订单,含 601。只用于页面「今天实时」一块,不进任何日指标(今天未完整)。
-- 每天几十到一两百行。601 的订单仍是「待核实」口径,剔除规则同 N601_orders(测试号、内测前)。
-- 2026-10-28 初版(用户要求看板显示到今天的数据)。
-- 2026-11-05 加 orderId(商店订单号):601 订单按 New Era 支付表判断测试卡 / 沙盒 / 退款(用户确认)
SELECT monetId, serverId AS server_id, channel, productId AS product_id, price, createTime AS created_at, orderId AS order_id
FROM invade_billing.dbo.TopUpRecord
WHERE createTime >= DATEADD(day, DATEDIFF(day, 0, GETDATE()), 0)
