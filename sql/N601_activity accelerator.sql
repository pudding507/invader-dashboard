-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 加速道具使用日期(约 750 行)。可能只记每种道具最后一次使用的日期,只能补一部分活跃。
-- 2026-10-21 初版(用户批准执行)。补活跃痕迹:601 不写老版登录日志,活跃靠各种带日期的记录拼。
SELECT monetId, CONVERT(varchar(10), useDate, 120) AS day FROM invade_user_n601.dbo.itemAccelerator WHERE useDate IS NOT NULL
