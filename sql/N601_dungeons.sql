-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 副本 1 / 副本 2 进度(当前状态,按人汇总)。completed = 通关的关数,max_completed = 通关的最大关卡 ID。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT 'dungeon1' AS mode, monetId, COUNT(*) AS unlocked, SUM(CAST(completed AS int)) AS completed, MAX(CASE WHEN completed = 1 THEN dungeonsId END) AS max_completed
FROM invade_user_n601.dbo.dungeons GROUP BY monetId
UNION ALL
SELECT 'dungeon2', monetId, COUNT(*), SUM(CAST(isCompleted AS int)), MAX(CASE WHEN isCompleted = 1 THEN dungeonsId END)
FROM invade_user_n601.dbo.Dungeons2 GROUP BY monetId
