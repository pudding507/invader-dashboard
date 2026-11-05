-- db: log
-- 卡片:老服金币(resourceType 1)/ 水晶(2)账本按天 × 来源 / 去向(近 28 天)。
-- in  = AddResource:amount = 应发,actual = 实际进账(两者的差按字段名推断是仓库满了溢出,待研发确认);含 NPC / 离线产出等非玩家号,是全量合计。
-- out = ConsumeResource:花费(amount,actual 同 amount)。ConsumeResource 的日期索引是 (serverId, dateCN),必须带服号才走索引,
--       这里写死近 30 天有登录的 10 个老服;开新服要加进来。EXPLAIN 估:进账约 430 万行、花费约 780 万行。
-- 缺失清单 P1-7 的看板版,只放数字。2026-11-05 初版(用户确认)。
SELECT 'in' AS kind, dateCN, resourceType AS resource_type, typeEnum AS source, SUM(amount) AS amount, SUM(actualAmount) AS actual
FROM AddResource WHERE dateCN >= CURDATE() - INTERVAL 28 DAY AND dateCN < CURDATE() AND resourceType IN (1, 2)
GROUP BY dateCN, resourceType, typeEnum
UNION ALL
SELECT 'out', dateCN, resourceType, typeEnum, SUM(amount), SUM(amount)
FROM ConsumeResource WHERE serverId IN (285, 337, 342, 344, 347, 348, 349, 350, 351, 401)
  AND dateCN >= CURDATE() - INTERVAL 28 DAY AND dateCN < CURDATE() AND resourceType IN (1, 2)
GROUP BY dateCN, resourceType, typeEnum
