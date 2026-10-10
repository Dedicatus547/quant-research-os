# HM09 component-v2 独立最终工程审阅

结论：**ACCEPT_COMPONENT_V2**。没有阻塞项。本次接受固定 C15 的 `hosted-component-full12-composition/v2` 工程组合，解除该版本的 HM09 独立审阅 pending，允许后继 HM10 有界文档收尾及 HM11 本地 release identity 登记。HM10/HM11 尚未由本审阅执行。原 v1 契约、原记录的 `NOT_QUALIFIED`、原 selected result 的七项 `NOT_EVALUATED` 及全部历史失败仍按原字节保留；本接受不构成新 tuple 的 v1 全 12 门 PASS，也不构成科学验证或盈利结论。

审阅分配为 `gpt-6.1-sol/high/fork_turns=none/attempt=1`，实际 usage 不可观察。审阅从本任务固定 packet 开始，没有继承开发实现上下文；这是工程判断，科学 authority 仍是原 deterministic artifacts。

## 固定身份与读取范围

唯一输入 [packet](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-review-input-01.json)：12468B，SHA256 `fafd49bd974ac967fb6c3bf1751f27e6d39f7dae33d904672481018d966a8c0e`。

| 身份 | C15 接受对象 |
|---|---|
| C | `a47e5a95db15f51e748c1343d96e124fc5b04d8c` |
| tree | `11665c024f11952720051d13c3739bcaff083b64` |
| B | `4d577d6521d7413202f41c1d8260b2bace2cebb82e0b33438220b6a004deb829` |
| D | `1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf` |
| I | `cabd9c952f30dc92e689879087a0d564f5b40d9b210b08ad313aef76567d1624` |

核对 packet 的 21 个显式引用和其 [公开来源草稿](../../artifacts/hosted-evidence/recovery-continue01/hm09-public-source-refs-draft-01.json) 的 105 个引用，共 126 次有限文件 hash/size 核对（32716422B，含重复引用），无差异。草稿 51822B/SHA256 `2209475ec0050af3d0cd07e73db3356a15fd913dc347b1cf7edfd6192f0f1050` 仍是当时 pending 状态，后继完整事实来自本 packet 与 continuation 原件。另核对 continuation origin 的九个显式公开引用、两份原 receipt/report、两份监督保存 policy，以及下述有限源码。大 manifest 仅解析必要身份、gate 和引用字段，没有遍历或重新哈希 4.79GB bundle。

没有执行模型、科学流程、service、CI、test、replay、原 heavy 门或原 helper。没有读取认证、环境、raw CLI、log、trace 或 proc。没有修改源码、冻结契约或原 artifacts。

## 源码变化与组件采用依据

C15 capsule 的实际 HEAD/tree 与上述身份相符且工作树干净；主工作区不作为接受源码。该 capsule 只有 C14/C15 对象，缺 C11 Git 对象，因此使用 `git diff --no-index` 比较 [delta inventory](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-source-delta-inventory-01.json) 明确指定的原 C11 安装四文件与 C15 capsule 四文件。八份原文件各自 SHA256 已核对，delta inventory 为 37130B/SHA256 `a1c6601dddef1dc948fb1217fa64649be546f787d1a45167684a96e92b7bc515`。其 174 项索引记录 170 字节不变、四项变化、无增删；字节差异范围不证明传递行为等价。

| 四文件变化 | 静态判断与边界 |
|---|---|
| application/autonomous.py | 仅 host-mediated/v1 分支递归删除 schema default，并要求 object 全字段；原 proposal 接收及科学判据不被重写。schema/request identity 的变化由新 tuple 实际材料承担。 |
| contracts/hosted_deployment.py | 扩展 CLI 版本和 extraction v1/v2 解析，默认新版本；无 Qlib/Tushare/harness/LLM SDK 依赖加入。旧解析兼容不证明旧 runtime 可启动新 service。 |
| infrastructure/hosted_launcher.py | 只在 thread 已开始且 turn 尚未开始接受字段集合固定的 typed nonfatal error notification；它不能提供 proposal。tool/未知事件、重复 JSON key、非整数或负 usage 仍拒绝；cache_write_input_tokens 扩展也适用于原 usage 扫描分支。candidate map 和 canonical JSON 指令补充 prompt，实际 proposal 字节仍原样接收，未人工规范化。launcher 绑定配置/rule v2。 |
| infrastructure/hosted_service.py | bootstrap 明确要求 v2 与配置/rule 内容 hash，保留原安装和身份核对。 |

Q02/Q03/Q04/Q05/Q06/Q12 采用 C11 原 proof，保持原 originating tuple；没有称其为 C15 实际执行。原 C11 CI 为 1909 passed、无 failed/error/skipped，组合覆盖 `(25272+6068)/(28468+8336)=85.15378763177915%`。原 106 为 73 成功批次来源加 33 个同 C11 失败父 prefix，保留两个失败父及一个 interrupted 父，不声称一个 106 进程 exit0。七门原 PASS/native0 属于 C11，原 sealed manifest SHA256 `89b0cbacf113963e264d27736db868e096b9f8ac50dd92d1fe981067f91c51e4`、verifier `930413bdfd622bd396fafdacffa9078fc9c604a331e3c93e9cf49147119f8edd`、native exit `ac66ee902a38dc49ffff7cbccf1703cab056316b295e7314f592d9efb2a098e2` 已核对。采用 gate 的原 verdict/reason/checked hashes 与 C11 verifier 逐项一致。

C15 原 live 已 actual0/COMPLETED/fullcleanup；export0，两个独立 REEXECUTE 和 parent RECEIPT_REUSE 均 actual0/wait/worker-group absent。原 comparison `5ec7e2084203a4cbf9be03ce5e0db7e3c6f5e69a915dfcb5ab899aea3451dc48` 与五类 tamper `724912fa7410104a59191bad37fcf577d7297e0706b2c2a1be809341d56feb04` 均核对。这些实际材料及五个原谓词覆盖本版本新增工程路径，接受不依赖从未变代码推导新 tuple 全量等价。

## runtime 报告路径适配

原 `verify_runtime_binding` 仅扫描 `/manifest.json`，原 native ValidationReport 在 `/report.json`。helper05 和 resume 使用完整 Q11 inventory 下的两份 execution receipt 推导两份 report，要求 receipt 数、alias 数、不同 report 数均为 2，且引用集合恰等于全部原 report 路径。report typed identity 与原文件字节 SHA/size 是不同检查：typed identity 按 ValidationReport 排除 `report_hash/created_at/oos_access_event` 后的 canonical payload 计算，已独立核对。

| trial | report typed hash | 原 report 字节 SHA256 | bytes |
|---|---|---|---|
| 1 | `f1d7e034a337e958d2a5e341f801e0dd78944c71d73f1f29fde2521ae99942e6` | `2f5e1050ae2b7dbbd0bc2c9fbbf87bd876b20880f94df07a895117b8d62587d3` | 83696 |
| 2 | `58005f808bd6891b8488dfa1bdc6029dcee946503ab3942710ddeaf69ddb53e9` | `5f58004741381f18c7636e019061e8e3f4979a1d51b4e9e15d402c992af4da63` | 83691 |

两份 runtime_fingerprint 均为 `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`。原 receipt 字节 SHA 分别 `269908db535e48ee872cbbab61a412424a30b687eb4f08fb20ad073ccb84676e`/4089B、`6955b7564611c4f53483d6fda8da29428c8cb2c28ccc9438aeb68f02f3ca4a1e`/4088B，与各自 execution identity、C15 code_commit、trial ordinal 和 report ref 匹配。

runtime-only root 将完整两份原 report 的同 inode 只读别名暴露为 manifest.json，原 typed manager export `bcecd025d411dd437a6ee0cfb19e477ceed797df6a86d673e7b12739689b5dac` 绑定 source_path、字节 hash 和 size。plan v3 为 5819 文件/62只读 mount，SHA256 `4aff12c9764b7497306d4e3d771ca0f272a498ebfac657a50bb7ca8b95acfd1e`。静态代码在原 manager/source-view 验证后核对别名同 inode/RO和完整库存，再调用原 runtime 谓词；实际 Q11 root 和完整 inventory 不被替换。它是有界路径适配，没有补造报告或缩小实际 Q11 分母。原 verify01 actual1/type-only failure 保留；路径不匹配是静态推导，未称为捕获到的原异常正文。

## verify02 checkpoint 接续

原 verify02 actual -15/`STORAGE_ESTIMATE_EXCEEDED`/fullcleanup，guard `78ec8d0db9a09e07ec39de14224e42d2d7025b7571b2ca1408ff8e18c731322c`。触发瞬间空间读数没有保存，整卷 free delta 监管的瞬态原因不能确定。四份已写 canonical PASS 按各自固定 hash 复用：

| gate | checked hashes | 原 checkpoint SHA256 |
|---|---:|---|
| Q01 | 41 | `8ba3080030eafc8f267e602745f3bc0ba969d96c7391d8ce3ffce1c1f8830529` |
| Q07 | 42 | `02dc7896e3e0d4ef531075e037a92c348e848ee26f37f76755a3b452c3d2087d` |
| Q09 | 78 | `ec14f376456d0424243ffebf53fe99324d6ad7137cd1a1f8b9c80de886a15398` |
| Q10 | 140 | `d200fb4f94d361b3a7ff1478707033342ab88701d365aefb0d3fb4068e2e816b` |
| Q11 | 70 | `6e725769e03d5ef98ad6269b17e003d031f90c5f4f2901fafe0b0e41f3d0f381`（continuation 原谓词新执行） |

对 helper05→resume helper 及 wrapper03→resume wrapper 做只读差异审阅。resume 固定 pin 原 helper/wrapper、plan、prepare0、verify02 invocation/startup/namespace/prelaunch、原失败 guard/binding 及四份 checkpoint，保留中断 provenance。loaded source-only install 前后核对、相同 RO source set、manager export、runtime、Q08 当前库存、baseline 收尾逻辑沿原 helper；只有 Q11 调用原 verify_case，四份已完成 gate 不重跑。原 invocation 与 continuation 的实际 namespace hash 都按监督保存的 run/policy.json 三个 storage settings 重建匹配；没有执行 wrapper。

新 helper SHA256 `083b433d618b96fc2130ea570f8a75b792d62f2a8e46a5e3a0973be22937689f`，wrapper `bab00ff7d4de8649407d342a85c0fd1652d5112b9a065fd57556e5a5f8807be7`，origin `e989b0584f665f07e39b97c4a86dfc4bec9bb984ac6d5529efc8c0140342c470`。continuation guard `3afdfe0163e964dbd473c44db32a075e62e4713c8bb2dcbab5256f28f4d84275` 为 actual0/failure null/wait/namespace exit/cleanup all true，binding `303ac1d7e848b2c0bce3bf27e88224af3f4cc2a67d59db29bb823847fb427c87`。结果落盘证实后续收尾已完成，原 verify02 failure 不被改称成功。

## 接受范围与限制

[原 composition](../../artifacts/hosted-evidence/cli01621-canonical-adoption-01/component-full12/continuation-01/component-full12-result.json) 241845B/SHA256 `0e8b4474c0f987fb929ff836c3fbeba7d8f598769df3e5d19114f6684c0fedf0`，仍为 READY_FOR_INDEPENDENT_COMPONENT_V2_REVIEW/PENDING/NOT_QUALIFIED。五份 PASS 的 canonical bytes 与 [原 selected result](../../artifacts/hosted-evidence/cli01621-canonical-adoption-01/component-full12/continuation-01/candidate-selected-verifier-result.json) 27069B/SHA256 `e143c5d599a8d85f6e232238b7edfb6486ad668730ee83fd257069e655777a11` 和 composition 完全一致；selected 七项 NE 保留。

Q08 保留 C11 原完整 gate，新版本仅采用原 C15 47 项 live source chain 与 stable 当前 inventory `35131b13a8274c3da57effd2878a5d2171fb286859951defb2444151eaf66183`；47项 hash 全在源 plan 文件集内。这不是 C15 v1 full Q08 PASS。组件工程接受采用这些明确来源及上述有界适配；不将原重流程跨 tuple 重标。

原请求为 gpt-6.1-sol/high、CLI0.162.1/binary `628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1`，provider model identifier 未暴露，HTTP 数 UNKNOWN。正式8/8、诊断2、所有CLI10/10，余额0，没有重试/reissue/TTL重置授权。两份实际科学 execution 为 SOFT_REJECT，对应原 ValidationReport 为 SUCCEEDED/REJECT；不改科学结论，不授予因子/alpha/selection资格。原失败保留，pre-recovery01–36 原件不可用，历史完整性不被声称。

新 [工程接受记录](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json) 独立版本化登记本结论；原 pending/qualification 记录均不覆盖。HM10/HM11 可在此工程接受范围继续，未来完成事实须另行实际记录。
