# 项目状态（2026-10-26 收尾）

## 一句话

基座、实验装置、两个场景的真模型实验全部完成；所有指标、图表、结论都可复现。

## 完成情况

| 项 | 状态 | 证据 |
|---|---|---|
| 公地困境插件 | 完成 | plugins/commons，声明/议约/取用/结算 |
| world 可视化 | 完成 | 回放台资源曲线 + 10% 警戒线 |
| 并发调度 | 完成 | 批次 4 局 3.3s→1.3s；同相位并行提问 |
| 成本与图表 | 完成 | cost_usd 列 + chart.svg（短标签、95%CI） |
| 合约与调解 | 完成 | 三组对照，违约率 0.25，调解后合作率 0.42→0.25 |
| 持久化与续跑 | 完成 | 停在第 2 轮 → 重启 → 恢复 paused → 续跑至结束 |
| 批次 GUI | 完成 | web/batches.html，同时展示 batches 与 experiments |
| 吞警徽 | 完成 | 竞选期自爆 → 无警长 + 直接黑夜 |
| 规则怪谈 | 完成 | plugins/rules_horror，条文可程序化检查 |
| TTS 播报 | 完成 | 会话台开关 + /api/tts |
| 页面令牌化 | 完成 | 五个页面 style 块硬编码色值 = 0 |
| LLM judge | 完成 | base/judge.py + CLI，强制 JSON |
| 真模型验证 | 完成 | 120 局 0 失败，2.54M tokens，$1.37 |
| 正式实验 | 完成 | N=20/条件，6 条件，结论见 docs/FINDINGS.md |

## 关键数字

```
主实验：120 局（3 档 rho × 沟通开关 × 20 seeds）
  沟通开 vs 关：三个 rho 下均更高（差值 0.03–0.13）
  基尼：rho=0.02 时 0.073–0.077，rho>=0.05 时 0.007–0.031
  崩溃：0 / 120（天花板效应，RQ 的崩溃支未检验）
规则怪谈：6 局，违规率 0，求助 0（条文明示 + 可检查时模型很守规矩）
成本：2.54M tokens，约 1.37 USD
```

## 测试

```
python -m unittest discover -s tests
# Ran 282 tests — OK
```

## 复现三步

```bash
python scripts/probe_gateway.py
python scripts/run_experiment.py --plan main --seeds 1-20 --seats 6 --concurrency 3 \
    --models gpt-6-luna,gpt-5-6-terra,gpt-6-1-sol,gpt-6-sol,gpt-6-astra,claude-haiku-5-5 \
    --price-in 0.5 --price-out 1.5
python scripts/fill_experiment.py --batches 批次1,批次2
```

## 已知限制

1. 天花板效应：模型过于自律，崩溃从未发生；用 --plan main_hard（12 轮、上限 15）才能压出崩溃；
2. 模型组固定为 6 个（gpt 系列 + claude-haiku），换组结论可能变；
3. 合作率口径与 rho 机械相关，需与"绝对取用量"并看；
4. 成本是估算值（网关不一定回 usage）。