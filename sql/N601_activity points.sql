-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 活动积分(约 400 行)。activityConfId 对应 _activity.id。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, activityConfId AS activity_id, point FROM invade_user_n601.dbo._activityUserData
