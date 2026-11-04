-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 世界 BOSS(按人汇总)。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT monetId, COUNT(*) AS fights, SUM(CAST(damageDone AS bigint)) AS damage, MIN(createTime) AS first_at, MAX(createTime) AS last_at FROM invade_user_n601.dbo.WorldMonsterUserData GROUP BY monetId
