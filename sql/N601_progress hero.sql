-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 每人英雄数和最高英雄等级(未删除的英雄,约 130 行)。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, COUNT(*) AS heroes, MAX(level_) AS max_hero_level
FROM invade_user_n601.dbo.hero
WHERE deleted = 0
GROUP BY monetId
