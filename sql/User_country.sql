-- db: log
-- 卡片:每个账号最近一次记录的国家。getUserCountry 没有日期索引,按主键倒序只读最后 30 万行(约覆盖 15 万个账号)。
-- 约一半活跃玩家在这里没有记录,页面上显示为「未知」,不隐藏。
-- 2026-10-21 初版。原写法(子查询 MAX(tid) - K)在 MySQL 5.6 的派生表里走全表扫描,改为 ORDER BY tid DESC LIMIT。
SELECT monetId,
       SUBSTRING_INDEX(GROUP_CONCAT(country ORDER BY tid DESC SEPARATOR '|'), '|', 1) AS country
FROM (SELECT tid, monetId, country FROM getUserCountry ORDER BY tid DESC LIMIT 300000) r
WHERE country IS NOT NULL AND country <> ''
GROUP BY monetId
