-- db: log
-- 卡片:天 × 类型 钻石产出(addDiamond)与消耗(ConsumeDiamond)。近 90 天。
-- PetQuiz / SlotSpin 有返还,净消耗 = 同类型 消耗 − 产出,由渲染层计算。
-- 2026-10-20 初版。
SELECT dateCN, 'out' AS direction, typeEnum AS diamond_type, SUM(amount) AS diamonds, COUNT(DISTINCT monetId) AS users
FROM ConsumeDiamond
WHERE dateCN >= CURDATE() - INTERVAL 90 DAY AND dateCN < CURDATE()
GROUP BY dateCN, typeEnum
UNION ALL
SELECT dateCN, 'in' AS direction, typeEnum AS diamond_type, SUM(num) AS diamonds, COUNT(DISTINCT monetId) AS users
FROM addDiamond
WHERE dateCN >= CURDATE() - INTERVAL 90 DAY AND dateCN < CURDATE()
GROUP BY dateCN, typeEnum
