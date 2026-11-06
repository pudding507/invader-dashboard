-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 钻石花费流水(newera_center.NewEraActivityWalletSpendV1,11-04 起):每次花钻石一行,consumerKind = 去向;
--       金额在 fees(JSON:actualDiamond 钻石、actualGreen 绿钻),计算层解析。时间是 UTC 毫秒。601 之前没有钻石去向。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT monetId, consumerKind AS consumer, occurredAtMs AS occurred_ms, fees
FROM invade_user_n601.newera_center.NewEraActivityWalletSpendV1 WHERE serverId = 601
