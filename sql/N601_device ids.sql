-- db: prod  (SQL Server invade_account)
-- 卡片:账号的设备广告 ID(GAID / IDFA),只取 MD5,不把原始 ID 带回本地。全表约 1.1 万行。用于判断 601 新建号是不是老玩家同一台设备上的小号。全 0 的 ID(用户关了广告追踪)不取。
-- 2026-10-21 初版(用户批准执行)。
-- 2026-10-21 核对:截出来的 11,132 个里有 1 个不是 设备 ID 格式(8-4-4-4-12),加了连字符位置检查把它去掉。
SELECT monetId, master.dbo.fn_varbintohexstr(HASHBYTES('MD5', adid)) AS device_hash
FROM (SELECT monetId,
             SUBSTRING(rawData, CHARINDEX('"', rawData, CHARINDEX(':', rawData, CHARINDEX('"advertiser_id"', rawData)) + 1) + 1, 36) AS adid
      FROM invade_account.dbo.user_attribution_data
      WHERE CHARINDEX('"advertiser_id"', rawData) > 0) ids
WHERE adid NOT LIKE '00000000-0000-0000-0000-000000000000%' AND LEN(adid) = 36
  AND SUBSTRING(adid, 9, 1) = '-' AND SUBSTRING(adid, 14, 1) = '-' AND SUBSTRING(adid, 19, 1) = '-' AND SUBSTRING(adid, 24, 1) = '-'
