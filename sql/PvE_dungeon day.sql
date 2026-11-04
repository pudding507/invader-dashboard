-- db: log
-- 卡片:玩家 × 天 副本 1 结算次数(生命周期 PvE 参与)。近 60 天。
-- 2026-10-20 初版。
SELECT monetId, dateCN, COUNT(*) AS dungeon_count
FROM EndDungeon
WHERE dateCN >= CURDATE() - INTERVAL 60 DAY
  AND dateCN <  CURDATE()
GROUP BY monetId, dateCN
