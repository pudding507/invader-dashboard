-- db: log
-- 卡片:近 7 天老虎机券(道具 52001)按天 × 发放来源。addItem 约 3.8 亿行,走 dateCN 索引,7 天约扫 140 万行、10 秒内。
-- 2026-10-29 初版:券一周发出约 132 万张、只用掉约 23 万张,单列监控积压。
SELECT dateCN, typeEnum, COUNT(DISTINCT monetId) AS users, SUM(num) AS tickets
FROM addItem
WHERE dateCN >= CURDATE() - INTERVAL 7 DAY AND dateCN < CURDATE() AND itemId = 52001
GROUP BY dateCN, typeEnum
