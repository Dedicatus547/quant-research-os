# FR-03 确切组合 GO 接受

2026-10-12：**SDK/runtime 0.162.1 + gpt-6.1-sol / medium**，后继
`v4-env1-apps-isolated1`，已满足原20项退出条件，在本工作线形成 **GO**。
[不可变接受记录](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/acceptance-record.json)、[逐条复核](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/exit-review.json)、
[简短续接交接](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/handoff.json)绑定原件及源码。
main 尚未集成、未部署；默认 canonical dependency pin 仍为0.154.0。
后继通过实际命名 profile 接入SDK adapter，
[资格绑定配置](../../configs/qualification/fr03-sdk-01621-gpt61-medium.json)固定目标与报告hash。

| 阶段 | 结果 | input / output | SDK / launcher耗时 |
| --- | --- | --- | --- |
| 新组合P10 | 9/9；身份、同环境控制、四项EPERM、生命周期、导出/复验通过 | 17524 / 87 | 48.163 / 59.898秒 |
| 新组合P13 | 精确MCP、schema/引用、proposal authority、admission/PIT、双根下游产物通过 | 28231 / 521 | 53.581 / 65.161秒 |

本后继共 **2个真实模型turn、零自动重试**，input45755/output608；cached44800已包含在input中。
本次剩余工程工作 **新增模型调用0次**。内置account/read两次，没有新独立预检；底层HTTP请求数未暴露。
沿用每次900秒、input250000/output4096验收阈值；这些数不是服务端费用硬上限。
新proposal的受影响离线步骤105.576秒，零模型调用。

## 完成的修复与工程证明

Apps在SDK-owned启动与线程配置两处关闭，turn前严格核对实际MCP目录。
P10仅dataset_describe；P13仅evidence_get/evidence_cite，实际调用get/cite/cite，
shell关闭、Agent网络关闭、无命令或审批事件。既有执行器、adapter、normalizer、verifier继续复用。

补齐原生 `model-data-splits.json` 的文件归属：审计hash必须同时出现在执行结果与receipt evidence中，
字节必须canonical；保留原语义/PIT/source检查。修正测试夹具的extraction_rule、
Unix短路径/MLflow目录环境，并修正新增checkpoint漏导入。新增149项离线回归全部通过，
涵盖持久预算、失败/恢复、来源替换、原生字节采用、未知费用与异常脱敏；合成SDK/transport不授予资格。

原完整父回归 **1940通过/30失败、5439.68秒、实际退出1** 原样保留。
1970个原节点按真实依赖增量核验：19项失败逐项补验通过，前9项受影响节点沿用已完成证明，
业务闭环完整测试通过，生命周期完成组合复验；没有把原失败父改标为PASS。
业务闭环所在双测试父为1通过/1失败、1484.80秒，失败原因是新增checkpoint漏导入。
后续生命周期父被2GiB存储增长守卫终止，实际退出-15且清理通过；五个完成checkpoint保留。
只读续接曾因新建临时Git提交改变绑定而被拒绝，失败亦保留。
最终复用原清洁provenance：旧五预算场景只读复验全部原负向断言，只执行两个未完成场景，
**续接测试通过、259.34秒、实际退出0，waitpid/namespace清理通过**。
原lifecycle前缀通过由冻结执行源码与其后已完成checkpoint证明；全部assert AST逐项、同序不变。
成功合成测试夹具按pytest原策略清理；资格bundle、JUnit、源码/覆盖率证明、退出与失败原件持久保留。

全库Ruff、663文件格式、Pyright均实际退出0。全 **192个源码文件** 精确组合覆盖率
**85.0220588235294%**（27904/31452 lines，6785/9348 branches），通过未放宽的85%门槛。
覆盖率仅采用源码字节完全相同的arc测量；改动的closure由新测量覆盖。
旧C11原始数据库与已绑定XML逐行、逐分支复现，158个相同文件贡献10个执行点；
其旧1909项测试父没有改标为当前接受。四舍五入显示85、实际低于85的中间测量没有被采用为GO。
[覆盖率来源与分母](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/coverage-adoption-final-36.json)、
[原失败逐项解除](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/regression-discharge-final-36.json)、
[当前实现源码清单](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/final-implementation-source.json)。
当前工程胶囊commit为 `ae99d787bda7c51efa71f454cee4ddabc4f6e718`；主worktree HEAD仍为 `ddfe674`。
实际P10/P13源码原件保留各自hash，当前关键代码AST相同；仅sdk_host错误字符串换行不同。

## 复用与限制

复用原冻结公告、Evidence Store、benchmark/业务预期、immutable Parquet snapshot、官方Qlib0.9.7
及已验证view，没有新采集。新proposal的admission/PIT与两个独立下游根已真实运行，principal hashes一致。
旧v1 P10/P13按原冻结来源离线复验；旧P10未记录进程退出/stderr/MCP实现，保持unavailable。
旧gpt-5.6-sol的9/9与先前197工具拒绝均保持原身份，不成为本模型的资格。

资源守卫仍核对宿主C物理卷/VHD、并发预留与原32GiB/16GiB安全余量，scratch硬配额64MiB。
存储失败只证明宿主/Linux总空闲量变化超过2GiB，保留目录约57MiB，未把全部增长归给本作业。
续接明确预留8GiB完整增长及外部宿主变化空间，等待既有独占租约释放；安全余量与守卫未降低。
模型alias可变；provider记录是SDK通知投影与选定RPC观察，并非独立raw wire。
GO范围仅此组合、冻结benchmark与环境，不能推导通用网络安全、盈利能力或P14d-C。
SDK discovery/campaign生成入口仍未获资格，其执行器token-limit metadata目前被scanner拒绝；
本次离线来源绑定测试不解除该入口的科学执行阻断。P14d-C继续 `BLOCKED_UNIMPLEMENTED`。

## 实际报告、退出与清理

- [P10不可变报告](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p10-01/bundles/sha256-a037501a0e1ee15ee1e4eb181ba318660c30cff761aeed1d08bad59efb162253/harness-spike-report.json)，[实际退出/清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p10-01/p10-supervisor-exit.json)。
- [P13不可变manifest](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/agent-runs/sha256-bebbf6b286af1b3df72eab789c98e1a09c01e6ca3f94fa52e811007b5af55c21/agent-run-manifest.json)，[实际退出/清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/p13-supervisor-exit.json)。
- [P13离线qualification](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/offline-qualification/sha256-00eb007683fea7f4e014dc244a379b99ee928faf3f33f935477016672762e7c2/qualification-report.json)，[科学退出/清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/offline-supervisor-exit.json)。
- [原生续接JUnit](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/completion-lifecycle-continuation-26/pytest.xml)，[实际退出/清理](/home/zjw/quant-research-os/artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/completion-lifecycle-continuation-supervisor-exit-26.json)。

[前次未完成记录](fr03-apps-isolation-result.md)继续作为历史保留，当前状态由本接受后继更新。
