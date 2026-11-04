-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 活动列表(约 50 行),给活动编号配名字。
-- 2026-10-21 初版(用户批准执行)。
SELECT id AS activity_id, activity_name, activity_open, activity_close, parent_id FROM invade_user_n601.dbo._activity
