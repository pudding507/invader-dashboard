-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 老虎机逐局(11-03 共约 700 行)。costs 以 [52001, 开头 = 用老虎机券,否则 [3,n] = 用 n 钻石;
-- rewards 是奖励列表(原文,计算层取钻石部分)。2026-11-03 初版(601 看板第一期)。
SELECT monetId, createTime AS created_at, CASE WHEN costs LIKE '[52001,%' THEN 1 ELSE 0 END AS used_ticket,
       betBaseDiamond AS bet_base, rewards
FROM invade_user_n601.dbo.SlotSpinRecord
