-- db: prod  (SQL Server invade_user_n601,newera_center 架构)
-- 卡片:601 宠物竞猜每人每轮一行(11-03 共约 650 行)。bets 里有 diamondUsed > 0 的轮 = 用了钻石,否则只用券。
-- rewardDiamonds 是返还的钻石。2026-11-03 初版(601 看板第一期)。
SELECT monetId, createTime AS created_at, betDiamonds AS bet,
       CASE WHEN PATINDEX('%"diamondUsed":[1-9]%', bets) > 0 THEN 1 ELSE 0 END AS used_diamond,
       rewardDiamonds AS reward_diamonds
FROM invade_user_n601.newera_center.PetQuizBetRecord
WHERE serverId = 601
