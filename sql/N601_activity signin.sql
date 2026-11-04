-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 每日签到记录(约 200 行),和每日任务一起作活跃代理;governmentLv = 签到时的主城等级。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, governmentLv AS government_level, time AS signin_at
FROM invade_user_n601.dbo.DailySignInRecord
