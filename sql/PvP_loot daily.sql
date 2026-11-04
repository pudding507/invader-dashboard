-- db: log
-- 卡片:天 × 来源 × 资源类型 的资源获得量,只取 PvP 相关来源(CnameInfo:Occupy 占领、Snatch 抢夺、CollectTax 税收、Resist 反抗)。近 30 天。
-- AddResource 很大(4.8 亿行)但有 dateCN 索引,30 天约 450 万行(EXPLAIN 估 60 天 910 万行,故只取 30 天);只做按天汇总,不按玩家。
-- 资源表里有非玩家 ID(NPC / 离线产出),这里是全量合计,不区分。
-- 2026-10-21 初版。
SELECT dateCN, typeEnum AS source, resourceType AS resource_type, SUM(actualAmount) AS amount, COUNT(DISTINCT monetId) AS users
FROM AddResource
WHERE dateCN >= CURDATE() - INTERVAL 30 DAY AND dateCN < CURDATE()
  AND typeEnum IN ('Occupy', 'Snatch', 'CollectTax', 'Resist')
GROUP BY dateCN, typeEnum, resourceType
