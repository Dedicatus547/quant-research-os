# Host-mediated 组件来源采用说明 v2

当前状态：`ACCEPTED_COMPONENT_V2_ENGINEERING / LOCAL_RELEASE_REGISTERED`（2026-10-10）。
来源组合已由[HM09 独立复审](../reviews/hm09-component-v2-final-review.md)接受，
[接受 JSON](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json)
SHA256 为 `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec`。
HM10 操作文档及 [HM11 本地发布登记](../releases/hm-mvp-component-v2-freeze-marker.md)已完成。

接受限于版本化 component-v2 工程组合范围；原 C11 PASS 按原 tuple 和采用范围保留，
当前候选五项原谓词 PASS、局部 Q08 与 runtime 绑定分别列明。
原 v1 契约、冻结记录、验收谓词和 selected 七项 NOT_EVALUATED 保持原字节。
两项科学 execution 均 SOFT_REJECT，原 ValidationReport 均 SUCCEEDED/REJECT。
重流程、既有 C15 源码冻结和四项已保存 PASS 均复用；正式业务调用额度8/8、诊断2次，
全部业务 CLI10/10余额0，不由本说明增加授权。

以下方案和执行章节保留各阶段历史，包括当时的 NOT_QUALIFIED/pending；
其待 HM09/HM10/HM11 状态由上述新记录更新。最初说明的原字节另存于
[原始采用说明](../../artifacts/hosted-evidence/recovery-continue01/hm-component-adoption-v2-origin-01.md)，
SHA256 `70af01babb1377eb35fb50b2fec901a88d44ee6dc07667751221b9eef914e957`。

## C15 当前实际来源与 runtime 适配（2026-10-10）

后面的候选章节保留各阶段事实。当前 C15 live、source export、两个独立 REEXECUTE、
parent RECEIPT_REUSE、comparison 与五类 tamper 均已实际完成；live/replay 外层原 guard
均实际退出0并完成清理。两份业务 execution 均为 SOFT_REJECT，科学结论保持原样。
正式模型额度8/8、独立诊断2、全部业务CLI10/10；没有新增模型调用或自动重试。

首次 source-view-01 验证实际退出1/fullcleanup，只有 HostedQualificationError 类型记录，
没有保存 selected/composition 结论。原 runtime 读取器只扫描 `manifest.json`，实际 native
ValidationReport 文件为 `report.json`；这是有限原件和源码的静态路径推导，未捕获原异常正文。
旧失败、旧 helper04/wrapper02、旧 view01 与全部成功业务原件保留。

仅新增管理 helper05/wrapper03 与 source-view-plan/v3；C15 源码及 B/D/I 均不变。
该管理适配从完整两份原 AutonomousExecutionReceipt 推导两份 native ValidationReport，
分别检查 typed report content hash、原文件字节SHA/size、原库存与 receipt 身份。
实际 Q11 根、case 与完整库存不变；独立 `runtime-only/Q11/live` 通过原 inode 的只读文件挂载
将原 report 字节提供为 `manifest.json`，仅供未修改的 `verify_runtime_binding` 使用。
别名集合必须与完整原 receipt 引用集合相等，不能筛选任意报告；没有改写、规范化或新造报告。
runtime-only 库存和来源文件同时进入原 typed manager export，验证时重新推导并核对来源。
该透明路径适配属于待 HM09 审阅的 component-v2 管理语义，不宣称 v1 原 bundle 验证了新 tuple。

prepare02 已实际0/fullcleanup；新 plan SHA256
`4aff12c9764b7497306d4e3d771ca0f272a498ebfac657a50bb7ca8b95acfd1e`，
5819来源记录/62只读挂载、物理大树复制0。原 Q01/Q07/Q09/Q10/Q11 调用不变，
各自返回的 canonical gate 立即保存。verify02 已启动；最终结果及 fresh HM09 尚待，
当前状态仍 NOT_QUALIFIED。旧 CI1909、106、原七门/native 和4.79GB sealed bundle全部复用。

后继实际结果：verify02 的1GiB全卷变动估算被原监管以
STORAGE_ESTIMATE_EXCEEDED 终止，actual-15/fullcleanup，原四份 Q01/Q07/Q09/Q10
canonical PASS已保存。原失败保持，不声称该整作业通过；没有触发瞬态读数，不能确定具体原因。
continuation01 明确绑定原helper/plan/调用/失败guard/四checkpoint来源并复用这四项，
只调用Q11原谓词，后续原runtime/Q08局部来源库存/安装/baseline逻辑不变。
续做整项3GiB估算包含512MiB私有tmp、128MiBmetadata和2432MiB全卷变动余量，原监管不变。
continuation01 已实际0/fullcleanup，Q11 PASS；五项原结果齐备，47项源chain及当前stable库存
35131b13a8274c3da57effd2878a5d2171fb286859951defb2444151eaf66183已核对。
composition/v2 SHA256 0e8b4474c0f987fb929ff836c3fbeba7d8f598769df3e5d19114f6684c0fedf0
为 READY_FOR_INDEPENDENT_COMPONENT_V2_REVIEW，仍pending独立工程接受；精确输入见
[HM09 input](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-review-input-01.json)。

## 固定基线与候选

|绑定|C11 原证明来源|
|---|---|
|C|`8963936ecaa3efd934701b711f841f5c66f4915a`|
|B|`4c9eaec0053223e9165a4f628e3ffdc077eb491d03589e59dd33a580af6df89f`|
|D|`40c1f50974f7f5db08b723313d0b5b7ee967ed8d4038bac60bfa31c1d9dc468e`|
|I|`4afa924c4871b65e917958f94a4b215e231a72d7a5665a0ac91f954b192509e2`|
|CI 实际 0 guard|`b6623bbd2ed99e31350e380701d700322f54473e3abee6b0f78bbfae3882d9bf`|
|106 原 aggregate result|`a247f685d43b083b8b6e9f6011b0f89a80f5f566b5747192b9ab84a4fe2b82cc`|
|七门 sealed manifest|`89b0cbacf113963e264d27736db868e096b9f8ac50dd92d1fe981067f91c51e4`|
|原 verifier result|`930413bdfd622bd396fafdacffa9078fc9c604a331e3c93e9cf49147119f8edd`|
|原 native 实际 wait/exit 0|`ac66ee902a38dc49ffff7cbccf1703cab056316b295e7314f592d9efb2a098e2`|

原 CI 为 1909 通过、0 失败/错误/跳过，覆盖 85.15378763177915%。106 包含失败父批次
下的真实完成 prefix，不声称曾有一个完整 106 子进程退出 0。原七门 Q02/03/04/05/06/08/12
PASS、其余五门 NOT_EVALUATED；这些 PASS 始终属于原 tuple。

候选 A：`artifacts/hosted-evidence/cli01621-adoption-03`。
候选 C12 为 `0aa7321f50639131332e8702c1b2d8a4a6d88647`，小型源码冻结结果
`source/result.json` SHA256 `55e9d557f799e1c5990c7fc12f683532c26ba557dc2d952597e06642a5fdffd1`。
候选 wheel SHA256 `78fd71251d8b007e90f82b5782a36a12e3ae1a7de5969f0528e1aa776957fdf7`。
实际安装观察 I 为 `a9e900c4b28b5b087ad9b87a8c51d1833887d5a606f4f2f03b557d8b9ff9aa7a`，
`install-view/observation-result.json` SHA256
`c38effbdd23d9ec7862fcbdb01fe5b833ffa1e6fc7873fe984debbc3c7ef1e32`。
这份实际只读安装观察不是业务部署或模型交接。候选 B/D 须从实际发布的公开结果绑定；缺失时保留 pending。

CLI 0.162.1 固定 binary SHA256
`628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1`。
源码差异清单 SHA256 `62a96fc74af04032b9ef0bbb3adce37bca2f5d8149770ce7a3ad51f52d68ebb4`：
174 Python 文件中 171 字节不变、3 改变、无增删。改变的是 contracts/hosted_deployment.py、
infrastructure/hosted_launcher.py、infrastructure/hosted_service.py；wheel 的 RECORD 随之改变。
这证明字节差异范围，不证明传递依赖或运行行为等价。

## 采用范围与未完成证明

1. 直接引用原 CI、106、原 sealed 七门/native 及其源索引；不复制整个 bundle，不改写原 evidence。
   原数据、科学对象、Qlib 派生缓存、依赖和未变安装文件按原哈希只读复用。
2. 候选追加 CLI/version、三文件、extraction rule、configuration/runtime policy 及 B/D/I 的实际派生绑定。
   configuration 默认 extraction v2 与 profile 默认 CLI 0.162.1 会改变序列化哈希；service 的 v2
   启动/输出来源复核也改变。因此原 Q02–Q06 可作为原核心场景证明采用，不能重标为候选实际执行。
   Q06 原子部署父子还绑定相同 CLI/I/config/rule；不能将旧 child 改称新 parent 的 child。
3. 候选仍需已有机制产生实际 service restart、projection/只读 mount/CLI identity 和安全来源证明，
   以及新版 scanner/extractor 的必要局部来源证明。只采用已发布的实际事实，不由差异清单推出 PASS；
   不以此自动追加完整 CI/106 或新测试清单。
4. 成功正式 live、其真实 proposal 的 source export、parent RECEIPT_REUSE、两个独立 REEXECUTE、
   comparison/tamper 与完整业务分母仍未完成。沿既有执行 API，不造 proposal，不吞错误、不刷新旧 TTL。
   新提案的双根执行是 Q10 原要求的未完成工作，不是重跑旧 106。
5. 原 Q08.checked 包含原 manager/evidence 库存。新材料放独立候选/管理根；不要向基线 evidence
   发布新 export。候选 Q08 必须绑定候选实际库存，不能沿用旧库存 hash。

## 最小 assembly 路线

先用 [管理 helper](../../artifacts/hosted-evidence/recovery-continue01/prepare-cli01621-component-adoption-01.py)
生成独占的 `hosted-component-adoption-management/v2` 记录：固定 baseline/candidate tuple、
原公开 proof 路径和字节 hash、delta 清单、实际安装观察、缺失来源及授权余额。
helper 只核对公开 metadata 的内容哈希、来源字段和 schema 版本；不运行 verifier/test/service/model，
不读取认证或 raw 输出，不产生门结论。B/D 尚未发布也可保存 truthful pending 记录；后继使用新记录文件。

随后将候选真实 live/replay/security/local 原件追加到独立来源索引。最终 composition 索引必须分别列出：
`baseline_tuple`、`candidate_tuple`、每门的 `originating_tuple + original_proof_refs + adopted_scope`、
delta inventory、候选实际原件、失败历史、限制和独立 composition 审阅引用。
原 sealed bundle 保持原名/manifest/result；不重新 publish_manager_export，不将旧 PASS 换成新 D。

当前 `HostedQualificationManifest/v1` 与 `verify_manager_export` 是单 tuple；原 verify_bundle
比较所有重新得到的 canonical result 与保存 bytes。该 API 原样保留用于其原 bundle。
新的跨组件 full12 不能伪装为 v1 验证已接受；必须明确 composition 版本及采用范围，并由最终 HM09
独立审阅其新增语义。原契约第 6–7 行要求语义变更新版本与独立审阅；本说明尚未满足该接受要求。
新 composition 不应重执行已完成的原七门/native；核对它们的原封存身份及完成来源，候选新增范围另列。
v1 没有 delta 接口只意味着不能直接重标 PASS，不能据此默认安排全量重跑。

## 授权和额度不自动增加

原用户批准07绑定原精确 C11/B/D/I 和 campaign，新增最多 2 次 CLI capture；已消耗其中 1 次，
还剩 1 次。加此前旧失败，实际正式 capture 共 2 次、原累计上限 3 次。两次独立固定 JSON 诊断另计，
不是正式业务 proposal；HTTP 请求数仍 UNKNOWN。旧过期 pending、失败 proposal 来源都保留。

候选 spec 的 `max_requests=2` 只是运行容量，不是新授予 2 次模型调用。原 tuple 剩余 1 次不能自动
迁移或刷新为候选 2 次；记录需明确用户已授权的采用范围/是否包含候选 tuple 及实际可用余额。
若明确采用剩余额度，候选最多使用该剩余 1 次，不能承诺两轮完整 live。需要额外额度时应说明具体
差额和新 tuple；同一已授权范围不重复请求。此说明和 helper 都不授予或消费额度。

原动态 Context 外传范围保持：未来第二 Context 可含结果/validation/proposal/failure 正文，
不能以 fixture 的 0 items/704B 当作未来正文承诺。request 1MiB、prompt 1052672B、stdout+diagnostic
合计 1MiB、proposal 262144B、每 capture 900s、实际 issue 起 TTL 3600s、reissue=false 均不扩大。
最终独立 HM09 未接受前，整体始终 `NOT_QUALIFIED`。

## 后继执行附录：候选局部原谓词与 component-v2 full12

用户已经批准材料09。公开批准记录
`artifacts/hosted-evidence/recovery-continue01/cli01621-user-live-approval-01.json`
SHA256 `785d74938cd942a63defc359a83a463ef570e4280f6ee5453c25d4d80337fb2c`，
将候选 tuple 绑定为 C12 / B `48ecbd334d458d95ad6c1776c2c437756cdee7a203fcab3654f0b9f79a04421d` /
D `2a15ae3a7a19c3bdbb2c00ea65f4eca4e5774ee1bf81ce552be5311ecc0e1d62` / 上文候选 I。
批准只补足 1 次正式额度：保留原正式 2 次，候选最多 2 次，总正式上限 4；加诊断 2 次，
所有 model CLI invocations 上限 6，HTTP UNKNOWN。这是本附录记录的实际后继授权，
前文原批准07剩余1次的事实保持历史，不重置旧计数。本附录不宣称 live/replay 已完成。

[最小管理 helper](../../artifacts/hosted-evidence/recovery-continue01/assemble-cli01621-component-full12-01.py)
准备了两阶段入口，当前仅准备、未执行：

1. `prepare` 在候选真实 live/replay 已退出0且 wait/namespace/cleanup 已观察后，
   读取显式 adoption/批准/完成引用，生成 `source-view-plan.json`。它使用原 typed
   `publish_manager_export` 保存有限的候选来源表；只写 inventory sidecars、索引和空挂点。
   不发布完整 I/inputs 副本，不复制 authority/case 大树，也不触碰旧 sealed bundle。
   选择 Q01 before/after、Q07 live、Q09 parent RECEIPT_REUSE、Q10 root-a/root-b、Q11 live，
   并映射 Q09 五类原 tamper、真实 installed probe、runtime fingerprint 和候选公开 evidence。
2. root 以 plan 中各个 `{source,target,source_dev,source_ino}` 建立 `--ro-bind source target`，
   保持候选 config/install/inputs/provenance 的既有只读安装 view、offline network 和既有监督。
   每个空挂点只有实际映射到原 source inode 后才可用于验证；它本身不是原件或证据。
3. `verify --plan-hash ACTUAL_SHA` 必须由固定 `/install/python-seeded` 在原 source-only
   初始化、隔离/hash-seed/cache 策略内执行。入口先调用原 `verify_manager_export` 绑定当前
   source bytes/安装来源，随后仅调用原 `verify_case` 的 Q01/07/09/10/11；前后使用原 loaded-install
   谓词。原 source API 对 I/provenance 做核对，但不要求把它们物理复制进候选来源 view。
   helper 的 metadata 参数适配器仅提供该来源 API 所需字段，不发布伪造 v1 qualification manifest。
4. Q08 保留原 tuple 的完整 PASS；候选局部调用原 `verify_original_live_source`，核对当前 trusted
   capture/request/projection/config/executable/raw-output 提案来源链，并绑定稳定的当前 evidence
   inventory。这项范围是 `SOURCE_CHAIN_AND_CURRENT_INVENTORY_ONLY`，不是候选原 v1 Q08 全 PASS；
   不重捕获旧 Q08 场景、不改原负例谓词、不跳过或删掉 CLI error events。
5. 输出 `candidate-selected-verifier-result.json`（仅五门候选实际结果，其余 NOT_EVALUATED）
   与 `component-full12-result.json`（十二范围来源组合）。任何候选 FAIL/NOT_EVALUATED 或来源异常
   都保留实际失败，进程返回1；只有五门实际 PASS 及局部来源核对完成才记录
   `READY_FOR_INDEPENDENT_COMPONENT_V2_REVIEW`。它仍为 NOT_QUALIFIED，绝不宣称 v1 全12 PASS。

最终十二范围为：原 C11 Q02/03/04/05/06/12 原证明；候选 Q01/07/09/10/11 实际原谓词结果；
Q08 原全门证明加候选局部实际来源。原 CI/106/七门/native 仅按原封存哈希引用，
不调用旧 verify_staging/verify_bundle，不重跑科学或模型执行。读取原 saved result/native exit 元数据
用于核对来源，不等于再次执行原 verifier。所有原失败通过基线索引保留；后继完成/失败另有显式引用。
新独立 HM09 须审阅这一版本化采用范围、三文件变化及实际候选材料，而非误读为全新 D 的旧门 PASS。
当独立 review 明确接受 component-v2 composition 时，可解除该 review pending 并限定接受范围；
helper 不自行作 HM09 接受决定，也不将该 pending 描述成永远无法取得资格。

具体 `prepare` 输入包括 `--adoption-record/--adoption-hash`、真实 `--live-exit/--live-exit-hash`、
`--replay-exit/--replay-exit-hash`，以及 manager 下原 `--restart-source`、`--before-source`、
`--after-source`、`--runtime-source`。未来 actual hash 未发布前不能填写伪值或执行。
root 仍使用现有 storage supervisor 的实际 forecast、双卷余量、有限等待及 kernel cleanup；
本 helper 不自建执行引擎或新的开发门。

## C15 实际后继范围（2026-10-10）

上文 C12 三文件及原授权07/09是历史来源。C15 当前来源见
[组件记录](../../artifacts/hosted-evidence/cli01621-canonical-adoption-01/component-adoption-record-01.json)，
SHA256 `8cfee581ab9edd33a50f0079dc87248793584a799a24e67cb4ee41b6e2df73b6`，
沿 C14→C13→C12→C11 原证明链。实际 C15/B/D/I 均已在只读安装及业务 view 中观察；
原件和新实际来源分别保留，原 C11 PASS 始终属于 C11 tuple。

[C11→C15 字节差异清单](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-source-delta-inventory-01.json)
SHA256 `a1c6601dddef1dc948fb1217fa64649be546f787d1a45167684a96e92b7bc515`：
174 个 Python 文件中4 changed/170 same，无增删。四文件为 contracts/hosted_deployment.py、
infrastructure/hosted_launcher.py、infrastructure/hosted_service.py、application/autonomous.py。
autonomous.py 的新增差异仅在 host-mediated 请求生成处补齐 proposal JSON schema 的 object required、
移除 default 注释；C14/C15 后继仅给 launcher prompt 补候选 content_hash 映射和 canonical JSON 说明。
原接收、proposal 合同、DQ 分母、科学执行及五项 case 验证规则保持。
差异清单证明字节范围；实际后继原件及采用范围仍须最终 fresh HM09 审阅。
原说明7315B/hash `70af01babb1377eb35fb50b2fec901a88d44ee6dc07667751221b9eef914e957`
保存在 recovery-continue01/hm-component-adoption-v2-origin-01.md，既有 origin refs 沿用该原字节。

用户已实际批准[材料12](../../artifacts/hosted-evidence/recovery-continue01/live-approval-preparation-12.md)，
[实际授权记录](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-user-live-approval-01.json)
SHA256 `501cc51a0c1b3b7e15d95d0e7fd075077b975d6d67fa7362bfa6346f1d04a603`。
原正式已用6保留，累计上限8，C15最多2次；两原CLI均actual0/CAPTURED/transport ACCEPTED，
正式8/8余0、独立诊断2、全部CLI10/10，HTTP UNKNOWN。此前观察到第一项COMPLETED/SETTLED、
第二项STARTED，是当时的阶段事实；当前两项均实际完成，live状态COMPLETED。
[完成摘要](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-live-completion-summary-01.json)
SHA256 `4ffe0b8ac87fb61d9db2bfb121097e611551cd2eb8edb1272fe5e1ba3de16578`，绑定原guard退出
`fc86529eb114e6108dcaa844294f0dab2821b55e8a234baf9b483f4cf0e5b5c6`：actual0、wait/namespace退出/cleanup均true。
两份original execution receipt分别4089B/hash
`269908db535e48ee872cbbab61a412424a30b687eb4f08fb20ad073ccb84676e`、4088B/hash
`6955b7564611c4f53483d6fda8da29428c8cb2c28ccc9438aeb68f02f3ca4a1e`，均绑定C15，
outcome=SOFT_REJECT、execution_requested=true、compute_seconds=18；两原报告的runtime hash均为
`66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`。自然拒绝未被改写为研究PASS，
live完成也不自行授予工程资格。

C15后继仅metadata绑定：replay wrapper04/hash
`a0d821779b7d35d4b3af87106eb1283572cdb34004044792d7bc44a24c92fc71`，
full12 helper04/hash `5b9b198f3edaf4d66e073647a59afe7a58e6f0d3b2a35b4d2998b4029bc52e83`，
source-view wrapper02/hash `527653d249bfdd61209308288cd1a0faf88813d347fcfa91aff7d3105e6df558`。
上述入口在初次准备时均未执行；当前live/export已实际0，双根回放原入口仍在执行，
整体replay收尾、原五项谓词与当前局部Q08来源核对、fresh HM09及HM11仍pending。
原CI/106/七门/native/4.79GB bundle继续直接复用，不重导或重新封存；没有新增测试、开发门
或独立模型诊断。MVP仍NOT_QUALIFIED，尚无最终接受记录。
