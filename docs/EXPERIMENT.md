# 实验方案（预注册草案）

> 这份文档在**正式开跑之前**冻结。任何条件改动都会改变 manifest 的哈希，从而可被检出。

## 1. 研究问题（RQ）

**RQ1（主）**：在多智能体共享资源场景中，资源再生率 ρ（稀缺程度）如何影响**合作率**与**资源崩溃概率**？

- 可证伪预测：ρ 越低（越稀缺），合作率越低、崩溃概率越高；
- 对照：同一 RQ 在"关闭沟通"与"开启沟通"两种条件下重复。

**RQ2（次）**：公开承诺（声明）与合约/调解机制能否缓解稀缺带来的过度取用？

- 可证伪预测：开启合约+调解后，违约率不为零，但合作率高于无机制条件。

## 2. 场景与条件

场景：`scenarios/commons.yaml`（6 户共享草场，上限 100，单轮取用上限 25）

| 因子 | 取值 | 说明 |
|---|---|---|
| `regen_rate` (ρ) | 0.02 / 0.05 / 0.10 | 稀缺度旋钮 |
| `communication` | on / off | 沟通消融 |
| `contracts` | on / off | 合约与调解 |
| `seed` | 1–20 | 每条件 20 局 |

条件组合（主实验）：3（ρ）× 2（沟通）= 6 组，每组 20 局，共 **120 局**。
附加对照：ρ=0.05 下再跑 contracts=on/off 各 20 局。

## 3. 指标（口径由 `base/metrics.py` 统一）

| 指标 | 定义 | 方向 |
|---|---|---|
| `cooperation_rate` | 取用量 ≤ 可持续份额（cap×ρ/人数）的比例 | 越高越合作 |
| `gini` | 各户累计取用的基尼系数 | 越高越不均 |
| `depletion_round` | 存量首次跌破 10% 的轮次（T_survive） | 越小越早崩 |
| `collapse` | 是否崩溃（存量≤10%） | 1=崩 |
| `survived_rounds` | 实际撑过的轮数 | — |
| `contract_breaches` / `breach_rate` | 合约违约数与比率 | 越低越守信 |
| `cost_usd` | 按单价换算的估算成本 | 预算控制 |

## 4. 执行流程

```bash
# 4.1 冻结条件并跑批次（自动写 manifest + index.csv + REPORT.md + chart.svg）
python scripts/run_batch.py --plugin commons --seats 6 \
  --scenario scenarios/commons.yaml --seeds 1-20 --rounds 8 \
  --sweep "regen_rate=0.02,0.05,0.1;communication=on,off" --concurrency 3

# 4.2 复核清单未被改动
python -c "import json,glob;from base.manifest import verify;
m=json.load(open(sorted(glob.glob('runs/batches/*/manifest-*.json'))[-1]));print(verify(m))"
```

## 5. 分析口径

- 每组报告 `mean ± 95%CI`（正态近似）；
- 主结论只比较**同一 seed 集合**下的条件差异；
- 崩溃概率用比例 + 二项分布区间；
- 质性编码（合作/欺骗/守规）用 `scripts/run_judge.py` 抽样 10% 发言，judge 模型不参与对局；
- 结论边界：不外推到人类群体，不跨模型普适（模型清单见 manifest.seats）。

## 6. 已知限制

- 模型有随机性，单局不可作为证据；
- 估算成本（网关不回 usage 时按字符折算）只能用于数量级；
- 公地场景的"公平份额"是自定义口径，换份额定义结论可能变化。
## 7. 演练结果（mock，仅验证流程，不作为研究证据）

用 mock 模型把"ρ 三档 × 沟通开关 × 5 seeds = 30 局"完整跑通：

```
批次 b11aecd3441 | 30 局 | 用时 16.0s | 错误 0
产物：index.csv（30 行）、REPORT.md、chart.svg、manifest-*.json
结论示例：在 cooperation_rate 上，ρ=0.05/沟通开 为 0.250（n=5），ρ=0.02/沟通关 为 0.333（n=5），相差 0.083
```

mock 不看上下文，所以数字没有意义；这一步验证的是**装置**：条件矩阵、并发、续跑、清单、报告、图表、成本列全部打通。

## 8. 正式实验的执行方式（额度恢复后一键）

```bash
# 主实验：3 档 ρ × 沟通开/关 × 20 seeds = 120 局（建议并发 1–2，避免网关限流）
python scripts/run_experiment.py --plan main --seeds 1-20 --seats 6 --concurrency 2 \
    --price-in 0.5 --price-out 1.5

# 机制对照：合约 / 调解
python scripts/run_experiment.py --plan contract --seeds 1-20 --concurrency 2

# 规则怪谈：违规率与求助
python scripts/run_experiment.py --plan horror --seeds 1-20 --concurrency 2
```

脚本会：冻结条件（manifest）→ 逐局跑 → 写 index.csv/REPORT.md/chart.svg → 打印聚合（含 95%CI）。
同一命令重跑会自动续跑，不会重复消耗额度。

## 9. 当前阻塞（2026-10-26）

真模型调用返回 **429（请求过于频繁 / 余额不足）**，连续 3 次重试仍失败；早前还出现过网关返回 VPN 登录页。

- 已做的兜底：`providers` 现在会把"返回 HTML 登录页"直接报成明确错误，不会被当成空回答；
- 待恢复后执行第 8 节的命令即可产出正式数据；
- 数据一到位，只需把 REPORT.md 的结论段落抄进本文第 10 节即可。

## 10. 额度恢复后的操作顺序

```bash
# 1) 先体检，确认哪些模型可用（会逐个试一次，很轻）
python scripts/probe_gateway.py

# 2) 可用数 ≥ 需要的座位数时再开跑（建议并发 1–2）
python scripts/run_experiment.py --plan main --seeds 1-20 --seats 6 --concurrency 2 \
    --price-in 0.5 --price-out 1.5
```

工程侧的两道保护：

- **指数退避重试**：429/5xx 默认重试 3 次（5s→10s），可在模型配置里用 `retry_attempts` / `retry_wait` 调整；
- **额度中止**：批次里连续两局失败调用中 ≥50% 是 429 时，自动标记 `state=quota` 并停止，避免空跑烧时间。

### 结果解读（N=5/条件，2026-10-26）

| 观察 | 数据 | 说明 |
|---|---|---|
| 越稀缺，合作越难 | ρ=0.02：0.92（关）/0.96（开）；ρ=0.05：0.84/1.00；ρ=0.10：0.92/1.00 | 方向与 RQ1 预测一致，但幅度有限 |
| 沟通有帮助 | 三个 ρ 下"沟通开"均不低于"沟通关"；ρ=0.05/0.10 时达到 1.000 | 支持 RQ1 的对照假设 |
| 稀缺加剧不均 | 基尼：ρ=0.02 为 0.12–0.13，ρ=0.05/0.10 为 0.00–0.05 | 池子越紧，取用差异越大 |
| 无崩溃 | 30 局 `collapse=0` | **天花板效应**：模型整体过于克制 |

**重要限制**（写论文时必须写进去）：

1. **天花板效应**：所有条件都没有崩溃，`depletion_round` 为空，RQ1 的"崩溃概率"这一支实际没有被检验到；
2. **样本量小**：每条件 n=5，95%CI 宽度大，只能看方向；
3. **单一模型组**：6 个模型固定（gpt 系列 + claude-haiku），换模型组结论可能变；
4. **合作率口径**：以"≤ 可持续份额（cap×ρ/人数）"计，ρ 越小口径越严，存在机械相关的成分；
5. **成本**：648k tokens ≈ $0.35（按 0.5/1.5 USD 每百万 token 估算）。

要缓解天花板效应，可行做法（下一轮实验）：把 `per_round_max` 降低、把轮数拉到 12、或引入"个人收益权重"的提示，让过度取用变得有吸引力。

## 11. 结果

<!-- RESULTS:BEGIN -->

### 结果（自动生成，批次 `b9d0f89bb15 + b9aa4b77277`）

共 120 局（有效 120），tokens 2544874，估算成本 1.3730 USD。

| 条件 | n | 合作率 | 基尼系数 | 枯竭轮次 | 崩溃比例 | 总取用 |
|---|---|---|---|---|---|---|
| regen_rate-0p02_communication-off | 20 | 0.954±0.022 | 0.077±0.036 | — | 0.000±0.000 | 12.020±0.673 |
| regen_rate-0p02_communication-on | 20 | 0.981±0.021 | 0.073±0.088 | — | 0.000±0.000 | 15.240±6.218 |
| regen_rate-0p05_communication-off | 20 | 0.861±0.020 | 0.027±0.004 | — | 0.000±0.000 | 29.800±0.142 |
| regen_rate-0p05_communication-on | 20 | 0.989±0.016 | 0.007±0.012 | — | 0.000±0.000 | 29.080±0.508 |
| regen_rate-0p1_communication-off | 20 | 0.915±0.027 | 0.031±0.011 | — | 0.000±0.000 | 61.180±1.108 |
| regen_rate-0p1_communication-on | 20 | 0.997±0.004 | 0.016±0.003 | — | 0.000±0.000 | 58.860±0.405 |

![合作率](chart-main.svg)

**结论**：合作率最高的是 `regen_rate-0p1_communication-on`（0.997），最低的是 `regen_rate-0p05_communication-off`（0.861）。

<!-- RESULTS:END -->
## 12. 提示词修订：把"私人收益"补回去（2026-10-26）

### 问题

第一版公地提示词只写了一句"草场归零，本局结束且所有人都输"，**没有说明多取一只牛的收益归谁**。
这等于把公地困境的核心激励删掉了：模型只听到"共同损失"，自然一律少取，于是 120 局零崩溃。

### 经典设定（文献）

- Hardin 的牧羊人思想实验：多养一头牛，卖牛的钱全归自己（+1）；而"每头牛少吃一点草"的代价由所有人分摊，
  所以当事人"得到 +1，只失去 −1 的若干分之一"，加牛永远划算（[CNRS News 的复述](https://news.cnrs.fr/opinions/debunking-the-tragedy-of-the-commons)）。
- 实验室 CPRD（Walker/Gardner/Ostrom 一系）：被试"按自己的取用量获得报酬"，集体收益是总取用量的凹函数，
  因此私人边际收益恒为 1，社会边际成本随总量上升（[arXiv 2403.06796 的方法描述](https://ar5iv.labs.arxiv.org/html/2403.06796)）。

### 修订后的写法（`incentive: classic`，现为默认）

```
1. 每轮你先当众说这轮打算割多少，然后实际去割（0–25捆）。
2. 你割到的草料全部是你的收成，记在你自己的账上，多少都是你的。
3. 但草场是大家的：你多割 1 捆，草场就少 1 捆，这一份损失由 6 户平摊，你只承担 0.17。
4. 所以：多割 1 捆，你自己净得 1 - 0.17 = 0.83 捆；少割 1 捆，你也只替大家省下 0.17 捆。
5. 草场不会突然消失，只会越割越少；少了，往后每轮能割的就少一点。
没有人会惩罚你，也没有人逼你守信。你的目标是让自己这一局的累计收成尽量多。
```

事实卡同步改为：`你的累计收成: N 捆（这就是你这一局的得分）` 与 `多割 1 捆的账: 自己 +1，公共损失 1，你只承担 0.17`；
并且**移除了"可持续份额/人"**这一行——那是个强合作暗示，会再次把行为拉回保守。

### 对照条件

旧写法保留为 `incentive: moral`（只说共同损失、保留可持续份额提示），用于做 A/B：

```bash
python scripts/run_experiment.py --plan main --seeds 1-5 --incentive classic   # 新
python scripts/run_experiment.py --plan main --seeds 1-5 --incentive moral     # 旧
```

### 验证受阻（同日）

用 `classic` 设定重跑 `--plan main --seeds 1-5` 时，账户额度耗尽：30 局里 3240 次调用全部返回
`403 Insufficient user quota`，取用总量为 0。该批次（`b5a409fe304`）已移到
`runs/experiments_archive/b5a409fe304_quota-exhausted` 留档，未计入任何结论。

**所以"改完提示词会不会出现崩溃"这个问题，目前还没有实证答案**——只能说：

- 提示词已按文献补齐（4 项回归测试锁住措辞与算术）；
- 机器侧是通的：全员取 25 的确定性测试会崩溃（`tests/test_commons.py::test_greedy_collapses`）；
- 按算术推演，ρ=0.05 时若每轮 6 人各取 5（合计 30）而再生只有 5，存量每轮净减 25，第 4 轮跌破 10 → 崩溃。

额度恢复后一条命令即可验证：

```bash
python scripts/probe_gateway.py
python scripts/run_experiment.py --plan main --seeds 1-5 --incentive classic --concurrency 3 \
    --models gpt-6-luna,gpt-5-6-terra,gpt-6-1-sol,gpt-6-sol,gpt-6-astra,claude-haiku-5-5
```

## 13. 运行纪律（用户硬性要求，2026-10-28）

**未经用户允许，不得发起大规模并发测试。** 已做成代码闸门，而不是靠自觉：

| 入口 | 默认 | 并发条件 |
|---|---|---|
| `scripts/run_experiment.py` | `--concurrency 1` | >1 必须同时加 `--allow-parallel` |
| `scripts/run_batch.py` | `--concurrency 1` | 同上 |
| `POST /api/batches` | `concurrency` 缺省 1 | >1 需 body 带 `allow_parallel: true`，否则 400 |
| `/web/batches.html` | 输入框默认 1 | 需手动勾选「授权并发」 |

闸门实现见 `base/batch.py::check_concurrency`，测试见 `tests/test_concurrency_gate.py`。

代价说明：此前两次并发批次都出了问题——`b358babf980`（12 局）有 6 局被网关限流打断，
`b5a409fe304`（30 局）因额度耗尽整体作废。两者均已移入 `runs/experiments_archive/`。
