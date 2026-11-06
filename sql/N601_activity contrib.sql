-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新活动积分贡献(NewEraActivityContributionV1)和结算发奖(NewEraActivityRewardV1,活动结束后才有)。kind = contrib / reward。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT 'contrib' AS kind, periodKey COLLATE DATABASE_DEFAULT AS period_key, ruleKey COLLATE DATABASE_DEFAULT AS rule_key, monetId, amount, createdAt AS at FROM invade_user_n601.newera_center.NewEraActivityContributionV1 WHERE serverId = 601
UNION ALL
SELECT 'reward', periodKey COLLATE DATABASE_DEFAULT, CAST(status AS varchar(64)) COLLATE DATABASE_DEFAULT, monetId, 1, appliedAt FROM invade_user_n601.newera_center.NewEraActivityRewardV1 WHERE serverId = 601
