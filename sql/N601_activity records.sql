-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 三类活动记录按 人 × 活动 汇总:兑换(ExchangeItemRecord,次数)、建筑冲级奖励(BuildingUpRecord,领取数)、冲级奖励(passionLevelingRecord,领取数)。原表合计约 7 千行。
-- 2026-10-21 初版(用户批准执行)。
SELECT 'exchange' AS kind, monetId, activityId AS activity_id, SUM(exchangeTimes) AS times FROM invade_user_n601.dbo.ExchangeItemRecord GROUP BY monetId, activityId
UNION ALL
SELECT 'building_up', monetId, activityId, SUM(CAST(isGot AS int)) FROM invade_user_n601.dbo.BuildingUpRecord GROUP BY monetId, activityId
UNION ALL
SELECT 'passion_leveling', monetid, activityId, SUM(CAST(isGot AS int)) FROM invade_user_n601.dbo.passionLevelingRecord GROUP BY monetid, activityId
