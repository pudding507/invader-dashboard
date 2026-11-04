-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 每人每天做了几条每日任务。601 不写老版登录日志(GetUserInfo),活跃只能用这张表代理,
--       没做每日任务的活跃玩家会漏掉(偏低)。原表约 7 千行,这里按人 × 天聚合。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, CONVERT(varchar(10), createTime, 120) AS day, COUNT(*) AS tasks
FROM invade_user_n601.dbo.dailyTasksUserData
GROUP BY monetId, CONVERT(varchar(10), createTime, 120)
