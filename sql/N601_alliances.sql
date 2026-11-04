-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 联盟列表(十几行)。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT id AS alliance_id, level, contribution, createTime AS created_at FROM invade_user_n601.dbo.alliance
