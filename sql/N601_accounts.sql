-- db: prod  (SQL Server invade_account × invade_user_n601)
-- 卡片:601 每个角色对应账号的建号系统、建号时的客户端版本和注册 IP(几百行)。
-- 注册 IP 只在抓数时用:fetch_db 用本地的 IP 分配表(data/rir/,五大洲 IP 管理机构公开的分配记录)换成国家码后立即丢掉,
-- 不写进 raw_metrics,也不上看板。挂 VPN 的人国家会判错。2026-11-04 初版(601 国家 / 版本 / 平台筛选,用户选定注册 IP 方案)。
SELECT u.user_id AS monetId, u.sysType AS sys_type, u.clientVersion AS reg_version, u.ip
FROM invade_account.dbo.user_info u
WHERE u.user_id IN (SELECT monetId FROM invade_user_n601.dbo.player)
