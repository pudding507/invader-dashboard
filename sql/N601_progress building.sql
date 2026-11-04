-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 每人每种建筑的最高等级(原表约 2 千行)。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, buildingType AS building_type, MAX(buildingLevel) AS max_level, COUNT(*) AS buildings
FROM invade_user_n601.dbo.building
GROUP BY monetId, buildingType
