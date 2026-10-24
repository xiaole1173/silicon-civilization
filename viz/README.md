# Silicon Civilization · 仿真回放台 v0

viz/index.html 是零依赖、零构建的单文件页面：双击即可在浏览器打开，内置一段手工构造的
7 轮示例 run（共享水源公地困境，含过度索取导致崩溃的完整叙事弧），用于先确认可视化样式。

## 页面四要素（对应赞助方 "actions and outcomes visible"）

1. 成员面板：每人持有量与贫富差距（基尼系数在右侧）
2. 动作流：结构化动作渲染为语义色条（索取红 / 贡献绿 / 提案蓝 / 接受青 / 沉默灰）；
   同轮动作同时提交、结算后整批揭示，避免动画顺序泄漏信息；rationale 默认折叠并标注「事后自述」
3. 公共池状态：余量、阈值线、T_survive
4. 趋势：公共池曲线（虚线=生存阈值）、基尼、本轮合作率

## 正式接入方式（事件溯源）

- Python runner 是唯一事实来源，输出 JSONL，每轮一条（或拆成 submit/resolve 多条事件）：
  round, regen, actions[{who,kind,amount,target,why}], pool_before, pool_after, holdings,
  gini, coop_rate, collapsed；另加 run 级 meta：scenario, condition, seed, model, prompt_version
- 指标（基尼/合作率/T_survive）只在 Python 计算，前端只显示
- 重放：读 JSONL；直播：FastAPI/SSE 推同一结构的事件，页面代码不变
- 多 run 对比（条件 A/B 曲线叠加）是答辩利器，建议作为 viz 的第二个页面

## 测试钩子（无动画确定性截图/检查）

- index.html?shot=N ：同步渲染前 N 轮（不经动画），用于无头截图和确定性检查
- index.html?auto=1 ：加载后自动播放
- 无头截图命令示例：msedge --headless=new --disable-gpu --window-size=1400,860 --screenshot=out.png 页面URL

## 已修复的坑（留作团队经验）

1. 往 SVG 里塞子元素不要用 innerHTML 拼字符串，必须 createElementNS，否则部分浏览器不渲染
2. 不要把局部变量命名为 history——window.history 是只读的，赋值无效且会报诡异错误（已改名 trail）
3. T_survive 是「首次跌破阈值的轮次」，必须单独记录，不能用当前轮次代替（会差一）

## 红线

- 不要把前端做成可以改参数影响实验的操作台（分析期污染风险）；参数从场景 YAML 进，不从前台进
- 不要显示未经后端确认的数字；时间戳、原始 action 保留在详情里供审计
