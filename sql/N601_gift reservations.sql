-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新版礼包下单意向(约 50 行)。state 含义未核对,只按下单人数用。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, giftId AS gift_id, state, createdAtMs AS created_at_ms FROM invade_user_n601.dbo.UnityGiftReservationV1
