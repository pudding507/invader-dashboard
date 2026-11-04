-- db: log  (MySQL invaderPortal,旧后台每日汇总库,和 Log 库同一台)
-- 卡片:601 每天各主城等级的人数(旧后台每天对全服角色做的等级快照,10-01 起,约 300 行;按 date 索引)。
-- 每个主城等级取各类建筑里最大的人数(pnum)= 该等级的角色数。含测试号和内测前的角色,去不掉;只看分布怎么随天移动。
-- 601 库只存当前等级,这是 601 唯一现成的按天等级历史。2026-11-03 初版(601 看板第一期)。
SELECT date, governmentLevel AS city, MAX(pnum) AS players
FROM invaderPortal.BuildingByGovernment
WHERE serverId = 601 AND date >= '2026-10-01'
GROUP BY date, governmentLevel
