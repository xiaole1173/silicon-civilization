# 项目状态（2026-10-26）

## 一句话

基座与实验装置全部完成并通过测试；**真模型数据待额度恢复**——这是唯一的外部阻塞。

## 完成情况

| 项 | 状态 | 证据 |
|---|---|---|
| 公地困境插件 | 完成 | `plugins/commons`，跑通：基尼 0.36 / 合作率 0.61 / 第 2 轮跌破警戒线 |
| world 可视化 | 完成 | 回放台资源曲线 + 10% 警戒线（`docs/ui-commons.png`） |
| 并发调度 | 完成 | 批次 3.3s→1.3s（4 局）；`ask_many` 同相位并行 + 按座位重排 |
| 成本与图表 | 完成 | `cost_usd` 列 + `chart.svg` + REPORT 成本小节 |
| 合约与调解 | 完成 | 三组对照：无契约/契约无调解/契约+调解，违约率 0.25，调解后合作率 0.42→0.25 |
| 持久化与续跑 | 完成 | 第 2 轮停 → 重启进程 → 恢复 paused → 续跑到结束（61 条消息） |
| 批次 GUI | 完成 | `web/batches.html`：表单/进度/表格/图表/报告（`docs/ui-batches.png`） |
| 吞警徽 | 完成 | 竞选期自爆 → `sheriff is None` + "警徽被吞" |
| 规则怪谈 | 完成 | `plugins/rules_horror`：违规率 0.5、求助 3 次、3 人存活 |
| TTS 播报 | 完成 | 会话台开关；`/api/tts` 返回 91KB WAV |
| 页面令牌化 | 完成 | 四个页面 style 块硬编码色值 = 0 |
| README / 截图 | 完成 | README 全量重写，docs 清理旧图 |
| LLM judge | 完成 | `base/judge.py` + `scripts/run_judge.py`，6 项测试 |
| 真模型批量验证 | **受阻** | 网关 429（ailab）/ 余额不足（modelscope） |
| 正式实验 N=20-30 | **受阻** | 脚本与文档就绪，待额度 |

## 测试

```
python -m unittest discover -s tests
# Ran 264 tests — OK
```

## 页面烟测

```
200 /web/chat.html     200 /web/models.html     200 /web/batches.html
200 /web/werewolf.html 200 /viz/index.html      200 /web/theme.css
200 /api/plugins       200 /api/models          200 /api/replay
200 /api/batches
```

插件：`commons`、`discussion`、`rules_horror`、`werewolf`

## 外部阻塞详情

| 端点 | 现象 | 时间 |
|---|---|---|
| `https://ailab.gbu.edu.cn/v1` | 先是返回 VPN 登录页（HTML），后持续 429「请求过于频繁」 | 2026-10-26 全程 |
| `https://api-inference.modelscope.cn/v1` | 429 `insufficient balance` | 2026-10-26 |

已投入的兜底：

- HTML 登录页 → 明确报错（不会被当成空回答污染指标）；
- 429/5xx → 指数退避重试 3 次（5s→10s，可配置）；
- 连续两局 429 占失败调用过半 → 批次自动 `aborted=quota`，不空跑。

## 恢复后的两步

```bash
python scripts/probe_gateway.py
python scripts/run_experiment.py --plan main --seeds 1-20 --seats 6 --concurrency 2
```

跑完把 `runs/experiments/<batch>/REPORT.md` 的结论段抄进 `docs/EXPERIMENT.md` 第 11 节。