# HM-MVP hosted 当前状态

当前记录接受 `hosted-component-full12-composition/v2` 的有限工程范围：`ACCEPT_COMPONENT_V2`，C15 commit `a47e5a95db15f51e748c1343d96e124fc5b04d8c`，绑定 B `4d577d6521d7413202f41c1d8260b2bace2cebb82e0b33438220b6a004deb829`、D `1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf`、I `cabd9c952f30dc92e689879087a0d564f5b40d9b210b08ad313aef76567d1624`。

权威记录是 [HM09 接受 JSON](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json)（SHA-256 `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec`）及[独立复审报告](../reviews/hm09-component-v2-final-review.md)（SHA-256 `ba4557868c2d1f98fc87a19564d666e85ca9673b3c0266327c66d881237f7a33`）。执行摘要见 [live completion summary](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-live-completion-summary-01.json)。

## 实际范围

- C15 仅有五项原谓词实际 PASS：Q01、Q07、Q09、Q10、Q11。旧 C11 tuple 的 Q02、Q03、Q04、Q05、Q06、Q12 证明经核对后复用；这不是新 tuple 的全 Q01–Q12 PASS。
- Q08 的 C15 范围为 47 项来源链与当前 inventory，不是原 v1 full Q08 gate PASS；旧 full-gate tuple 保持不变。
- 两份原 ValidationReport 均为 `SUCCEEDED / REJECT`，对应两次实际科学执行均为 `SOFT_REJECT`。不产生盈利、alpha、selection 或投资建议结论。
- CI 1909 tests、106 个场景的既有批次（73 新执行、33 同 commit 继承，非单一 106 场景进程）、七门/native 及 4.79 GB bundle 均沿用原证据，不由 component-v2 重新授予或扩张。
- runtime-only 只读别名适配保持原 report bytes、inode 与原 runtime predicate；实际 Q11 case/root/inventory 不变。

## 运行限制

Campaign 已 `COMPLETED`，正式模型额度 8/8、独立诊断 2 次、全部业务 CLI 10/10 已耗尽。请求模型为 `gpt-6.1-sol/high`，CLI 固定为 0.162.1；provider model identity 未暴露，HTTP 请求数 `UNKNOWN`。无自动 model retry/reissue/TTL reset。服务及 namespace 已清理，当前不提供可重启耗尽 campaign 的启动命令。

接受记录及复审报告没有改写旧失败或旧 `NOT_QUALIFIED` 原件。发布登记以独立 [HM-MVP release marker](../releases/hm-mvp-component-v2-freeze-marker.md) 为准；本状态页不授予或执行发布，也不含 release hash。

## 不变的上游边界

FR-03 SDK/runtime 已取得[确切组合 GO](fr03.md)，P14d-C 仍为 `BLOCKED_UNIMPLEMENTED`；component-v2 hosted 是单独登记的工程轨道。P14-DQ/ScriptedReplay 的既有状态不变。Agent review 不是科学证据；科学权威仍是原确定性不可变 artifact。没有历史 vendor-vintage PIT、盈利、alpha 或投资适用性声明。

操作入口见 [快速上手](../hosted/hm-mvp-quickstart.md) 与[故障恢复](../hosted/hm-mvp-recovery.md)。
