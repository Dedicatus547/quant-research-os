# HM-MVP 故障恢复与续接

## 保留既有失败和成功原件

先只读核对 [HM09 component-v2 接受记录](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json) 和 [独立复审报告](../reviews/hm09-component-v2-final-review.md)。保留每个失败 attempt、原始 report、receipt、checkpoint、guard 记录和原路径；不要覆盖、删除、改写或用摘要替代它们。旧原件仍是其原有 tuple 的历史证据，不因 component-v2 接受而被改标。

已绑定且可验证的结果应直接复用。确实无法复用时，先在新记录中说明缺失的身份、字节或绑定，以及为什么无法对账；不得凭猜测补写成功。原失败或退出不完整的执行保持其原有失败分类。未能确认业务执行结果时保持 `FAILED / NOT_EVALUATED`。

## 当前不重跑已耗尽 campaign

本次业务正式额度 8/8、独立诊断 2 次、业务 CLI 10/10 均已用完，campaign 为 `COMPLETED`，且运行环境已清理。不要重启、resume、重发模型请求、重置 TTL 或尝试恢复旧服务。接受记录没有授权新模型额度或新 campaign；未来请求沿既有授权与管理流程提出。

## 空间与清理故障

遇到卷余量、lease、namespace 清理或空间守卫异常时，停止新增作业并保留实际失败记录。不要删除证据来腾空间，不要启动完整 CI、矩阵、replay、export 或其他重流程，也不要把空间恢复本身解释为验收通过。

部署前后的空间检查遵循[存储恢复说明](hm-storage-recovery.md)：按共享物理卷统一计算、使用完整作业增量预算、保留失败留证空间，并满足 Linux 16 GiB、宿主卷 32 GiB 的保守余量及 private tmp 512 MiB 约束。这些是对应存储策略的容量约束，不是新模型额度或验收授权。全卷瞬时容量与 VHD 映射需由原流程实际核验；已接受的历史运行记录不能代替当前空间观测。

Windows VHD 操作只按[本机维护说明](hm-windows-vhd-maintenance.md)及其原有维护流程处理。维护、迁移或新请求均继续使用原有授权与记录方式；不得因本手册而新增绕过流程或把维护成功等同于业务资格。

## 证据与结论边界

- 只引用接受记录实际接受的 component-v2 tuple 和原件。
- Q08 当前范围不是 C15 v1 full-gate PASS；原 Q08 full-gate tuple 仍保持原样。
- C11 复用的 Q02/Q03/Q04/Q05/Q06/Q12 仍绑定原证明 tuple；不能据此声称新 tuple 的全矩阵 PASS。
- 两次科学结果为 `SOFT_REJECT`；没有盈利、alpha、selection 或投资适用性结论。
- 两份 ValidationReport 的状态/判定为 `SUCCEEDED / REJECT`；不要把工程接受、执行结果和 ValidationReport 判定合并成一个状态。
- provider model identity 未暴露且 HTTP 请求数为 `UNKNOWN`；不声称模型身份或未来账户持续可用。
- 此 component-v2 工程接受不改变 FR03 SDK `NO_GO / THIN_MAINTENANCE` 或 P14d-C `BLOCKED_UNIMPLEMENTED`。

发布登记以独立 [HM-MVP release marker](../releases/hm-mvp-component-v2-freeze-marker.md) 为准；本手册不授予或执行发布。
