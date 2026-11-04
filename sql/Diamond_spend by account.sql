-- db: log
-- 卡片:近 90 天每个账号 × 钻石去向的消耗,另加竞猜 / 老虎机的返还(算净额用)。用于「收入按功能拆」:
--       钻石包收入按每个付费者同期钻石去向按比例分摊。走 dateCN 索引,范围和看板每天跑的钻石日账相同。
-- 2026-10-29 初版。
SELECT monetId, 'out' AS direction, typeEnum AS diamond_type, SUM(amount) AS diamonds
FROM ConsumeDiamond
WHERE dateCN >= CURDATE() - INTERVAL 90 DAY AND dateCN < CURDATE()
GROUP BY monetId, typeEnum
UNION ALL
SELECT monetId, 'in' AS direction, typeEnum AS diamond_type, SUM(num) AS diamonds
FROM addDiamond
WHERE dateCN >= CURDATE() - INTERVAL 90 DAY AND dateCN < CURDATE() AND typeEnum IN ('PetQuiz', 'SlotSpin')
GROUP BY monetId, typeEnum
