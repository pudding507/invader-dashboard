-- db: log   (MySQL invaderLogData)
-- 卡片:玩家 × 天 登录聚合。活跃、等级、联盟、平台、版本、服 都从这里算。
-- 窗口:近 150 天的完整日(不含今天)。dateCN 有索引。
-- 2026-10-20 初版。
-- 2026-10-20 改为按 账号 × 天 × 服 聚合:同一账号在多个服有角色,按账号取最高等级会把老服高等级和新服低等级混在一起,
--            升级速度会出现大量「0 天」。DAU 等仍在渲染层按账号去重,不受影响。
-- 2026-10-21 加 last_login_at = 当天该服最后一条登录记录的时间(中国时间,精确到秒),给大 R 风险表「最后登录时间」用。行数不变。
SELECT monetId,
       dateCN,
       COUNT(*)              AS login_records,
       MAX(governmentLevel)  AS max_level,
       MAX(allianceId)       AS alliance_id,
       MAX(clientType)       AS client_type,
       MAX(clientVersion)    AS client_version,
       serverId              AS server_id,
       MAX(timeCN)           AS last_login_at
FROM GetUserInfo
WHERE dateCN >= CURDATE() - INTERVAL 150 DAY
  AND dateCN <  CURDATE()
  AND monetId > 0
GROUP BY monetId, dateCN, serverId
