-- db: prod  (SQL Server invade_account)
-- 卡片:近 150 天注册的账号(只取需要的列,不取密码 / 手机号 / IP)。
-- user_id = monetId;create_date 为中国时间。有 15 个 user_id 重复,渲染层取最早一条。
-- SQL Server 2005 没有 date 类型,用 DATEADD/DATEDIFF 取零点。
-- 2026-10-20 初版。
SELECT user_id AS monetId,
       create_date,
       sysType   AS sys_type,
       phoneType AS phone_type
FROM invade_account.dbo.user_info
WHERE create_date >= DATEADD(day, DATEDIFF(day, 0, GETDATE()) - 150, 0)
  AND create_date <  DATEADD(day, DATEDIFF(day, 0, GETDATE()), 0)
