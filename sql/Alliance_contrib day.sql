-- db: log
-- 卡片:玩家 × 天 联盟捐献次数(大 R 风险)。近 60 天。
-- 2026-10-20 初版。
SELECT monetId, dateCN, COUNT(*) AS contrib_count
FROM allianceContribution
WHERE dateCN >= CURDATE() - INTERVAL 60 DAY
  AND dateCN <  CURDATE()
GROUP BY monetId, dateCN
