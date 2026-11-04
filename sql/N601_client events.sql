-- db: rs  (Redshift ods.invader_events,New Era 客户端埋点)
-- 卡片:601 客户端埋点逐条(11-03 全表约 1.5 万行,整表几秒)。只取 Invader 的事件(app_source = INVADER,去掉混进来的 Looba),
--       服号为空(登录前的事件)或 601 的;测试服 1、3 去掉。安装 ID 只取 MD5,不取原值。时间用服务器收件时间 server_time(UTC),
--       计算层 +8 小时转中国时间;客户端事件时间 event_time 有手机时钟误差,不用。
-- 量大了以后改成按天聚合的卡。2026-11-03 初版(用户批准 601 看板第一期)。
-- 2026-11-04 改(用户确认):① 加 B72(2.4.0053)起的字段 event_uuid、install_referrer、city_level、operation_id、step_id、
--       target_level、device_model、os_version;计算层按 event_uuid 去重(数仓链路不去重;B72 之前的版本没有 uuid,不能精确去重)。
--       ② 去掉测试包:版本号不是纯数字的(如 2.4.0040-qa-probe 13 行、0.0.0-dw-test 1 行)。
--       ③ install_referrer 只在本地计算里归成来源类别(Facebook / Instagram / 自然量 / 未设置 / 其他),原文不进页面。
--       注意:服号为空不只是登录前事件(11-04 查:shop_open 等登录后事件也有 40%–100% 服号为空),计算层按 user_id 认角色。
SELECT event_name, server_time, user_id, MD5(device_id) AS install_md5, sid, client_version, platform, server_id, device_tier,
       start_reason, active_seconds, end_reason, stage, network_type, safe_error_code, login_method, is_existing_account,
       guide_id, building_type, completion_method, missing_resource_type, reason_code, growth_system, missing_amount_bucket,
       mode_id, fps_bucket, stall_count, screen_id, duration_ms, memory_bucket, tab, entry, placement, latency_bucket, component,
       event_uuid, install_referrer, city_level, operation_id, step_id, target_level, device_model, os_version
FROM ods.invader_events
WHERE app_source = 'INVADER' AND COALESCE(server_id, 601) = 601
  AND client_version ~ '^[0-9.]+$'
