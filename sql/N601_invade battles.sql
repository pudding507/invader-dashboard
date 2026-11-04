-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 入侵记录(每次一行,几十行)。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT attackerId AS attacker_id, defenseId AS defense_id, startTime AS started_at FROM invade_user_n601.dbo.invaderRecord
