# 仓库说明（2026-10-29）

## 本仓库是什么

Silicon Civilization：多智能体社会仿真基座 + 四个场景插件 + 实验装置。

- 规范位置：`D:\silicon-civilization`
- 远程：`git@github.com:xiaole1173/silicon-civilization.git`（分支 `main`）

## 不放在本仓库的东西

这个仓库**只放本项目**。以下内容曾被误混进来，现已清除，请勿再提交：

| 内容 | 处理 |
|---|---|
| `w05_3d_game/`、根目录 `index.html`（Week 05 3D 游戏） | 已移除；提交 `1893d5a` 已从 `main` 摘除 |
| `_w05_probe/`、`_pc*/`、`_pwt*/`（无头浏览器 profile） | 已移除并加入 `.gitignore` |
| `memory-pro/`（另一个项目的插件源码） | 不入库；它在 `D:\classvibecoding` 自己的仓库里 |
| `data/`（模型注册表，含 API Key） | 只在本机，`.gitignore` 已排除 |
| `runs/sessions/`（对局日志，137 MB） | 只在本机，`.gitignore` 已排除 |

## 2026-10-29 的清理记录

1. 远程 `main` 曾指向 `1893d5a feat: add Week 05 3D game`（它还把 README 整体替换成了游戏说明）；
2. 已把 `main` 重置到上一个干净提交 `71d67d8`，并 `git push --force`；
3. 远程现在只有一个干净的 `main`，历史保留 `71d67d8` 及之前的全部提交；
4. 清理前的完整引用备份（含 `1893d5a`）在本机：
   `D:\_gitbackup\silicon-refs-<时间戳>.git`（`git clone` 该裸库即可取回）；
5. 旧的 `D:\classvibecoding` 仓库远程已改名为 `legacy-silicon`，避免再从那里误推到本项目。

## 注意

`1893d5a` 这个对象在 GitHub 上可能仍以"不可达"状态存在一段时间（直到服务端 GC）。
若需要彻底删除，需在 GitHub 侧操作（删库重建或联系支持），仅靠 force push 无法抹除对象。