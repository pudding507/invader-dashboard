-- db: prod  (SQL Server invade_account)
-- 轻量刷新卡:今天 0 点到此刻注册的账号。列和 NewUser_accounts 相同(不取密码 / 手机号 / IP)。
-- 预计:每天 60–200 行(近 7 天每天 63–202 个注册)。
-- 2026-10-28 草稿(待用户确认后执行)。
SELECT user_id AS monetId,
       create_date,
       sysType   AS sys_type,
       phoneType AS phone_type
FROM invade_account.dbo.user_info
WHERE create_date >= DATEADD(day, DATEDIFF(day, 0, GETDATE()), 0)
