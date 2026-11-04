-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新版内测服每个角色的注册时间、最后登录、客户端、名字。约 200 行。
-- 时间是服务器时间(原样),不换时区。
-- 2026-10-21 初版(用户批准执行)。
SELECT monetId, name, createTime AS created_at, lastLoginTime AS last_login_at,
       clientType AS client_type, clientVersion AS client_version
FROM invade_user_n601.dbo.player
