-- db: prod  (SQL Server invade_user_n<服>)
-- 卡片:各正式服近 150 天登录过的角色的国家(player.countryCode,游戏服务器记录)和设备语言。用于补全国家(Log 库 getUserCountry 覆盖不全)。
-- 每服玩家表几千到几万行,无 lastLoginTime 索引,全表扫但量小。服务器列表是 10-30 时近 30 天有登录的 10 个服,开新服要加一行。
-- 2026-10-30 初版。
SELECT 285 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n285.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 337 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n337.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 342 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n342.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 344 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n344.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 347 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n347.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 348 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n348.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 349 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n349.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 350 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n350.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 351 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n351.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
UNION ALL
SELECT 401 AS server_id, monetId, countryCode AS country_code, deviceLang AS device_lang FROM invade_user_n401.dbo.player WHERE lastLoginTime >= DATEADD(day, -150, GETDATE())
