-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 联盟成员(当前状态,几十行)。identity(T-SQL 保留字,要加方括号)= 成员身份。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT monetId, allianceId AS alliance_id, [identity] AS member_role, contribution, createTime AS joined_at FROM invade_user_n601.dbo.allianceMember
