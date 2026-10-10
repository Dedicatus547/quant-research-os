# HM-MVP component-v2 本地发布登记

日期：2026-10-10（Asia/Singapore）。状态：`LOCAL_RELEASE_REGISTERED`；工程接受范围：
`ACCEPTED_COMPONENT_V2`。HM09、HM10、HM11 已完成。

本标记登记既有 C15 源码冻结、版本化工程接受记录及操作文档的精确身份。
资格身份采用 `SHA256_OF_VERSIONED_COMPONENT_V2_ENGINEERING_ACCEPTANCE`，
即下表 HM09 接受 JSON 的原始字节 SHA256；其范围不是新 tuple 的 v1 全12门 PASS。
源码来源为既有 C15 capsule，不以当前主工作区的未提交改动作为已接受源码。

## 身份绑定

| 对象 | 精确身份 |
|---|---|
| C15 commit | `a47e5a95db15f51e748c1343d96e124fc5b04d8c` |
| C15 tree | `11665c024f11952720051d13c3739bcaff083b64` |
| Business inputs（B） | `4d577d6521d7413202f41c1d8260b2bace2cebb82e0b33438220b6a004deb829` |
| Deployment profile（D） | `1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf` |
| Install inventory（I） | `cabd9c952f30dc92e689879087a0d564f5b40d9b210b08ad313aef76567d1624` |
| [HM09 接受记录](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json)，28639B | `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec` |
| [HM09 独立复审](../reviews/hm09-component-v2-final-review.md)，11226B | `ba4557868c2d1f98fc87a19564d666e85ca9673b3c0266327c66d881237f7a33` |
| [本地发布记录](../../artifacts/hosted-evidence/recovery-continue01/hm-mvp-component-v2-release-01.json)，18209B | `732b508bf5f4d4d860814acd976a62f95981943cff4e1fcbd6888b4f807ec7aa` |
| [component-v2 composition](../../artifacts/hosted-evidence/cli01621-canonical-adoption-01/component-full12/continuation-01/component-full12-result.json)，241845B | `0e8b4474c0f987fb929ff836c3fbeba7d8f598769df3e5d19114f6684c0fedf0` |
| [实际 continuation guard](../../artifacts/hosted-evidence/storage-control/run-1791628405055372513-413389/exit.json)，425B | `3afdfe0163e964dbd473c44db32a075e62e4713c8bb2dcbab5256f28f4d84275` |

源码 capsule：`artifacts/hosted-evidence/cli01621-canonical-adoption-01/source/workspace`。
发布记录逐项绑定实际调用、清理、原 checkpoint、来源清单及旧 C11 重流程证明。
本标记与导航是上述记录的后继登记，不作为发布 JSON 的自引用哈希输入。

## 仓库发布工件

以下仅有限公开管理记录随源码提交，保留原字节；其内部绝对路径仍表示原执行环境，
完整科学输入、运行原件和约4.79GB sealed bundle 按原路径留存，不复制到 Git。

- [工程接受 JSON 的原字节副本](hm-mvp-component-v2/engineering-acceptance.json)：
  SHA256 `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec`。
- [本地发布 JSON 的原字节副本](hm-mvp-component-v2/local-release.json)：
  SHA256 `732b508bf5f4d4d860814acd976a62f95981943cff4e1fcbd6888b4f807ec7aa`。
- [提交源码与原 C15 的有限字节及 Git mode 对照](hm-mvp-component-v2/repository-source-equivalence.json)：
  740个非文档文件逐项相同。排除 `docs/**`、根 AGENTS.md、README.md 和 PLAN.md 的后继说明。
  该对照不授予新提交整树运行资格；精确被接受的 C15 源码身份保持不变。

原 C15 Git 对象和父历史从既有源码 bundle 导入，未重新构建、冻结、运行或生成原重流程材料。

## 已完成的交接

- HM09：fresh `gpt-6.1-sol/high/fork_turns=none` 独立复审，attempt 1，
  `ACCEPT_COMPONENT_V2`，blockers 为空；模型 usage 未提供。
- HM10：`gpt-6-luna/medium` 完成下列三份操作文档，attempt 1，模型 usage 未提供。
- HM11：完成接受身份、C/B/D/I、来源与实际结果、文档哈希的本地登记。

| HM10 文档 | 字节数 | SHA256 |
|---|---:|---|
| [快速上手](../hosted/hm-mvp-quickstart.md) | 2660 | `f5c5c865ad48063b532f39d7de05556609c11e0f2ea45ce566a1f8f32771ac1c` |
| [故障恢复](../hosted/hm-mvp-recovery.md) | 3203 | `125184f29ababef0b335b0160049fad4fb2cd4c00ae8746c224b6938f86f6a13` |
| [Hosted 状态](../status/hosted.md) | 2907 | `4591398e445ad28e4f3d87aebbb8d78371177be21d9baca6db7f7255300a5930` |

## 接受范围与复用

当前候选 Q01/Q07/Q09/Q10/Q11 原谓词已有五项 PASS。
verify02 因 `STORAGE_ESTIMATE_EXCEEDED` 实际退出 -15 的失败原件保留；
其四份已保存的 canonical PASS 直接复用。continuation01 仅执行剩余 Q11 原谓词，
再完成 runtime、Q08 局部来源/库存、loaded-install 与 baseline 核对，实际退出0，
wait、namespace 退出及 cleanup 均已确认。

旧 C11 的 Q02/Q03/Q04/Q05/Q06/Q12 证明按原 tuple 和指定组件范围采用。
旧 Q08 fullgate 仍属于 C11；当前 Q08 为47项来源链与稳定库存核对，范围为
`SOURCE_CHAIN_AND_CURRENT_INVENTORY_ONLY`。原 selected verifier 的七项
`NOT_EVALUATED` 以及 composition 生成时的 pending 状态保持原字节；
新 HM09 接受记录只更新明确的 component-v2 工程范围。

原 CI1909、106项矩阵（73项执行及33项同提交已完成前缀）、原七门/native、
约4.79GB sealed bundle、实际 live/export/replay 全部复用。
HM10/HM11 未新增测试、开发门禁、业务模型调用或科学执行，也未重新冻结源码或复制大树。

## 运行与研究边界

固定 CLI `0.162.1`、请求 `gpt-6.1-sol/high` 的账户路线已完成两次实际 proposal capture。
provider `model_identifier` 未提供、HTTP 状态为 `UNKNOWN`；此记录只证明已发生的路线可用性。
campaign 已 `COMPLETED`，服务 namespace 已退出并清理。
正式调用8/8、独立诊断2次、全部业务 CLI10/10，余额0；不得续发该 campaign、重试、
reissue 或重置 TTL。后续运行依照快速上手和故障恢复中的授权及额度约束。

两项实际科学 execution 均为 `SOFT_REJECT`，原 ValidationReport 均为 `SUCCEEDED/REJECT`。
工程接受不改变这些结论，agent 复审不成为科学验证证据；盈利不是工程接受标准。
无限制 Live Agent、sealed confirmation、alpha/盈利、投资适用性、历史 vendor-vintage PIT
及无限制自主研究均不在本登记的资格范围。

旧失败、过期及待定记录保留；不可取得的01–36轮历史原件不重建。
FR-03 SDK 仍为 `NO_GO / THIN_MAINTENANCE`，P14d-C 仍为 `BLOCKED_UNIMPLEMENTED`；
既有 P14-DQ 与 ScriptedReplay 的原身份和状态沿用。
