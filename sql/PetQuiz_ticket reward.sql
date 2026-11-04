-- db: log
-- 卡片:近 28 天宠物竞猜「纯券下注」轮次的钻石返还,按天。券局不花钻石,返还的钻石是净发。
-- PetQuizRewards 约 500 万行、只有主键索引,按查询规范用主键范围:只扫最后 25 万行(约 40 天),再按日期筛;最早日期不到窗口起点时计算层标「数据不全」。
-- 纯券 = bets 里所有项 diamondUsed 都是 0。混合下注(同一轮既用券又用钻)不计,28 天与逐项按比例分摊的结果差 0.3%。
-- 这张表只记有返还的轮次,所以只能算返还,不能算返还率。
-- 2026-11-02 初版:券八成用在宠物竞猜,之前看板只算了老虎机券局的返还。
SELECT q.dateCN, COUNT(*) AS rounds, COUNT(DISTINCT q.monetId) AS users, SUM(q.rewardDiamonds) AS reward_diamond
FROM PetQuizRewards q JOIN (SELECT MAX(tid) - 250000 AS lo FROM PetQuizRewards) b ON q.tid >= b.lo
WHERE q.dateCN >= CURDATE() - INTERVAL 28 DAY AND q.dateCN < CURDATE()
  AND q.bets NOT REGEXP '"diamondUsed":[1-9]'
GROUP BY q.dateCN
