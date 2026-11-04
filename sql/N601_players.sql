-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新版内测服的全部账号 ID。只取 ID 一列。
-- 用途:把内测账号从「新注册」里剔除。601 是新版,不写老版的登录日志(GetUserInfo),
--      内测账号在老版数据里表现为「注册了但没进游戏」,会把进入游戏率、留存拉低(10 月 Android 进入率下降的主要来源)。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId FROM invade_user_n601.dbo.player
