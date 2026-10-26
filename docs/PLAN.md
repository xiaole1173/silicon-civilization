# 剩余任务执行计划

> 目标：把基座从"能看对局"推进到"能跑实验并产出结论"。
> 原则：**先有场景，再有数据，最后有结论**；每块完成即提交并更新任务进度。

## 任务拆分与依赖

| 编号 | 任务 | 依赖 | 产出 | 状态 |
|---|---|---|---|---|
| T1 | 公地困境插件 | — | `plugins/commons/`、`scenarios/commons.yaml` | 进行中 |
| T1b | 回放台 world 曲线 | T1 | `/api/replay/{id}/viz` 加 `world` 字段 + SVG 图 | 待办 |
| T2 | 并发调度 | — | `base/session.py` 并行提问（可配置并发数） | 待办 |
| T3 | 成本金额 + 报告图表 | T2 | `--price-in/--price-out`、REPORT 里出图 | 待办 |
| T4 | 合约 / 第三方调解 | T1 | `base/contracts.py` + 开关 | 待办 |
| T5 | 持久化续跑 + 批次 GUI | T1 | 会话状态落盘、`/api/batches`、页面入口 | 待办 |
| T6 | 吞警徽 / TTS / 规则怪谈 | — | 规则补齐 + 音频播报 + 新插件 | 待办 |
| T7 | 颜色收尾 + docs/README | — | 页面令牌化、文档刷新 | 待办 |
| T8 | LLM judge | T1 | `base/judge.py`（非参与者模型打分） | 待办 |
| T9 | 真模型批量验证 | T1、T2 | 小批次结果 + 成本/失败率 | 待办 |
| T10 | 正式实验 | T9 | 冻结清单 + N=20-30 + 结论文档 | 待办 |

## 关键设计约定

1. **玩法进插件，能力进基座**：资源池、指标、批量、清单、并发、持久化一律在 `base/`；插件只写"谁在什么时候做什么"。
2. **指标口径统一**：插件只声明 `metrics()`；通用统计走 `base.metrics`（基尼/合作率/CI/CSV）。
3. **可复现**：每批次写 manifest（条件哈希），同条件重跑自动续跑。
4. **可回放**：会话事件全部落 JSONL；`/api/replay` 提供归一化视图。
5. **消融开关在基座**：`communication`、`info_visibility`、`show_reputation`。

## 公地困境场景规格（T1）

- 参与者 6 人，8 轮；共享池初始 100，上限 100；
- 每轮：公开声明（可选）→ 取用（0..cap/4）→ 结算（按 ρ 恢复）→ 裁判播报；
- 参数：`regen_rate`（稀缺度旋钮）、`rounds`、`initial`、`per_round_max`；
- 终止：池子归零（崩溃）或轮次用尽；
- 指标：合作率（取用 ≤ 公平份额）、基尼、崩溃轮次、总提取、期末存量；
- 结论：`{"collapsed": bool, "survived_rounds": n, "final_stock": x}`。

## 验收口径（对应课程要求）

- focused RQ：稀缺度 ρ 如何影响合作率与崩溃概率；
- controlled experiments：沟通开/关、ρ 三档；
- repeated trials：每条件 N≥20；
- findings：REPORT.md 一句话结论 + 图表；
- 可见性：会话台实时观察 + 回放台复盘。