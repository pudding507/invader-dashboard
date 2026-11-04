-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 名人每日任务,按人 × 天汇总(原表约 300 行)。
-- 2026-10-21 初版(用户批准执行)。补活跃痕迹:601 不写老版登录日志,活跃靠各种带日期的记录拼。
SELECT monetId, CONVERT(varchar(10), createTime, 120) AS day, COUNT(*) AS tasks FROM invade_user_n601.dbo.CelebrityTaskDailyData GROUP BY monetId, CONVERT(varchar(10), createTime, 120)
