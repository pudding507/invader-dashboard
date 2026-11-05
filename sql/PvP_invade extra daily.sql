-- db: log
-- 卡片:老服入侵结构按天(近 28 天):进攻场次、进攻人数、胜场、打 NPC 城的场次(城主号 ≥ 10 亿 = NPC,依据 CreateNewNPC 的号段)、
--       打「已被别人占着的城」的场次(occupiedId ≠ 城主);另一行是解救(invaderRelease):次数、发起人数、被救的人数(放在 on_occ 列)。
-- EndInvadeBattle / invaderRelease 都有 dateCN 索引,每张几秒。缺失清单 P1-5(老服入侵逐场)的看板版,只放数字。
-- 2026-11-05 初版(用户确认)。
SELECT 'battle' AS kind, dateCN, COUNT(*) AS n, COUNT(DISTINCT monetId) AS users, SUM(win) AS wins,
       SUM(ownerId >= 1000000000) AS npc, SUM(occupiedId > 0 AND occupiedId <> ownerId) AS on_occ
FROM EndInvadeBattle WHERE dateCN >= CURDATE() - INTERVAL 28 DAY AND dateCN < CURDATE() GROUP BY dateCN
UNION ALL
SELECT 'release', dateCN, COUNT(*), COUNT(DISTINCT monetId), 0, 0, COUNT(DISTINCT releaseId)
FROM invaderRelease WHERE dateCN >= CURDATE() - INTERVAL 28 DAY AND dateCN < CURDATE() GROUP BY dateCN
