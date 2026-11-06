-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 限时道具 / 票:发放(NewEraExpiringItemGrantV1、NewEraActivityTicketLotV1)和使用(NewEraActivityTicketUseV1)。kind = grant / lot / use。
--       itemId 52001 = 老虎机 / 宠物竞猜券。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT 'grant' AS kind, monetId, itemId AS item_id, quantity AS amount, startsMs AS at_ms, NULL AS at FROM invade_user_n601.newera_center.NewEraExpiringItemGrantV1 WHERE serverId = 601
UNION ALL
SELECT 'lot', monetId, itemId, granted, startsMs, createdAt FROM invade_user_n601.newera_center.NewEraActivityTicketLotV1 WHERE serverId = 601
UNION ALL
SELECT 'use', monetId, itemId, amount, NULL, createdAt FROM invade_user_n601.newera_center.NewEraActivityTicketUseV1 WHERE serverId = 601
