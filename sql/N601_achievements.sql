-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 成就(每人每个成就一行,约 5 千行)。库里没有成就名称表,只有编号。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, achievementId AS achievement_id, CAST(isFinish AS int) AS finished FROM invade_user_n601.dbo.AchievementUserData_New
