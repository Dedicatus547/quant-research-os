# 有界反馈研究：主线集成与首次 STOP 范围

2026-10-18。结论：**适合合入本地主线作为已实现、已定向离线验证的后继能力；真实接受目前只覆盖首次 STOP 分支。**
本记录随主线合并提交，不授予完整自动研究、真实新 AST 科学闭环或 P14d-C 资格；`NOT_QUALIFIED` 保持不变。

## 提交与合并范围

- 原主线：`ec8087ecf17c60c42d1914a2899150fb3cbf4e54`。
- 工作区原计划及入口先独立提交：`bbaab3546bb18269372e26f32e87b242f88c3e42`；原文可从该提交读取。
- 原开发/真实运行提交：`5235445296207d29ec9513905d938f2ccae652f0`，分支 `work/bounded-adaptive-research-20261017`。
- 采用普通 merge 保留开发提交身份。合并过程中只补当前文档；生产源码、scripts、测试和依赖采用开发提交原字节。
- `.worktrees/dev-adaptive-research-20261017` 保持 `5235445` 与干净工作区；旧固定候选运行 worktree `29fef56` 不动。
- 本次只提交并合并本地 main，未推送、部署、升级环境、运行测试或启动新的模型/科学任务。

## 为什么可以合并

新能力由 `scripts/adaptive_research.py` 显式入口和后继契约启用。审阅覆盖父任务/SDK 预留、capture 与业务提交、
新候选准入及冻结、预算/取消/期限、科学 namespace 接线和只对账路径。
旧 Discovery 三方法、静态历史和 SDK 入口阻断保持原语义；未放宽科学门、秘密检查或冻结 normalizer。

对既有组件的生产改动限于：公开 singleton 准入/冻结入口、公开既有 SDK 观察保存函数，
以及默认关闭的 `retain_completed_outcome` 和仅补 receipt 方法。新方法复核完整原件及请求，不进入科学 pipeline。
因此可以集成开发成果，并继续把尚未实跑的生成/反馈分支标为待验证。

合并前核对 14 项源码依赖与开发冻结 checkpoint 相符；4 轮既有 JUnit 原件的 SHA256 均匹配，
共 69 次执行、61 个不同用例、所采用轮次失败/错误为 0。模拟涵盖新 AST/反馈、STOP、来源篡改、
父预算、取消/过期、UNKNOWN 不重发及完整结果补 receipt；不能代替真实新候选科学组合。
采用已有 Ruff/format 和 Pyright 原件；历史失败保留，不将旧轮次重标成合并提交新跑的测试。

原主线 `ec8087e` 的 [CI run 39041958415](https://github.com/Dedicatus547/quant-research-os/actions/runs/39041958415)
已读取到 `completed / success`，checkout 与原主线完全对应。该结果只覆盖原基线，新增提交/合并提交没有远端 CI 结果。
本次没有为文档整合或总体 commit 变化重跑全量 CI、资格矩阵或科学任务。

## 真实观察与未证明能力

固定 `5235445` 的新任务 `ce713513681cf19edbc63c881375b3e8e9229e3f2f148faa608fe438b5708d7f`
在首次真实 SDK 调用后返回 STOP。请求、provider 用户消息 echo、原始响应、事件链和独立进程退出对应。
程序按 `MODEL_STOP` 终止；SDK、operator、外层 observer 和 guard 均 exit0，namespace/cleanup 已观察。
controller 的 finally 记录不单独冒充父进程 waitpid。

实际为 1/2 次 SDK、0/2 新候选、0/2 科学，政策 units 消耗/占用均 0/36；没有本任务新的 Validation 或科学裁决。
模型根据提供的历史摘要建议停止，理由与所引原件相符；这不证明允许范围内所有假设都失败。
此次 76 份库存文件大小/哈希一致，事件引用和 SDK request/raw response 也经跨层核对。

仍待真实证明：新 AST → 准入 → 科学执行 → 本任务反馈 → 后继决策，以及反馈后修订分支。
长期可靠性、跨宿主安装、反馈因果改善、sealed confirmation 和历史 vendor-vintage PIT 不由这次停止证明。
完整自动研究目标保持“部分证明”；初次 STOP 是有效任务结果，不能强迫生成或追加调用来凑验收。

收尾首次审计 exit1 源于管理结果的 method-name map 被冻结 scanner 拒绝；改为 method/count 列表后第二次审计 exit0。
这是管理元数据整理，未改 runtime/scanner，未增加 SDK/科学调用；失败审计和先前库存均保留。

## 原件与下一步

以下以 `artifacts/bounded-adaptive-research-20261017/` 为根，原件保留在主仓持久目录，不纳入 Git。

| 原件 | SHA256 |
|---|---|
| [源码冻结 checkpoint](../../artifacts/bounded-adaptive-research-20261017/coord/ar2-ar5-source-checkpoint.json) | `ae82be5498715dffee6072ecb3419b8c7bea4b81848dee63cfa3254bd1bafe5a` |
| [离线采用结果](../../artifacts/bounded-adaptive-research-20261017/coord/final-verification.json) | `01f1b924aebc809411ba76406c056d6788bf9cab3bc912be911532d6069786e7` |
| [原运行包 manifest](../../artifacts/bounded-adaptive-research-20261017/package-01/release-manifest.json) | `06c8d36774cab2d0c6f8c2828ef79a625c7b31279264087b343e4c67b9c0d0e8` |
| [运行报告](../../artifacts/bounded-adaptive-research-20261017/authorized-run-01/report.md) | `e1bac7d5ebb2f38f46b2b839c020e1d4b12d0a1aba6ff71bbf1d753a81e2112c` |
| [机器结果](../../artifacts/bounded-adaptive-research-20261017/authorized-run-01/result.json) | `aebfca3544fd7bceb1c48cc9f03be039261245f76aee353f4f0cce6194e360a5` |
| [完整库存](../../artifacts/bounded-adaptive-research-20261017/authorized-run-01/evidence-inventory-completed.json) | `8b53c572850a99bba5cb16e2a8f07854026564a7ea7c333373795e8e56ac7d77` |
| [最终收尾](../../artifacts/bounded-adaptive-research-20261017/authorized-run-01/closeout.json) | `0afbde4c92979263f96c678ccb61f3c1b425eaafde33a00bca25f15fe674e6d0` |

原 [AR0–AR5 离线交付](bounded-adaptive-offline-2026-10-17.md)保留准备时点，“待授权”不覆盖之后的真实 STOP 记录。
原 `package-01` 已终态，剩余机会未使用且不自动续跑。下一任务需有明确研究理由、新输入/输出身份、具体预算与适用授权；
先采用已有证明，只补实际变化或缺失的依赖。操作入口见[使用手册](../guides/bounded-adaptive-research-v1.md)。
