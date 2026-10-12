# FR-03 Apps 隔离修复与资格结果

2026-10-12。确切组合 **SDK/runtime 0.162.1 + gpt-6.1-sol / medium**，
后继 `v4-env1-apps-isolated1`：**P10 9/9、P13 与离线 qualification PASS；FR-03 仍为 NO_GO**。
未创建 GO 接受记录，canonical pin 仍为 0.154.0；main 未集成、未部署。

| 阶段 | 结果 | 实际 usage（input/output） | SDK / launcher 耗时 |
| --- | --- | --- | --- |
| P10 | 9/9，不可变导出及冻结源码复验通过 | 17524 / 87 | 48.163 / 59.898 秒 |
| P13 | schema、引用、proposal authority、admission、PIT、双根离线产物通过 | 28231 / 521 | 53.581 / 65.161 秒 |

修复后共 **2 个真实模型 turn、零自动重试**；input45755/output608，cached input44800
已包含在 input 中。内置 account/read 两次，无新独立账户预检。底层 HTTP 请求数未暴露。
沿用900秒、input250000/output4096的验收阈值；这些阈值不是服务端费用硬上限。
新 proposal 的离线科学步骤耗时105.576秒，零模型调用。
此前后继的一次 P10 turn 和 P13 模型 turn 前拒绝保留于[原结果](fr03-gpt61-qualification-result.md)，
不并入本后继，也不改写成成功。

## 修复与证据

0.162.1 默认开启 Apps；本候选在 SDK-owned launch `features.apps=false` 与线程配置两处关闭，
并在 turn 前核对实际 `mcpServerStatus/list` 目录。P10 仅 dataset_describe，P13 仅
Evidence 的 evidence_get/evidence_cite，成功调用为 get/cite/cite；没有额外 server、错误或分页。
实际线程 model/effort、readOnly/network_access=false、approval=never 与请求一致。
P10 的同环境前后对照、四种 IP socket EPERM、完整命令生命周期和恢复顺序通过。
P13 shell关闭，完成 transcript 无 command 或 approval 事件。旧197工具拒绝证据没有删除。

候选 P13 使用明确 0.162.1/gpt61 profile、配置与 hash，复用现有 SDK adapter、normalizer、
executor/verifier。默认旧 profile、历史冻结输入与报告未静默改写。
normalizer v2 与实际 provider 通知、usage、程序身份、实际退出和清理记录均绑定。
新增 P13 离线步骤复用已验证 Qlib view，并及时保留每个已完成步骤的 checkpoint。
另修正类型注解、必要格式，以及已有 bootstrap 夹具漏填的 extraction_rule。

复用原 Evidence Store、冻结公告、benchmark/业务预期、immutable Parquet snapshot、
官方 Qlib0.9.7工具与健康检查、旧 Qlib view及原 offline engineering report；没有重新采集数据。
新 proposal 与原来不同，重新执行受影响的 admission、PIT、两根 feature/study/signal/backtest/
reconciliation，principal hashes 一致。旧科学结果没有替代新模型 P13。
历史 v1 P10/P13 离线复验通过；旧 P10 未绑定 MCP 实现与进程退出/stderr，原退出保持 unavailable。

重作业沿用原宿主 C 物理卷、VHD映射、32GiB/16GiB安全余量、64MiB scratch硬配额与独占租约。
模型阶段各256MiB、科学512MiB、完整CI2GiB、受影响原生复验1GiB完整增长预算，另留失败/收尾空间。
正式原件从启动就在持久目录；未用 WSL free 代替宿主容量，未删除唯一证据。

## 工程退出条件仍未满足

完整回归实际 **1940通过、30失败、5439.68秒**，原覆盖率76.43%，实际退出1及清理原样保留。
修复后52项局部复验通过；原生/Unix路径相关11项复验9通过、2失败，耗时810.73秒。
累计测量 **78.83163365365758%**（26020/31446 lines、6137/9346 branches），仍低于85%。
这是执行冻结 `7e3a4d77...` 的累计测量，在最后的文件归属修复之前，未宣称当前全库coverage PASS。
核验过原 C11 的1909项/85.15%原件及源差异；原组合保留，未缩小当前分母或把旧PASS改标。

两项剩余集成父失败均为原生 file closure：新增 `model-data-splits.json` 没有被归属。
已修复严格归属：要求审计 hash 同时存在于 execution result 与 receipt evidence，归属 canonical
字节；语义检查仍由既有 receipt verifier核对冻结输入、calendar/PIT与原生 source files。
保留副本的325个文件离线复验通过，非规范审计字节及无关新增文件仍被拒绝；
13项相关单测、受影响Ruff/format/Pyright通过。没有重算Qlib、修改原authority或放宽安全判据。
这项局部证明不把两份失败的集成父运行改标，也不证明尚未完成的其他场景。
此前87项受影响检查、全源码Ruff/653文件格式/Pyright通过，最后改动另作比例适当的检查。

最小后续是复用已完成结果与保留authority，仅补受影响/缺失的原生场景及当前85% coverage证明。
不需要因为总体commit改变重跑P10/P13或全部科学；任何真正影响其依赖的改动另行核对。
现有模型额度已用完，未默许第三次turn。逐条结论见[20项退出复核](../../artifacts/workstreams/fr03-apps-isolation-20261012/exit-review.json)。

## 原件入口与续接

- [不可变P10报告](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p10-01/bundles/sha256-a037501a0e1ee15ee1e4eb181ba318660c30cff761aeed1d08bad59efb162253/harness-spike-report.json)、[实际退出及清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p10-01/p10-supervisor-exit.json)。
- [不可变P13 Agent manifest](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/agent-runs/sha256-bebbf6b286af1b3df72eab789c98e1a09c01e6ca3f94fa52e811007b5af55c21/agent-run-manifest.json)、[实际退出及清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/p13-supervisor-exit.json)。
- [不可变P13离线资格报告](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/offline-qualification/sha256-00eb007683fea7f4e014dc244a379b99ee928faf3f33f935477016672762e7c2/qualification-report.json)、[科学退出及清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/offline-supervisor-exit.json)。
- [完整回归退出](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/regression-supervisor-exit-02.json)、[受影响原生复验退出](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/regression-repair-supervisor-exit-06.json)。
- [结果JSON](../../artifacts/workstreams/fr03-apps-isolation-20261012/result.json)、
  [可续接handoff](../../artifacts/workstreams/fr03-apps-isolation-20261012/handoff.json)、
  [严格文件归属与篡改拒绝](../../artifacts/workstreams/fr03-apps-isolation-20261012/closure-retained-repair-06/result.json)。

模型名称是可变alias；provider stream是SDK通知投影与选定RPC观察，不是独立raw wire。
网络证明限本环境的四种IP socket与read-only组合边界。没有通用网络安全、盈利能力、
新research campaign或P14d-C资格；P14d-C保持 BLOCKED_UNIMPLEMENTED。
