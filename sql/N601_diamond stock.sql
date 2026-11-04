-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 每人当前钻石存量(几百行,全表)。计算层只算内测玩家。2026-11-03 初版(601 看板第一期)。
SELECT monetId, num AS diamonds
FROM invade_user_n601.dbo.DiamondResource
