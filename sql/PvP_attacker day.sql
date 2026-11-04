-- db: log
-- 卡片:玩家 × 天 发起入侵次数(大 R 风险、生命周期 PvP 参与)。近 60 天。
-- 2026-10-20 初版。
SELECT monetId, dateCN, COUNT(*) AS invade_count
FROM CheckInvadeBattle
WHERE dateCN >= CURDATE() - INTERVAL 60 DAY
  AND dateCN <  CURDATE()
GROUP BY monetId, dateCN
