-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 新活动排期(newera_center.NewEraActivityPeriodV1,服务端构建 56 / B72 起):每一期一行;payload 里 template = 活动类型、series = 系列,
--       openMs / closeMs 是 UTC 毫秒。只取类型、系列、时间、阶段,不取商品配置大字段。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT periodKey AS period_key, openMs AS open_ms, closeMs AS close_ms, settleMs AS settle_ms, lifecycleStage AS stage,
       SUBSTRING(payload, CHARINDEX('"template":"', payload) + 12, CHARINDEX('"', payload, CHARINDEX('"template":"', payload) + 12) - CHARINDEX('"template":"', payload) - 12) AS template,
       SUBSTRING(payload, CHARINDEX('"series":"', payload) + 10, CHARINDEX('"', payload, CHARINDEX('"series":"', payload) + 10) - CHARINDEX('"series":"', payload) - 10) AS series
FROM invade_user_n601.newera_center.NewEraActivityPeriodV1 WHERE realmId = 'newera-n601'
