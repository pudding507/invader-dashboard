-- db: log
-- 卡片:近 28 天老虎机按天 × 下注方式(钻石 / 券)。SlotSpin 约 3,750 万行、没有日期索引,
--       按查询规范用主键范围:只扫最后 150 万行(近 30 天约 100 万行),再按日期筛;最早日期不到窗口起点时计算层标「数据不全」。
-- costs:[[3,N]] = 花 N 钻石(baseDiamond = 下注钻石);[[52001,1]] = 花一张老虎机券(baseDiamond 固定记 5,不是真花钻石)。
-- 2026-10-29 初版:老虎机返还率预警改为只看钻石下注的局,券转出单列。
SELECT s.dateCN,
       CASE WHEN s.costs LIKE '[[52001,%' THEN 'ticket' WHEN s.costs LIKE '[[3,%' THEN 'diamond' ELSE 'other' END AS kind,
       COUNT(*) AS spins, COUNT(DISTINCT s.monetId) AS users,
       SUM(s.baseDiamond) AS base_diamond, SUM(s.rewardDiamond) AS reward_diamond
FROM SlotSpin s JOIN (SELECT MAX(tid) - 1500000 AS lo FROM SlotSpin) b ON s.tid >= b.lo
WHERE s.dateCN >= CURDATE() - INTERVAL 28 DAY AND s.dateCN < CURDATE()
GROUP BY s.dateCN, kind
