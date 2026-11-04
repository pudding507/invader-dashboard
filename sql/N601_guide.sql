-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新手引导:每人完成过的引导步骤编号列表(约 300 行,每行不到 100 字)。步骤只有编号,没有名称。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, guides FROM invade_user_n601.dbo.GuideCondition
