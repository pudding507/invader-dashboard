-- db: log
-- 卡片:近 7 天老虎机券(道具 52001)按天 × 用途(useItem.from:PetQuiz 宠物竞猜 / SlotSpin 老虎机)。useItem 约 3.8 亿行,走 dateCN_serverId 索引,7 天约扫 300 万行、40 秒左右。
-- 2026-11-02 初版:券八成用在宠物竞猜。之前「使用」只算老虎机的券局,发放 ÷ 使用被高估(4.9 倍 → 两种用途合计 1.3 倍)。
SELECT dateCN, `from` AS use_for, COUNT(DISTINCT monetId) AS users, SUM(useNum) AS tickets
FROM useItem
WHERE dateCN >= CURDATE() - INTERVAL 7 DAY AND dateCN < CURDATE() AND itemId = 52001
GROUP BY dateCN, `from`
