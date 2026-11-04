-- db: log   (MySQL invaderLogData)
-- 轻量刷新卡:昨天 + 今天到此刻的 玩家 × 天 × 服 登录聚合。dateCN 有索引,只扫两天。
-- first_login_at 用来算「昨天同一时刻」的对照(昨天在 HH:MM 之前就登录过的人数)。
-- 预计:昨天约 850–970 行 + 今天到此刻的行数,合计 ≤ 2,000 行。
-- 2026-10-28 草稿(待用户确认后执行)。
SELECT monetId,
       dateCN,
       serverId              AS server_id,
       MIN(timeCN)           AS first_login_at,
       MAX(timeCN)           AS last_login_at,
       COUNT(*)              AS login_records,
       MAX(governmentLevel)  AS max_level,
       MAX(clientType)       AS client_type
FROM GetUserInfo
WHERE dateCN >= CURDATE() - INTERVAL 1 DAY
  AND monetId > 0
GROUP BY monetId, dateCN, serverId
