-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 建筑升级逐次(UnityBuildingOperationV1,11-04 建表):每次发起升级一行,fromLevel = 升级前等级(主城 = buildingType 5)。
--       有 consentScope 字段,可能只记同意采集的玩家,覆盖范围待研发确认。时间是 UTC 毫秒。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT monetId, buildingType AS building_type, fromLevel AS from_level, startedAtMs AS started_ms
FROM invade_user_n601.dbo.UnityBuildingOperationV1 WHERE serverId = 601
