# HM-MVP 实施进度

日期：2026-10-01。整体状态：`NOT_QUALIFIED`，尚未完成 MVP 验收。

HM-01/02 的基线、冻结契约和独立契约审查已保存；HM-03/04/05 的版本化交接、
持久化业务编排和受限 CLI 已实现并通过组件回归。HM-06 的冻结安装、namespace、
Unix channel、可信 CLI 捕获及管理 staging 已实现；已有实际启动和 Q07 原件诊断，
尚未完成完整正式资格。
HM-07 的只读 raw/protocol/business verifier、保存 SUBMIT 导入和 offline 管理入口已接入；
Q01–Q12 的来源谓词已有实现，完整原件矩阵与新 Q12 实现的冻结安装验收尚未通过。
HM-08 的实际模型驱动已接入受限 CLI，
正式 live、receipt reuse、两个全新 Qlib 根及完整 bundle 尚未执行。HM-09/10/11 未完成。

追加独立审查 [隔离启动与回放](../reviews/hm-replay-isolation-review.md) 批准有界实施澄清，
没有授予资格。普通 `python -I` 忽略 seed 环境的冲突已通过原生 CPython 初始化设施处理。
新部署对象使用 `hosted-deployment-profile/v2`，显式绑定 seed 初始化模式和 seed 0；
旧 v1 工件没有被补写或自动升级。新 binary、源码和编译记录进入完整只读安装 inventory。

2026-09-30 用户的开发模型分配覆盖：普通 Sol/Astra 工作由当前主 agent 执行；
必须独立的 subagent 工作使用 `gpt-6.1-sol`，effort 按任务确定；HM-10 保持
`gpt-6-luna/medium`。研究 host 冻结模型仍为 `gpt-6-sol/high`。本阶段主 agent usage
未提供，因此记录 `unavailable`；新增窄审为 `gpt-6.1-sol/high`，attempt 1、usage unavailable。

已执行的新增检查：99 项 hosted protocol/campaign/inputs/launcher/CLI/qualification/replay
组件测试通过；5 项真实 CPython seed/isolation 测试通过；ruff 和严格 pyright 检查通过。
双根组件测试使用明确的测试 receipt producer，不能替代 Qlib 或 live 资格。完整 CI 与
开发工作树全量回归得到 821 passed / coverage 80.48%，未达到 85% 门；这次回归窗口有
后续开发变化，因此也不能作为 exact-commit Q12 证据。需要补集成测试并在稳定提交重跑。
wheel 已可在本地现有缓存中离线构建，未修改依赖锁文件。

实际 staging attempt 01 保留在 `/tmp/hm-stage-796b55a-attempt01`：系统 gcc alias 的身份
读取拒绝导致失败；`5b31ec5` 固定系统二进制解析绑定后，attempt 02
`/tmp/hm-stage-5b31ec5-attempt02` 已冻结 profile 并启动服务、持久化请求，但受限 CLI
启动诊断污染 stdout，导致 JSON 解码失败。两个根均保留；没有模型调用、Q 门 PASS。
后继修复把 CLI import diagnostics 移到 stderr。追加实施审查记录
[三个 P1](../reviews/hm-replay-isolation-implementation-review.md)；后继实现补了恢复前
INTENT 校验、mixed Validation 结果处理和离线原 launcher 来源核验，仍需稳定提交验证。

禁止把本进度记录或组件测试视为 HM-09 接受记录。FR-03、P14d-C 和历史 P14-DQ 状态保留。

追加实际诊断：attempt 03–06 保留各自独立部署根；最新冻结安装来自 `9ae5537`。
[Q01/Q07 原件诊断](hm-q01-q07-diagnostic-attempt06.md) 经独立外部管理根核验，
两门诊断 `PASS`，其余十门 `NOT_EVALUATED`，整体仍为 `NOT_QUALIFIED`。
它没有运行模型或授权读取模型凭据，也不是最终 HM-09 接受记录。
新增 [Q07 窄审](../reviews/hm-q07-attempt06-review.md) 与
[请求导出窄审](../reviews/hm-request-export-review.md)；新版受限 `request-export`
只回传固定 guest 私有文件内的原始 canonical request，不增加 channel RPC 操作。
该修复已在新 attempt 07 的冻结安装中完成实际部署验证，旧 attempt 06 未被当作替代证据。

Q09/Q10 谓词已接入只读 verifier：核验原始管理端的 durable prelaunch、实际固定 argv、
返回码、完整输入及 before/after 清单，并重算 native 环境、零网络记录与执行调用分母。
receipt reuse 必须使用原始权威根且零 pipeline 调用；两个新根的初始内容必须精确等于
保存协议，不能含研究结果。comparison 单独保留完整 raw、principal、MLflow runtime
清单，以及逐文件 C11 投影。投影路径由每个已完成 execution 的对应 ValidationReport
和冻结 robustness case 推导；所有 manifest 的内容 hash 必须绑定目录，native signal、
backtest 和 reproduction sidecar 继续复用既有底层 verifier。未知文件没有时间豁免。

新增原生合成输入回归通过：一个原始 campaign 与两次独立 Qlib 重执行，22 个逐文件
C11 投影；五种 request/response/native receipt/result/event 单文件篡改均拒绝。
缺少 hash 目录前缀、错 candidate、错 cost variant 的有效 manifest 复制均不能获得投影；
合法 cost 路径内的错误 manifest hash 和破损 portfolio sidecar 也拒绝。
最后原生回归为 `1 passed / 125.27s`，相关单测为 `107 passed / 18.71s`，ruff、
format 和严格 pyright 通过。这些是合成输入测试，不能替代真实 model 来源或完整资格。
各次失败的开发测试日志保留；pytest 临时 fixture 根会自然轮换，不作为不可变资格证据。
[Q09/Q10 独立窄审](../reviews/hm-q09-q10-predicates-review.md) 由
`gpt-6.1-sol/high` 执行，attempt 1、usage unavailable，关闭三项 P1 后确认该窄范围
没有开放 P1；仍不授予总体资格。其独立原生回归 `1 passed / 123.51s`。

待完成：Q02–Q06、Q08、Q12 完整 scenario predicates 与原件验收矩阵；稳定提交的
禁网 CI coverage≥85%；真实 Q11、Q09 receipt reuse、Q10 两个新根
及完整 source-bound bundle；最后 HM-09 独立审查、Luna HM-10、HM-11 发布绑定。

attempt 07 原件位于 `/tmp/hm-stage-463ec6d-attempt07`，精确实现提交
`463ec6d50bfd4b262a46964920db1698cb9322ab`。新 profile
`0539efd3a44b42a33d13b454ee0e4ffd1c6e3f9f5855fdfbb03fec05f44db6dc`
的实际 `request-export` 得到原始完整 R，重复导出前后 20 文件 raw 清单一致；
随后 Q07 只新增管理端 sealed canary，旧文件字节没有变化。原件 Q01/Q07 诊断
manifest 为 `f4f1a35be3c4d4067053c9ad4a2f91660e61b85928f0976e1176ed0dbd2c78a4`，
result 为 `0dfd7782c07e7313e49e85f703d03a565c67abed46760a29608d6f5428fde71f`。
[独立安装及原件窄审](../reviews/hm-attempt07-export-review.md) 逐字节核对 139 个 wheel
项目成员、安装与 git object，重算 80 文件管理导出和诊断结果；正式 verifier 仍拒绝
diagnostic basename，整体 `NOT_QUALIFIED`。首次漏传解析器 `max_bytes` 的驱动失败及日志
保留；诊断 bundle 的失败尝试列表仍不完整，最终 bundle 必须补齐，不能把空列表当作无失败。

补充 Q05 组件回归：REGISTER、ISSUE、接受/拒绝 SUBMIT、CANCEL、EXPIRE 共 28 个
逐项 INTENT/publication/COMPLETE 窗口在 spawned 子进程中 `os._exit(73)`，每窗口由
新进程恢复，原时间/预算/bytes 不变，再启动新进程检查不重复发布。另有真实两进程 barrier
submit/submit 与 submit/cancel 竞争、稳定 lock inode、TTL 后 seen/未 seen bytes 区分。
首轮 `30 passed / 1 failed` 的失败来自测试将 JSON 的日期显示格式误认为 canonical bytes，
修正后该项独立复测 `1 passed / 30 deselected`。业务编排新增 research INITIAL 与
request checkpoint 实际退出恢复，整个组件文件 `25 passed / 313.50s`。

新增只读负例 accounting helper：重算五种独立错绑、expired/cancelled/conflict/seen bytes，
检查原 acceptance 保留、一个 charged reservation、完整 raw delta 精确等于 journal
publications、deterministic 文件完全一致，不信任自填 reason/PASS。51 项语义测试通过，
额外 protocol 文件、被改 business、错误 bytes/标签和多操作均拒绝。协议、helper 与管理
组件联合回归 `103 passed / 1 deselected`；kernel namespace 用例另行执行，未以 deselect
当作隔离通过。它尚未接入 Q03 的完整来源谓词，因此不能给 Q03 授予 PASS。

固定管理端 `hosted_negative_probe` 已实现，研究 RPC 不能指定它的程序、case 或 clock。
它在独立空权威根调用真实冻结 loader，使用明确标注的 `TRANSPORT_NEGATIVE_FIXTURE`，
阻断并记录 execution/Workflow/network，保留 before/after 与 seen/cancel 重复结果。
管理端先保存 durable prelaunch，再记录实际 bwrap/kernel 子进程、固定安装程序 hash、
返回码及安全 observation；失败原根不可重用。该入口仍需新 wheel/profile 实测和完整
Q03 来源核验，不能拿现有组件 fixture 冒充模型提案或正式负例执行。

后继实际 attempt 08：`/tmp/hm-stage-24904e9-attempt08`，B
`44a0efc86c63efd0f110e5c207a06ca4cf73d2019c7a2a01bce7b2331baec77c`，D
`c6a2f1fe222dfdb92c9d836700600d8ce715334be3076126cfc8019589d68b20`。
实际隔离检查通过，首个 negative worker 的主错绑提交已保存且独立核验 13 hashes：
before 20、after 24 文件，unique submissions 0→1；worker 最终退出 1、observation 缺失，
未给 Q03 授予 PASS。完整 prelaunch、kernel PID 链、失败 completion、partial roots
保留。干净进程 import blocker 定位到 application capability 导出间接触发顶层 Tushare
SDK 导入，离线 guard 因此拒绝；不会删模块或放宽 guard 来通过。
[管理端负例边界窄审](../reviews/hm-negative-boundary-review.md) 未见该范围权限 P1，
仍要求修复后新冻结实跑；审查为 `gpt-6.1-sol/high`、attempt 1、usage unavailable。

主工作树在 `24904e9` 保持不变并执行禁网全量 CI；后继修复在独立
`/tmp/hm-negative-followup-worktree`。Tushare SDK 仅在 acquisition constructor 的
`client is None` 分支导入，显式假值注入 client 不再意外触发 SDK。4 项干净进程
import-blocker/SDK stub 用例及既有 4 项采集 capability 回归 `8 passed / 15.24s`。
管理端补充 launch error/timeout 的安全 failed-attempt 记录，标明 `NOT_OBSERVED`，
不编造 return code/completion；加上实际退出失败与缺安全观测，总计 `4 passed / 5.10s`。
ruff 和严格 pyright 通过，尚需新 wheel/profile 实跑；Q03 的完整 source predicate 草稿
未发布或授予资格，仍需原件和负例验证。没有模型调用或模型凭据读取。

后继 `76939b8` actual attempt 09 的八个固定隔离负例均成功退出，逐项 transition
核验通过，live authority 的完整 raw inventory 保持不变。原根
`/tmp/hm-stage-76939b8-attempt09`，B
`1379e46a28b69081fa838eebfae97b428787b57e672e4869e490fbb97473be46`，D
`9fd916af5c9d007cd20134063fcfed5d17ddea8088a92937a803f626e028423e`。
这是明确标记的 transport fixture，仍无模型调用或模型凭据读取。

新增 Q03 来源谓词接入 verifier，要求全部八个独立 before/after 原根、原始管理端
prelaunch/completion/observation、固定 argv/安装程序、真实 kernel PID 链、namespace
与外部 UID/GID/capability 绑定；重算拒绝 accounting、完整 raw delta、seen/repeat/cancel。
17 项语义和只读拒绝测试通过；其中合成 kernel records 不能当作正式部署证明。
独立窄审发现直接调用谓词可能在缺失 exported specs 目录时触发 Store 创建目录；现先
验证 raw inventory 与 protocol integrity，再构造 Store，并验证缺失目录不被重建。

actual attempt 09 的完整 diagnostic 首次导出失败，manifest
`0a73c92b357de0b99d18c4c71711e5bfa718daebbb826930cbbf540b9fe776cb`，result
`e059f5f8112550e34dd3338f546395fcddefc4aa4d4074214417cc187e31a7a0`。
导出脚本把 before inventory sidecar 写入已观测的 channel，改变原始清单，来源谓词
正确拒绝。失败 bundle、sidecar、日志与原根保留；后继导出将只在管理 evidence 下保存
新 inventory，不放宽 exact channel 检查，不删除失败工件来制造成功。

精确 clean `24904e9` 的禁网 CI 已结束：`1022 passed / 344 warnings / 1739.63s`，
coverage `80.07%`，未达冻结 `85%`，Q12 仍未通过。保存日志
`/tmp/hm-ci-24904e9-pytest.txt` 与 XML `/tmp/hm-ci-24904e9-coverage.xml`。
覆盖率配置增加 multiprocessing 与 subprocess/_exit 采集，以计入实际执行过的
退出/恢复子进程；冻结 85% 门和 source 范围不变。实际 expired/seen fresh-process
覆盖率 smoke `1 passed / 30 deselected / 52.49s`，完整稳定提交 CI 尚待重跑。
manifest 的失败尝试引用补充严格 SHA-256 格式校验；完整失败 ledger 来源对账仍待完成。

`53f365a` 首次启用子进程覆盖率时产生 `.coverage.<host>.pid...`，既有 gitignore 只忽略
单文件 `.coverage`，因此 clean provenance 拒绝了尚未创建部署根的 attempt 10。
CI 已主动中止，partial 日志/coverage 保留，不能当作完成的 Q12。补充忽略标准
coverage 子进程缓存；后继全量 CI 使用 `/tmp` coverage data file，避免污染工作树。

实际 attempt 11 来自精确 clean `955b07f`，原根 `/tmp/hm-stage-955b07f-attempt11`，
B `e089b172f135f584f584b187f4cf86bae5ff29d794af58b83e9516778279b1f8`，D
`3775d679c75bfe43fa52fb0591149e2034fe29bcd5e4aea246316905a557cd57`。
八个 fixed worker 均成功退出；正确导出将新 inventory 只保存到 manager evidence，
所有观测 channel 与 before/after authority 完整保持不变。Q03 原件诊断 manifest
`55637d9b9046cfa3666894235130baf0cc7f610d1ca22b573cd5cac5fb3d5b87`，result
`88f4123cf137f96d518a50448c2b0645a29a450254821baf6628a2bb6d777019`：仅 Q03 PASS，
其余十一门 NOT_EVALUATED，整体 NOT_QUALIFIED。原件导出绑定 436 files。
[attempt 09 窄审](../reviews/hm-q03-origin-review-attempt09.md) 与
[attempt 11 窄审](../reviews/hm-q03-origin-review-attempt11.md) 均由
`gpt-6.1-sol/high`、attempt 1、usage unavailable 执行。后者独立核验 77 hashes、实际
PID/namespace、142 个 git/wheel/install/provenance 项目成员与完整 saved result，无新 P1。
诊断 manifest 的旧 `PREDICATE_POSTDATES_INSTALLED_COMMIT` limitation 是驱动遗留误写；
实际本轮安装已经包含 Q03 predicate。原件不覆盖修改，后继生成器需纠正此描述。
失败 attempt references 在该诊断仍为空，不能当作完整失败 ledger 或最终资格。

精确 `955b07f` 禁网全量 CI：`1049 passed / 344 warnings / 2470.79s`，coverage
`79.74%`，仍未达到冻结 85%。日志 `/tmp/hm-ci-955b07f-pytest.txt`、XML
`/tmp/hm-ci-955b07f-coverage.xml` 保留，Q12 不授 PASS。比较旧报告发现新 concurrency
配置只列 multiprocessing，导致 thread worker 的覆盖记录丢失；后继改为显式同时采集
thread/multiprocessing。该修复不降低门或排除源码，重要未覆盖路径仍需实际集成验证。

后继 Q04 实施在独立 `hm-admission-followup` 工作树：固定 guest 管理程序覆盖 byte cap、
invalid UTF-8、duplicate keys、unknown fields、非 canonical、unknown candidate 与
credential-like 合成 scanner 输入；无效原 bytes 不以 raw/base64/可逆形式导出。
六类 known-candidate schema/DSL/AST/parameter/fingerprint 错误复用原生业务对账，产生
一个 SCHEMA_INVALID trial，零 Qlib execution，保留 governor 原本的 validation segment
计费，不将 validation round 错当作物理执行次数。新原生集成回归 `1 passed / 152.33s`，
包含六个独立坏 proposal 根和原有两根 Qlib 重执行；联合组件 `136 passed / 1 deselected /
166.23s`。deselected 为 kernel 子进程测试，此次组件运行不当作隔离证明。
首次 native predicate 的 validation-round 假设和两次 runtime fixture 序列化错误均修复，
原失败日志保留，pytest 临时根不当作不可变资格 evidence。

新增完整 Q04 谓词要求全部十三个 before/after 原根，加上实际受限 host 的 path/projection、
symlink/hardlink/FIFO/并发替换 probes。增加的管理程序仍不在研究 RPC 内，入口仅固定
模块/finite case，不开放 arbitrary path/code/clock。尚需新 wheel/profile 的完整 Q04 实跑
与独立来源审查，不能以现有组件和旧安装授 Q04 PASS。

正式 verifier 补充运行时与自身安装绑定：outer runtime hash 必须等于原件 canonical
fingerprint，Q11 PASS 时所有已验证 native ValidationReport 必须绑定同一 runtime；冻结
文档读取原管理 provenance，使 wheel 中 verifier 可用；当前实际加载的项目模块（含
`-m` 的 __main__）源码须逐 bytes 对应冻结 install。各 6 项 runtime 和 source mismatch/
symlink/missing 模块测试通过。该正式路径仍需最终精确代码与完整 bundle，而 staging
diagnostic 继续整体 NOT_QUALIFIED。


### 2026-09-30：attempt12 原件与检查点修正（未授资格）

主 agent 按用户替代分工完成实施；必要独立审查使用 `gpt-6.1-sol / high`，
usage unavailable。HM10 的 `gpt-6-luna / medium` 仍等待 HM09 接受事实。

固定提交 `a6d1859398225f94cdc75c7f80adc73b1cc9b4ad` 的实际安装 attempt12 保留于
`/tmp/hm-stage-a6d1859-attempt12`：B
`826a9e0996c34046331b90b79e154659ba9b716bed3c92cf4b01daa8e68c3d08`、D
`bab80b80d65268a75e529fb5e2ea2d82f9877fc1957c5d9f7bfff6d4fccb5895`。
Q07 路径/符号链接/hardlink/FIFO/权限探针重算通过，Q03 八个原件调用完成，
Q04 七个 bounded 调用完成。`known_schema_invalid` 正确创建零 execution 的
SCHEMA_INVALID trial 后，管理 worker 取消下一请求并继续 resume，触发 P14-DQ
完整家族/receipt 前置拒绝；该调用 exit=1、observation=null，失败 root/prelaunch/
completion 完整保留，不能补写成功或授 Q04 PASS。

Q03 单项原件诊断 `/tmp/hm-q03-a6d1859-attempt12-diagnostic` 的 manifest
`d8fd68f4a49c7f63b997563367af22f88b853335a4b27e79607eab0f9bd8e48e`、result
`1d5804cad2e4efb572131d3bc3aa022961dc5b4755573caf9a233665c55cc778`、export
`e5bbff940548291c32589b6f2217cc59a64ea788bccfcb3bbbd5b82c13c5eae4`。
Q03 PASS，其余十一门 NOT_EVALUATED，整体 NOT_QUALIFIED；明确保留 a6 的两个
P1 与失败 ledger 不完整限制，inventory sidecar 只写 manager/evidence。

[独立窄审](../reviews/hm-q04-review-attempt12.md) 在 a6 复现两项 P1：磁盘 .py hash
不能证明执行时没有加载 stale .pyc；known-invalid helper 接受额外未知 authority 文件。
本轮修正 native PyConfig 的缓存读取前缀，在初始化前拒绝前缀污染，禁写 bytecode；
正式 verifier 仅接受固定 native、安装内 SourceFileLoader/spec/file 与不存在的私有
cache，并继续核验冻结库存。这改变 native/profile 身份，a6 旧原件不能替代新入口实测。
真实 CPython 同 mtime/size stale-cache 反例已显示普通入口读取旧值、native 入口读取冻结值。

Q04 改为原生 admission 检查点：复用只读 native orchestrator 构建及 prepare_trial/
finish_trial、governor、Ledger，核验 PREPARED→COMPLETED、SCHEMA_INVALID trial、
原预算、事件、STEP_COMPLETED 和下一 request 的原取消 receipt，不运行 finalization，
不伪造完整 campaign/P14c report。完整 raw 新增集合必须来自已核验协议 publications、
事件和 trial Ledger 节点；未知文件、额外 execution/manifest/sidecar 均拒绝。
生产 DQ 的完整终态要求保持原有严格语义。原生集成六类拒绝及额外文件反例通过，
并同时重跑现有两根 Qlib replay：1 passed / 232 warnings / 142.40s。

新增 Q08 固定管理 worker 与完整原件谓词，研究 RPC 不能选择该入口；覆盖自填
permission pass、usage、model/effort、snapshot、缺 transcript、fake attestation、
requested/observed 冲突、verdict、伪 SDK manifest、删限制和 TRUSTED 来源自填。
自填合法字段仅为 HOST_REPORTED；schema 不合法则 bounded 拒绝；原可信来源根与
冲突判定另行重算，缺原件不创建目录。所有响应和 CLI metadata 都为显式合成 fixture，
不属于 Q11 live 来源。Q08 组件及原件语义测试通过，实际安装运行与独立复核仍待完成。

Q12 仍未通过：上一固定提交 955b07f 全量禁网回归 1049 passed / 344 warnings /
2470.79s，coverage 79.74% < 85%。修正 thread/multiprocessing 采集配置不能当成
新覆盖率通过证明，未降门槛或排除新实现。HM07 剩余 Q02/Q05/Q06/Q08 实际原件、
新安装 Q04、Q12，以及 HM08–HM11 仍待完成；尚未读取真实模型认证或调用 provider。


补充验证：Q08/原 negative/cache 组合 141 passed / 89.34s；完整原件语义
37 passed / 134.73s。受影响 business/offline/manager/cache 组合 99 passed 后，两项
失败分别为 missing-source 期望异常类型写错（实际 fail-closed 的 ArtifactIntegrityError，
无目录创建）及沙箱 /proc 无法观察宿主 kernel PID。修正测试类型后单项
1 passed / 9.58s；管理环境 kernel 子进程测试 1 passed / 5.06s。该内核测试第一次
自动审批超时、未启动，按工具允许重试一次后通过，没有模型认证或网络调用。
新 checkpoint 对 attempt12 原 P14-DQ partial authority 的只读组件核验为26个hash，
`POSTDATES_INSTALLED_COMMIT / NOT_QUALIFIED`，不补写原失败 observation。

### 2026-09-30：attempt13 矩阵诊断与 publication 闭包后继修复

冻结提交 `abe5a9db5e542eb09caba9fc868c35fa56207e2a` 的实际安装保留于
`/tmp/hm-stage-abe5a9d-attempt13`。B 为
`9efc5b967bfdcac665d2efa99343036b24abe6f76a6084012c93a245403e8488`，D 为
`c62b2a0d8211c347893bb74a7c9a648446f625f521e8afff47fa8fc1062664f6`。
固定管理入口实际完成 Q03 八项、Q04 十三项、Q08 十一项，未调用模型或读取真实模型认证。
Q04 保留原生 admission checkpoint，没有再对不完整的 DQ 分母调用 finalization。
Q08 使用显式合成自报／冲突 metadata，不能当作 live 模型来源。

原件只读诊断 `/tmp/hm-q03-q04-q08-abe5a9d-attempt13-diagnostic` 得到 Q03/Q04/Q08
PASS，其余九门 NOT_EVALUATED，整体 NOT_QUALIFIED。manifest 为
`fd301c7c76b1fd4a648f1df32b942fc84542fe8b6530f25f21476acd38e8b3b2`，result 为
`073ebcb5ddc291f103b21eaa4d28c858804324c4a6f7c1905a9f8c92e15c7783`，manager export 为
`0e8da7dd3834f0b7b2c547dff95ea7d18d2e44ad82b1046d1494f9dbf8112a1b`。
该不可变诊断明确记载 abe 的 Q04 未引用 publication P1 和失败 attempt ledger 尚未完整，
不作为正式资格依据；没有用后继实现重写这轮安装的检查结果。

[abe 独立审查](../reviews/hm-q04-q08-corrective-review-abe5a9d.md) 确认 source-only
缓存入口 P1 窄实施关闭，但复现额外合法 BUSINESS journal pair 发布未引用 trial 仍被
Q04 helper 接受。后继实施绑定全部 INTENT 的精确 native schema 顺序，以及四段
BUSINESS 的原生 operation ID、时间、完整 publication tuple；budget operation ID 同样
复用应用层原生纯函数。新增发布额外 trial、重复 trial、重复 settlement、用 TERMINATE
包装 trial 均拒绝，普通未知文件反例仍拒绝；native Qlib 集成回归 1 passed / 145.24s。
[闭包独立复核](../reviews/hm-admission-journal-closure-review.md) 又重跑原反例，并保持
有效 journal chain 篡改 operation ID/time，均精确拒绝、读取前后 raw 不变，关闭该窄
实施 P1。它不追认 abe 安装或 attempt13，也不是最终 HM09 接受记录。

Q02 后继固定入口和只读谓词已接线，研究 RPC 不开放测试入口、root override 或 clock。
两种 fixture 为 accepted 和 rejected：两个真实 fork 进程经 pipe barrier 同时提交，后续
重复提交、两个分别重建 application 的进程 resume，再达到冻结 per-request cap=2、TTL
后重复原 bytes。accepted fixture 使用已知候选的 schema-invalid proposal，原生 admission
仅形成一个 trial/event/Ledger，execution/Workflow 调用为零；这不是成功执行或 Q11。
谓词要求原 manager kernel/安装/argv、六个独立 child 的实际退出与锁 inode、原始每阶段
全量清单、接受/拒绝同 receipt、重复 resume 原件不变、cap unique 拒绝收费且 seen 不收费。
功能输入的真实 fork/barrier 回归 2 passed / 16.79s，不授实际安装 Q02 资格；新 wheel/profile
实跑尚待完成。主 agent 完成普通实施，必要独立窄审仍为 gpt-6.1-sol/high、usage unavailable。

当前缺项仍包含实际新安装 Q02、完整 Q05/Q06、修复后的 Q04 新安装原件、Q12 coverage≥85%，
以及真实 Q11／Q09／Q10、完整失败记录、HM09、HM10（gpt-6-luna/medium）和 HM11。
HM-MVP 未完成；没有启动真实模型认证、provider 调用、正式发布或资格 tag。

### 2026-09-30：attempt14 Q02 原失败与私有 FD 生命周期修正

固定提交 `53bb908ed45388dee05e0df6952997246f9b9aca` 的实际新安装保留于
`/tmp/hm-stage-53bb908-attempt14`，B
`1454952928c31cc3426ae5e1ef4b675d4da0cf07f97a985967f9fd56b3a7a64d`，D
`d90c99e1d86415cb67aa2f72460c70bc0335bd775717200e32ead56c80d55763`。
Q07 原探针重算通过；Q02 accepted 用例的两个 barrier 子进程及第三次提交返回同一
ACCEPTED receipt，unique submission=1，但首次 resume 新子进程发生 OSError、exit=1，
manager observation=null。原始 manager completion、child failure、protocol、authority 和
channel inventory 保留；rejected 和后续 Q04 尚未启动，不能授 Q02 PASS。

[53bb 独立审查](../reviews/hm-q02-implementation-review-53bb908.md) 与原实际失败一致：
首次 bootstrap 的 consume_capability_fd 关闭 slot 100，已 unlink 的 staging 不能再 hydrate；
旧功能 factory 没有消费这个 FD，因而漏掉真实生命周期。后继管理 worker 在首次 hydrate
之后、bootstrap 之前按冻结 slots 用 pread33 检查精确32字节，只存 RAM；每次固定 bootstrap
前用 private memfd、位置0、CLOEXEC 重建同 slots。字节不进入 argv/env/disk/日志/证据，也
不扩大研究 RPC。新功能 factory 真正 consume/close FD；三个长度拒绝、错 slot 和重复
重建测试加入，合计7 passed / 16.81s，ruff/format/pyright/diff检查通过。

[FD 独立关闭审](../reviews/hm-q02-private-fd-corrective-review.md) 独立7测试通过，并只读
核对 actual14 的安装、provenance、原程序/kernel 身份、完整 inventories 与失败记录，
原件未变；只关闭后继实施 P1，不追认53bb或attempt14。必要审查模型为gpt-6.1-sol/high，
usage unavailable。后继 profile 的 Q02 实际矩阵和完整原件谓词仍待运行。


### 2026-10-01：attempt15 Q02 原件与 Q05 实施进展

冻结提交 `81638bbd1abb53123a3da30010c2b8064dbd0657` 的实际新安装保留于
`/tmp/hm-stage-81638bb-attempt15`，B
`eab6752191c6e297245980a5a0751069f8d4985852cf7573b44c659cc90df0b3`，D
`1c5041d717022ff0dce5976763fee552f7e711436a3a1fe3e7e40b74504d985f`。
accepted/rejected 两个 Q02 fixed workers 均 exit0；独立只读原件复算核对完整427个 source files、
六个实际子进程的 waitpid/退出/锁 inode/barrier/fresh bootstrap 与全部阶段清单，Q02核59hash。
[独立原件审查](../reviews/hm-q02-origin-review-attempt15.md) 未发现新 Q02 P1；PID、exit、
inode、阶段、原生 budget charge 和额外合法 BUSINESS trial 的复制件负例均拒绝、原件不变。
审查模型 gpt-6.1-sol/high，attempt1，usage unavailable。

只读诊断 `/tmp/hm-q02-81638bb-attempt15-diagnostic` manifest
`3253382d69dfbffb767abdec503a16abd23c5c3bf6121d523f15a5f846f9e079`，result
`2fb3559ebbafe5c99b736b3993390ce8e592cec06c9656a228fd2b92b9e97ffe`，manager export
`ec280ddc58c650097786c03922073c8ab4c6c94c6cc68bc33b01ef10304aa810`。
结果为 Q02 PASS、其余11门 NOT_EVALUATED、整体 NOT_QUALIFIED；没有授 Q11/HM09，
没有把 schema-invalid trial 当作成功执行。该安装单项 Q04 known-schema-invalid checkpoint
exit0，精确 installed-commit 只读 component 检查26hash；完整 Q04矩阵仍待新安装核验。

Q05 主 agent 开发中：atomic publication 增加显式 file fsync/link/unlink/directory fsync hook，
通过管理 bootstrap 向 store/application 接线，研究 CLI/RPC 不开放 hook。五项物理退出测试
通过（4.68s），hard-link中间态仍拒绝；协议/inputs回归76 passed（542.43s）。原生 step/budget
只读核验抽取为可复用函数，额外未引用 trial 明确拒绝；native Qlib回归1 passed（144.93s）。
固定管理 worker 已实现28协议发布及7schema-invalid业务窗口，三个不同子进程分别物理
exit73、fresh bootstrap恢复、再次fresh bootstrap；空before快照创建缺口已修正。
functional physical+Q02 FD回归43 passed（100.28s），不授实际部署 Q05。

执行窗口还在验证。native component 首轮 recovery 子进程 SIGSEGV（exit-11），原始退出记录
当时生成于 `/tmp/pytest-of-zjw/pytest-402/test_actual_qlib_receipts_even0/physical-native-faults/`，
不当作通过。该组件目录后来被 pytest 默认轮次保留策略清理，不能再宣称其原始退出文件仍保留；
失败日志 `/tmp/hm-q05-native-physical-execution-regression01.txt` 仍在。实际安装的失败 attempt
原件不在 pytest 临时目录，保持不变。该轮父进程已先运行 LightGBM，后继测试调整为训练前启动独立 worker子进程，
与实际管理 worker 的cold parent顺序一致；不以stub execution替代原生链。STARTED不确定、
原生receipt复用、事件/Ledger/report、fsync和损坏窗口完整source-bound谓词仍待补齐。
当前仍缺完整 Q05/Q06、Q12 coverage≥85%、真实Q11/Q09/Q10、失败attempt ledger、
HM09/HM10（gpt-6-luna/medium）/HM11；没有读取模型认证、调用provider或发布资格。

后续增加9个原生执行窗口，固定 durable 矩阵共44项。纯组件全矩阵与原生 Qlib 业务回归
第06轮 `1 passed / 232 warnings / 627.08s`，日志
`/tmp/hm-q05-native-durable-scenario-regression06.txt`；该次加载的是后继 P1 修复前代码。
独立 gpt-6.1-sol/high 窄审确认三个 P1：额外未归属文件未拒绝、合法返回状态未绑定原生事实、
校验缺失的 before/specs 时重建空目录。原审报告
`/tmp/hm-q05-durable-implementation-review.md`，hash
`18030eabd8d97e5b843b41812d65ae3eccdeb9745098bd5a5409ee3d74e30a87`。
尚未提交、构建或运行 attempt16；不能把上述组件通过当作完整 Q05。

主 agent 正在补精确原生文件引用闭包和只读状态投影。修复后原两项反例日志
`/tmp/hm-q05-core-closure-fixed01.log` 均为拒绝；缺目录反例日志
`/tmp/hm-q05-before-readonly-fixed01.log` 为拒绝，且不创建目录。后继44窗口回归第07轮
使用固定 `/tmp/hm-q05-native-closure-regression07-root` 保存组件证据，仍在运行；
三个 P1 的独立后继关闭审查尚未完成。

后继窄审继续发现合法孤立 REGISTER pair、trial 被自洽改类为 EXPERIMENT，以及取消被
自洽改写为提前 TTL 的 EXPIRED；每次都保留原报告，不把后继修复追认为原版本通过。
原审及前两后继报告已归档至 `docs/reviews/hm-q05-durable-*.md`。主 agent 后续补原生
protocol operation/publication tuple、固定场景次数/时钟、完整 Ledger 节点类型/时间/父引用/
authority/provenance，以及按固定 action/request/clock 构造取消/过期 receipt。

第07轮因 execution-result schema字面v1（原生v2）失败148.23s；第08轮因完整ValidationReport
mode=json与原生mode=python日期序列化差异失败147.98s；两次固定根和日志均保留。
原生 validation-event execution-ID路径、signal variant引用、selection closing前时间也已按
现存原生 verifier/selection handoff 核对。保留第08轮原根的两次执行完整文件归属核对PASS，
不把第08轮失败改写为通过。第09轮完整44物理窗口+原生业务回归
`1 passed / 232 warnings / 599.73s`，日志 `/tmp/hm-q05-native-closure-regression09.txt`，
原件 `/tmp/hm-q05-native-closure-regression09-root`；该轮加载的是TERMINATE补强前代码。
最新补强对上述44原根重新只读核验全部PASS，execute/Workflow/socket均阻断且调用为0，
全文件和目录清单前后不变，日志 `/tmp/hm-q05-all-retained-readonly-recheck01.txt`。

新增仓库自动反例（孤立REGISTER和合法错误Ledger类型）集中两物理窗口短跑PASS，日志
`/tmp/hm-q05-repository-closure-negatives02.txt`；管理短跑driver第01轮误用Store.root而失败，
根和日志保留，第02轮用真实_root属性，未修理第01轮根。
物理/fsync/私有FD三组回归48 passed（111.01s），日志
`/tmp/hm-q05-tuple-components05.txt`。ruff/format、pyright及diff-check通过；这不是
Q12 coverage≥85%的证明。

第三后继独立审查已归档：[精确修复边界](../reviews/hm-q05-durable-p1-closure-review03.md)，
hash `648c2556657f6a6dfb5cc78696c11c81a44e6e6744f7f02bf9a2dd52c0916f7f`。
审查文件写作期间曾观测到 hash `70871c25f574982cf6495cf556ba85ff46f8a735614f16c7317510482195340e`，
但复制前文件已经完成更新。机械核对确认首个里程碑提交实际归档的是最终648c255版本；
没有保留70871版本文件，不能宣称留存。后续误名为 `review03-draft.md` 的文件也是最终
648c255版本的重复副本，已撤去多余副本；git历史仍保留该次文档更正。
独立机械反例确认原三项P1及后续孤立REGISTER、合法错误Ledger分类、提前TTL终结均被拒绝，
保留原生两执行320文件的完整业务/引用闭包及目录/文件只读核验PASS；该窄审范围内没有
未关闭的已复现P1。没有将第07/08轮或任何历史失败改写为通过。TERMINATE语义负例同时
在固定场景core与底层native file closure被独立拒绝。protocol/inputs回归45 passed（27.45s），
日志 `/tmp/hm-q05-public-projections-regression02.txt`。
冻结这一durable子集实现用于新安装实际核验；完整fsync/损坏source-bound窗口、Q05正式
dispatch、Q06、Q12 coverage、真实Q11/Q09/Q10和HM09–11仍未完成，不授完整MVP资格。

### 2026-10-01：attempt16 安装矩阵与管理导出后继

新安装 attempt16 原件保留于 `/tmp/hm-stage-1122922-attempt16`，冻结源码提交
`1122922f6e67e3b1802010cf3b350764e898f99a`；B
`f40980818a44c6a34c89754a2d80e9bd6af816f4822c2a5d7303b7f7b6914b35`，D
`ab0c81b49db036b7afc73421fe243b9dbaf45d4d6541d2244eb663500d822653`。
wheel hash `a051e0242251afc3d8487e132cb4efdddae75e0c106a0afd6e5a0f508cdd2467`。
首次 offline build 因新 worktree 未发现 Python3.11 失败，原日志保留；后继显式指定已有
3.11 interpreter 构建成功，未用 `.venv` symlink。实际固定安装 Q07 原件已捕获并机械核验；
44项 durable Q05→Q04→Q02→Q03→Q08 串行管理捕获仍在运行，无真实模型交接或完整资格。

完整44项组件文件映射预检为9881项、canonical export7143305bytes；原管理 publisher 的
通用4MiB guard 无法承载该集合。后继 publisher 保留通用4MiB每次扫描上限，以完整typed
header/每条record扫描解码字段，并用重叠1MiB窗口覆盖全部raw bytes；aggregate明确限制
16MiB，与现存reader相同。4项测试通过（17.97s），pyright与ruff通过。
[独立窄审](../reviews/hm-large-manager-export-scanning-review.md)，hash
`c5de75fdf551f7e6af4250f1482a882c3cc60c2e0a494bd981dad801a9b97047`，
gpt-6.1-sol/high、attempt1、usage unavailable；独立4测试及短转义/最长Unicode跨窗口
canary均通过，无P1。该改动属于另行记录身份的后继管理诊断producer，未改变attempt16的
冻结源码/安装或原件，不能宣称1122922安装已包含它，不能据此授Q05或MVP资格。

### 2026-10-01：损坏矩阵与 fsync 恢复预检后继

新增五项固定管理损坏窗口：journal碎片、错误sequence、双pending、孤立artifact、
改写request bytes。损坏字节由完整原生起点推导；原始before保留，crash子进程exit73，
两次fresh生产bootstrap尝试均拒绝exit74，execute/Workflow/network为0。固定研究CLI/RPC
没有开放注入参数。44项durable矩阵独立保持；corruption subset不授完整Q05。
第一轮功能组件误把ISSUE预发布EXHAUSTED receipt当作已提交而失败，根与日志保留；
第02轮5 passed（12.87s）。原生业务输入集中检查第01轮第一个窗口通过后，测试残余44项
索引KeyError，原根保留；第02轮五窗口及error_type/waitpid/额外损坏负例通过。

[独立原审](../reviews/hm-q05-corruption-narrow-review.md)，hash
`6eb9a73384056fd7668e3ec0c4ad56f0e449dd0860c7612673b2f5edb1d79e99`，发现目录P1：
records两侧自比不能证明真实树不变；新增空目录或把records目录数组改成空仍被core接受。
后继增加descriptor-anchored、O_NOFOLLOW安全目录清单，包含空目录并拒绝symlink、special、
hardlink，有100000 entry cap；snapshot完整保留目录；worker/parser与core核对实际四阶段
目录和records，source wrapper核对exported与original目录。
[后继关闭审](../reviews/hm-q05-corruption-directory-closure-review.md)，hash
`2e10aa8287658a6557425c632e3c33d8e3819fa9dd367b10d37f829e0ed2732b`，原两个反例拒绝、
独立5原生输入窗口与6目录安全测试通过。主agent集中第04轮五窗口和五组负例通过，日志
`/tmp/hm-q05-corruption-native-components04.txt`；第03轮正例也通过，但没有后来新增的
两个目录负例，不追认。目录/物理/FD组件59 passed（126.91s）。共同origin及Q02/Q03/Q04/
Q08相关回归133 passed（208.27s）；初始误列不存在test文件的两次no-tests日志保留。

fsync物理控制复现spec file_fsynced后孤立`.publish-*`被fresh registration忽略的缺陷。
后继在spec flock内检查完整spec目录名字与原有单链接规则，拒绝未完成publication。
before-fix01为2 failed/2 passed；file_linked实际已拒绝，第二失败是test regex漏了
`one link`，不能称第二生产漏洞。spec/协议回归83 passed（569.58s）。
随后journal/object八个native store断点复现object file_fsynced后先补objects/COMPLETE、
再拒绝孤立临时文件的问题；原根与日志保留，1 failed/7 passed（6.96s）。后继恢复写前
先核对existing object格式、hash与全部journal publication bytes，合法pending缺项允许。
[独立fsync原审](../reviews/hm-q05-fsync-recovery-narrow-review.md)，hash
`b33257bfa13e52886f74b1019993eca78a1a2cb6566e6c3d5bb4075ead48d888`，确认spec缺陷关闭，
另复现旧COMPLETE object缺失时先补新SUBMIT对象与COMPLETE才拒绝。修复再要求existing
包含所有旧COMPLETE必需hash，共享pending hash也不能缺。
[后继关闭审](../reviews/hm-q05-fsync-required-complete-closure-review.md)，hash
`4cb05821dd29b4816e711a94bad28945ee155f8145a304c6580e7b27975d835b`，原反例提前拒绝，
文件/目录/inode/link/hash不变，publication/verify callbacks为0；独立19controls通过。
上述必要独立审查均gpt-6.1-sol/high、usage unavailable；原失败报告不改写。

最终19 fsync/缺旧完成对象控制通过（11.87s），其中共享hashBUSINESS例是store-only受控
负例，不冒充原生业务资格。最新目录/物理/FD/fsync兼容回归73 passed（134.14s），日志
`/tmp/hm-q05-required-complete-compatible01.txt`。最新partial预检下三物理原生窗口
（SUBMIT artifact2、business completed_intent、execution receipt）的真实Qlib/receipt复用
检查通过，日志`/tmp/hm-q05-required-complete-native-smoke01.txt`，固定原根保留。
完整49物理窗口+原生业务/C11回归1 passed/232 warnings（659.51s），日志
`/tmp/hm-q05-native-corruption-full-regression01.txt`；该进程加载的是spec修复后、partial
objects预检前store，不能当作后者完整49实跑。后继44旧组件原根只读复查全部通过，
日志`/tmp/hm-q05-all-retained-readonly-recheck02.txt`，执行/Workflow/network 0，文件目录不变。
ruff/format、pyright、diff-check通过；这些仍不是Q12 coverage≥85%的证明。

attempt16继续使用冻结1122922原安装捕获，不包含上述corruption、目录或fsync修复。
完整fsync forensic/source-bound原件、完整Q05正式dispatch、Q06最小预算/竞争矩阵、Q12、
真实Q11/Q09/Q10、失败attempt ledger与HM09–11仍待完成。没有模型认证/provider调用。

### 2026-10-01：Q06 有界 DQ 停止与原生 plan 归属后继

精确 P14DQ_REPORT_ONLY profile 下，CANCELLED/EXPIRED/EXHAUSTED 且 trials 未覆盖完整
候选分母时，现在保存独立 hosted accounting report：FAILED / NOT_EVALUATED、无 selection
hash、完整未尝试候选和预算/事件/Ledger 引用，增加明确的
`P14DQ_INCOMPLETE_DENOMINATOR_SELECTION_NOT_PERFORMED` limitation。完整分母仍调用原
DQ preselection/原生 receipts 门；没有 catch 后降级、P14c 改写或 Q11 放行。resume 和离线
business verifier 都根据实际 frozen profile/events 要求精确 limitation 与失败声明。

功能第一轮3 passed（10.39s）；后继新增完整分母控制尾部误用 `_Inputs.governor`，第二轮
3 passed/1 failed（16.77s），原日志/根保留；该测试已经断言原DQ异常，失败发生在测试尾部，
不能算产品门绕过。修正后全 hosted campaign 回归29 passed（295.39s），日志
`/tmp/hm-q06-hosted-campaign-regression01.txt`，固定根保留。
[独立窄审](../reviews/hm-q06-incomplete-dq-stop-narrow-review.md)，hash
`59a66b3adaf198d27fabbcb7e990b19588e2fd01ca796053faea487a25479c44`，覆盖一次trial后取消、
七个可解析报告篡改、原完整分母失败门及重启全fixture不变；没有P1。gpt-6.1-sol/high、
attempt1、usage unavailable。只审组件，不授Q06/HM09。

实际冻结 B `8037d0010807ee7958aeed52de3154c3a1bcd5d763a6bcca42dc65e797d29dc7`
的两个全新 successor component 根，使用现有 QuantosResearchExecutionAdapter 和 native
Ledger/selection，不执行研究：cancel 与 expires_at 处过期都保存失败报告，native offline
verifier/file closure 通过，Q11 predicate 拒绝，fresh resume 文件/目录不变。日志
`/tmp/hm-q06-frozen-dq-bounded-stop-native01.txt`，根
`/tmp/hm-q06-frozen-dq-bounded-stop-native01-root`。手工 management registration 的
frozen-input callback 是组件替身，不声称 source-bound installed bootstrap 或 live source。

新增七个固定管理预算配方（请求、研究attempt、总提交、单请求提交、trial、execution、
确定性compute workload）。只接受原两候选预算基线，不接受任意 policy edits；typed预算
验证后重新构造 campaign/native activation/frozen selection plan/readable campaign binding，
保留原家族、manifest、执行输入和 seed Ledger，不改任何安装中预算。19组件控制通过
（4.57s），七个实际冻结输入的 native plan authoring/derive-spec/governor 控制全部通过：
`/tmp/hm-q06-budget-recipe-native01.txt`，新根
`/tmp/hm-q06-budget-recipe-native01-root`。这些是 authoring 控制；完整 Q06 原始 worker、
source predicate、最小预算真实执行与 cancel/submit竞争矩阵仍未完成。

### 2026-10-01：attempt16 原执行失败、attempt17 原损坏捕获与 verifier 后继

attempt16 的冻结1122922安装完成28协议+7业务durable捕获后，在首个
execution-prepared 的 recovery-1 中失败；原 child exit1、failure原件记录
RecorderInitializationError，父级失败ArtifactIntegrityError。原件、35项capture和失败日志
`/tmp/hm-stage-1122922-attempt16.log`完整保留；不得把它写成44项完成，也未运行后续Q02–04/
Q08捕获。另从crashed原件复制到全新组件根做只读来源的原执行诊断，不改原件。

新的冻结77c129f安装 attempt17 捕获五个corruption原件成功，B上述8037d001，D
`077b62211806f06319cd2ec0a9dd42d6155620bd30371779efe0aae931a9ec9d`，wheel hash
`7d606c51bd14bd05dbe53ed3201217f0f56b2e228a5ebb96fdf1efc64fde7c6f`；原件根
`/tmp/hm-stage-77c129f-attempt17`。其 diagnostic01/02 source-bound verifier 仍失败，两个新
导出根/日志保留。只读跟踪定位唯一未归属文件：生产loader物化冻结
selection-plans/sha256-<frozenPlanHash>/plan.json，而老组件只在B/initial-event内保留plan。
后继只按确切 frozen plan 路径和 canonical bytes 归属该文件；完整expected==actual保持，
未增加prefix排除或任意plan许可。
[后继窄审](../reviews/hm-q05-frozen-selection-plan-attribution-review.md)，hash
`7d835326bf48fd0e85706db3dc21010fefd26731a5445bd9a98d0a60b89590b4`，四个plan byte/path
负例拒绝，实际 frozenDQ组件复制件的十个 coherent protocol/report 篡改仍由新offline
guard拒绝，原件/目录不变，execute/Workflow/network 0；gpt-6.1-sol/high、attempt1、usage
unavailable，无P1。不追认原77安装包含后继verifier，不授完整Q05或Q06。

最新49物理窗口+原生业务/C11完整回归通过（1 passed/232 warnings，651.51s），日志
`/tmp/hm-q06-q05-native-full-regression02.txt`，固定根02完整保留。这轮加载最新required
COMPLETE object预检、目录核验、DQ停止与plan归属；native组件工厂现在用原方法物化plan，
另测非canonical plan与错误hash路径的extra plan拒绝。仍非原始部署/fullQ05资格。
ruff全树、format、src pyright通过；尚未取得新的Q12 coverage≥85%、真实Q11/Q09/Q10、
完整失败attempt ledger与HM09–11。模型认证/provider没有调用。

### 2026-10-01：Q05 原件诊断、原子取证与原生 recorder 故障定位

干净后继 `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35` 的新根
`/tmp/hm-attempt17-corruption-diagnostic03` 成功核验 attempt17 的五个原始损坏窗口，
483 个 manager export 来源和55个 checked hashes。qualification hash
`141995a97a6f7f25f2a53773b1f0a56198211e89b6e04475a47283211d583d51`，export hash
`4b7320b9c7f27035e4fc01865ca83a00fbf41e4bdaad2f06fb552a3c7519ba87`。
原77安装与后继verifier源码身份分开记录；完整Q05记录为空、12门仍NOT_EVALUATED，
不能把subset成功写成完整验收。
[必要原件窄审](../reviews/hm-q05-corruption-origin-review-attempt17.md)，SHA256
`bcb06ffc9fad6daf598ba3205565259996ed4f972b63e0b1a9ec6f5918ba1408`，独立核对原安装/
git成员、原始kernel进程、三次waitpid、目录与逐项损坏，删除空目录及改exit负例拒绝。
新版mount recipe下另只读重查仍55 hashes通过，日志
`/tmp/hm-attempt17-legacy-namespace-readonly-recheck01.txt`，保持旧profile的精确argv。

attempt16 的35项非执行durable原件另在全新
`/tmp/hm-attempt16-partial-durable-diagnostic01` 诊断根只读核验通过，qualification hash
`da99c9dc0834e6444eb8b418335c602b37fdba5bcd09bd3e4cc0308be530ef66`，export hash
`58752f8794d681cacca24d910249f33b4e728bbfab3867dacbba292a352732a4`。
同时保留原父级失败与 RecorderInitializationError child 原件；没有复跑或修补失败根，
没有完整44项或正式Q05 PASS。该35项partial诊断尚非独立完整资格审查。

新增原子取证reader仅允许已知 native spec/REGISTER INTENT/object 的特定`.publish-*`
pair 在file_linked窗口拥有同inode/nlink2；两次O_NOFOLLOW descriptor walk检查全文件/
目录/dev/inode/link/uid/gid/mtime/ctime，bounded entries/file/aggregate，完整hash与名称
不变。canonical Store/raw reader没有获得hardlink例外。副本明确是forensic bytes，
每alias复制成独立单链接文件，原physical facts单独保留，不能作为canonical来源权威。
[原reader审查](../reviews/hm-q05-atomic-forensic-reader-narrow-review.md) 保留资源上限P1，
[后继资源关闭审](../reviews/hm-q05-atomic-forensic-reader-resource-closure-review.md) 独立确认
枚举/aggregate/growth在超限前停止，旧报告不改。第一次缺Directory schema的开发回归
20 failed/19 passed；修正39通过。原资源canary失败也保留，后继41通过。

[原snapshot/probe审查](../reviews/hm-q05-atomic-snapshot-probe-narrow-review.md) 复现输出位于
authority内时先写后拒绝；[关闭审](../reviews/hm-q05-atomic-snapshot-source-closure-review.md)
确认写前检查字面和physical祖先/dev/inode别名、O_NOFOLLOW pin现有根，same/inside/parent/
sidecar symlink均拒绝且完整原facts不变。只保证固定已有channel，不承诺任意fresh channel
API。独立43 reader/probe controls通过，真实fork退出73/74/0。

生产bootstrap现在先read-only检查spec registration；frozen seed物化复用原
atomic_write_bytes_at，不再在重启时产生新temporary或改变原seed目录时间戳。
[两处生产重启副作用窄审](../reviews/hm-q05-atomic-production-restart-side-effects-review.md)，
SHA256 `43348643cc1e1f9b133672788f99c6625d14376e29da38f580d30d4623e53687`，25 controls及
真实fsync/错spec bytes/额外spec/existing seed冲突反例通过；不宣称完整installed bootstrap。

主agent12固定atomic fork controls与unknown case共13 passed（19.54s）；reader/probe后继
43 passed（24.28s）；exact native checkpoint/篡改/dispatch/inputs共35 passed（12.11s）。
actual frozen B17 加生产loader在12个全新component根全部通过：原未完成窗两次fresh拒绝
且physical facts全相同；已发布窗 nativeprotocol/budget/Ledger/file closure及R1等待状态
通过，第二次bootstrap事实不变，execution/Workflow/network均0。日志
`/tmp/hm-q05-atomic-frozen-business-component01.txt`，根
`/tmp/hm-q05-atomic-frozen-business-component01-root`。其management factory绕过安装/
profile/kernel检查，保持NOT_QUALIFIED，不能替代installed原件。

管理端原子worker/source predicate和完整61窗口Q05 dispatch已接线：44 durable、5损坏、
12原子全部必需；不能把49或12 subset给PASS。copy root与原physical sidecars明确绑定，
actual after unsafe原树通过独立forensic reader重新读取；positive native根复用已有只读
验证。独立窄审发现exit原件只检查集合membership而漏了path phase；已改为精确source
phase及该phase的waitpid tuple相等。
[原谓词窄审](../reviews/hm-q05-atomic-verification-narrow-review.md) 原样保留P1；
[exit闭合窄审](../reviews/hm-q05-atomic-exit-record-closure-review.md) SHA256
`1b652dd1756558c51d699964f840abb83eb6abded962292581f1ddfa0a99896d`，独立精确branch控制
证明三合法phase通过、两个错path phase拒绝；它不是完整installed sourcewrapper验证。

Recorder诊断component01未安装network hooks，约12分钟后主动SIGTERM并保存abort marker，
不当作离线证据；component02安装deny hooks后完成首次候选，返回WAITING_FOR_AGENT但记录
一次SOCKET_CONNECT，仍非离线PASS，且未消费完整家族。两原根/日志保留。
随后全新实际namespace诊断
`/tmp/hm-q05-recorder-namespace-component01-root/child.log` 明确复现：没有/bin/sh、存在
/usr/bin/sh；Qlib原生start_run→_log_uncommitted_code→subprocess因FileNotFoundError失败，
留下active experiment；第二次qlib.init报RecorderInitializationError，network0。
后继component02只增加/bin→只读/usr/bin布局，native recorder正常结束，active=false，
第二次init成功，network0。两次均是component诊断，不追认原安装或完整Q05执行。

新mount policy v2绑定service的/bin别名，并显式设置MLFLOW_DISABLE_TELEMETRY=true，
使用[MLflow官方opt-out](https://mlflow.org/docs/latest/community/usage-tracking/)；未确认长
component02那一次connect的caller，不把遥测说成其已证明原因。固定deny hooks及零网络
门仍保留。原v1 mount bytes/hash和来源重算recipe保持；unknown policy hash硬拒绝。
失败worker新增有限module/function/line位置与联网调用位置，不记录异常message、frame
locals、路径或环境。原16失败记录不改写。
[v2 mount policy窄审](../reviews/hm-service-mount-policy-v2-narrow-review.md)，SHA256
`b379aa98714398055d583f428e98ba591cefd6327e120c2b878a9b146c3eac61`，独立核对原legacy
bytes/两role argv不变、host新旧相同、unknown hash拒绝。最终v2 policy hash
`8d1b9175f41626fbd33eed6c6d350a0fbb6003dbe59536fba29e8d8a00fd2d4d`；新component03实测
telemetry client absent、env=true、native recorder结束/二次初始化成功/network0，原根
`/tmp/hm-q05-recorder-namespace-component03-root`。另独立12 frozen业务组件只读复核通过，
完整原files/dirs/physical facts不变，执行/Workflow/network0；仍不授完整Q05或HM09。

管理端含真实kernel检查14 passed（5.91s）；默认沙箱AF_UNIX bind拒绝造成5 failed/69
passed，保留原日志与first-failure诊断。正常Unix权限下原deployment整组18 passed
（11.08s），namespace+offline environment控制1 passed；不删除失败记录或把deselect当作
隔离证明。synthetic negative-origin/reader/probe回归77 passed（153.85s），失败位置probe43 passed
（113.27s）；launcher/offline profile绑定组件29 passed（6.90s）。src严格pyright、ruff、
format通过。这些均不是Q12 exact-commit coverage门。
尚待完整新安装Q05 source矩阵、Q06、Q12、真实Q11/Q09/Q10、失败尝试总账及HM09–11。

### 2026-10-01：新安装原子来源闭合与 Q06 生命周期子集

原子发布与只读服务修复冻结为 `93fef2875bcf10386badb921f6ede112cf2704c5`。独立干净
工作树 `/tmp/hm-q05-atomic-installed-worktree` 离线构建 wheel，SHA256
`de30b64fce57fbe49d50e25e2fe1594e405d53e21fc9f0e2992c5ff0246fe217`。全新 attempt18
安装根 `/tmp/hm-stage-93fef28-attempt18`，B
`aa03f815f0c5701c676fd6ae943ab68bd8493720b53db46545e84089b19471ef`，D
`8af66253b6f052821ab4d8a9f4caca1d78e348311e4e98ca439f4ec89f54580b`。实际启动、权限
探测后停止 live 服务；12 个 atomic 窗口各自在新 authority/channel 内捕获三个真实 child
退出及四阶段副本、原 physical facts。live authority 不变，未读取模型认证或调用 provider。

首次 export driver 在写出前因错误模块 import 失败，脚本和
`/tmp/hm-attempt18-atomic-diagnostic01.log` 保留；新 driver02 只修正 import。新导出根
`/tmp/hm-attempt18-atomic-diagnostic02` 的 565 个文件通过原始 manager export 绑定，完整
12-window subset 的只读 source predicate 通过124个 checked hashes。qualification hash
`418ec5c9b108d4d44fd17d5d3e8ad0a1484697958ab4d12c2586bcd9b2cf8d1e`，export hash
`0dbb89f3b1b6769942c2b91ac317b216144364302a17a4b7faa935be3ae6621d`，外部 subset result
hash `35973fc6ca4c5505724df560fd3dd42d9fa3672047756ef3a0b662a4c1129a08`。producer/
verifier 与安装使用同一精确93提交；完整 Q05 case 仍为空，12个正式门全部 NOT_EVALUATED，
eligibility NOT_QUALIFIED。新的必要独立原件审查正在进行；该 subset 不替代61窗口矩阵。
同一新安装另在全新 execution-prepared case 执行真实 Qlib 恢复，首次物理退出73已捕获，
完整恢复尚在运行，不能写成 PASS。其日志
`/tmp/hm-stage-93fef28-attempt18-native-prepared01.log` 和原件完整保留。

Q06 后继代码新增四个管理端固定生命周期 worker：cancel/submit 两种获锁顺序、TTL 首次
响应和 TTL 已见响应。winner 在原生 intent_published 持有目录 flock，loser 在同 inode
进入实际 LOCK_EX，父级独立 LOCK_NB 被拒绝且 loser waitpid 为(0,0)后才释放 winner。
记录与 journal 中的实际操作顺序交叉核验；没有给研究 RPC 增加故障或任意执行接口。
新 source subset 强制四案例/四阶段、精确原来源/lock inode、installed program/namespace/
PID、逐 phase exit、native events/Ledger/report/budget/file/directory closure。该代码尚未
取得完整 installed lifecycle 原件；预算七案例和正式完整 Q06 门仍未闭合。

开发失败保留：首轮功能测试4 failed/1 passed源于测试引用不存在的 report 字段；后继
2 failed/3 passed源于忽略 native 预发布 EXHAUSTED receipts；修正后5 passed/25.17s。
原生 e2e01 1 failed/26.18s发现 schema-invalid trial 的 native validation round=1，旧
谓词误要求0；e2e02 1 failed/36.02s发现 first-expired SUBMIT 的原生
(budget, EXPIRED terminal, receipt)漏归属。后继只在确切无 prior acceptance/terminal 且
达到 TTL 时重建原生 service EXPIRED terminal，并比较完整 canonical tuple；实际协议
执行规则未改。e2e03四 native 场景和20篡改控制通过1 passed/51.14s。

[原生命周期窄审](../reviews/hm-q06-lifecycle-narrow-review.md)，SHA256
`6872a2a51f9b72b0f3a8ec98cdb6298c26dac72f01fed822040a95afee0cfc93`，独立发现实际
protocol clock 偏移+1秒而 metadata 保持exact expiry时原谓词仍接受。原反例与报告不改。
[后继时间关闭审](../reviews/hm-q06-lifecycle-clock-closure-review.md)，SHA256
`a175c72c0489bfd4ccfd739b18a8c87faf8cb213d1471eeca19fb1ca08ce56ee`，在原反例上只读
拒绝，全部原/阶段 physical facts 不变；独立两个 frozen B17 race 原件复核42/83 hashes
通过，六个 native expiration tuple边界负例拒绝。审查 gpt-6.1-sol/high、usage unavailable，
不授完整 Q06/MVP 资格。后继要求实际 request/receipt/terminal/journal 的 exact fixture
clock与principal匹配；普通生产过期仍允许 deadline 之后，未改变全局 expiration 语义。

最新 e2e05通过1 passed/55.06s，含四 native 场景、20篡改、七有限预算派生及新 plan
publication controls。TTL±1秒/错误principal/native tuple控制15 passed/14.51s。最初
11个 tuple tests 使用通用仅ContextPack projection的fixture而被拒绝，11 failed/48 passed
日志保留；新独立 native fixture包含原生要求的ContextPack+proposal schema，11 passed。
历史49物理窗口+原生业务/C11完整回归1 passed/232 warnings/656.45s，日志
`/tmp/hm-q06-ttl-native-full-regression01.txt`，证明有限 first-expired closure 修复未回退
已覆盖的原生恢复链路，不是正式安装或 Q12 coverage 门。

预算 authoring 分出只读 `derive_hosted_budget_case`，管理发布仍调用 native plan publisher。
对实际 frozen B17 的七次派生与之前 native01 已发布 B 逐字节相同，原 plan 文件/目录不变，
日志 `/tmp/hm-q06-budget-derivation-readonly01.txt`；不靠后继作者标签接受任意预算。
frozen B17 lifecycle component02已只读复核原01两race根，并在新根捕获两个TTL案例，
四项通过42/83/40/46 hashes。其bootstrap仍是管理组件工厂，不能替代 installed/kernel
来源验证，且不覆盖原01旧谓词失败。全 src 严格 pyright与ruff通过。
尚待完整 Q05/Q06 安装矩阵、Q12≥85%、真实 Q11/Q09/Q10、失败总账及 HM09–11；MVP未完成。

后继 attempt18 原子原件独立审查已完成，见
[原件窄审](../reviews/hm-q05-atomic-origin-review-attempt18.md)，SHA256
`c05d62683f16b657b359319510f0408d1729af194834a3645638b103c4f97294`。
冻结93源码独立重算124 hashes；160 installed Python 文件与wheel、git一致；48阶段根、
36 actual waitpid记录；12 original case完整文件、目录和physical facts在审查前后不变。
九项新的错来源、错phase/exit/inode、空目录增删反例均拒绝，三原link2 authority仍被canonical
raw reader拒绝。未发现新P1；该窄审不授完整Q05或MVP资格，正式12门仍NOT_EVALUATED。

Q06预算后继加入七个固定worker：独立冻结variant B/D后才启动实际fork进程；执行预算
调用native deterministic adapter/QLib Workflow，其他六项不执行；32次unique over-cap响应
复用固定exhaustion receipt，seen response复用原receipt不增加收费或文件；两次fresh
bootstrap恢复核对完整raw inventory和目录。管理RPC未增加任意执行或预算编辑能力。
新budget verifier复用native events、budget、execution、Validation、Ledger和file closure，
逐阶段核对固定clock/principal、报告分母、真实execute/workflow计数与父级waitpid。

预算组件失败记录均保留：e2e06的receipt字典hash未经过契约类型规范化；后继改用
HostedSubmissionReceipt.content_hash。e2e07测试adapter仍绑定基线campaign/budget而被native
request校验拒绝，修正测试接线使adapter与独立冻结variant一致。e2e08新predicate漏计
native预发布的global/per-request exhaustion receipts，修正为原生固定集合。e2e09漏计
实际native execution的空execution-locks目录及MLflow .trash；后继仅按核验过的execution
identity加入这些固定路径，未知目录仍拒绝。原目录、日志和失败状态未重写。
e2e10 `/tmp/hm-q06-lifecycle-budget-native-e2e10.txt`通过1 passed/208.15s：四lifecycle、
七预算native accounting、35篡改控制；execution_allowance确实一次native execute并有
Workflow，compute_allowance零execute/Workflow。该测试仍使用明确的synthetic组件工厂，
不能替代installed/kernel original-source资格。运行期间后继加入额外recovery目录guard；
最终installed矩阵须使用最后冻结源码重新运行。

管理预算与TTL/protocol/qualification组件01有1 failed/63 passed，原因是默认sandbox的
`/proc/73/status`视图无法读取真实子进程。没有放宽内核校验；新02在真实内核环境执行
同组测试并加入qualification回归，73 passed/37.57s，日志
`/tmp/hm-q06-budget-management-components02.txt`。全src严格pyright02零错误；ruff通过。

管理部署新增固定child路径`qualification-deployments/Q06/<case>`和可信parent declaration，
每项重新冻结B→L→C→I0→D；read-only verifier从parent原件重新derive B、核对完整child
install/provenance/projection以及固定runtime字段，并沿parent manager export绑定child每个
原文件。组合Q06入口强制4×4生命周期根和7×4预算根共44根全部通过。当前只有组件正例，
该组合入口和嵌套安装来源正由gpt-6.1-sol/high独立窄审，尚无正式完整Q06 PASS。
attempt18 execution-prepared真实安装恢复随后失败，保留
`/tmp/hm-stage-93fef28-attempt18/evidence/attempt18-native-prepared-failure.json`与原日志。
原managed negative-run `23840865aac7c95d2d14b28e2c7cee815af1add9a832d96a363ce40d19ee0d5b`
记录return_code=1，prelaunch
`0058db92039b37db7ff6267fa45e9acf2b7a0ca1105f0104687cb71002b61ab2`。
实际crash exit=73；recovery-1运行至旧3600s边界后没有完成记录，既有两research result与
一validation report保留，不据此宣称完整执行成功。旧源码timeout分支仅在RAM追加waitpid
记录，未发布phase-exit；后继在kill/reap后发布实际exit记录，再按失败停止，旧根不追补。
仅后继未冻结源码的native Q05管理child设7200s，外层Q05设14400s；Q06唯一native预算
case外层7200s/child3600s，其他Q06外层300s。均为有限管理fixture wallclock上限，与
协议TTL、研究预算和compute workload units分开；冻结契约、旧D及旧结果未改，需新源码
审查与新D重新执行，不能继承原attempt18部分成功。

后继超时留证/原故障窗口组件44 passed/111.01s；manager export/source回归11 passed/17.56s。
预算[原窄审](../reviews/hm-q06-budget-narrow-review.md)，SHA256
`cbd02d35428b0ea895fe3b3ebb589119ef4394fa7d8e13d77cc3d9575f8492fe`，独立发现子staging
祖先alias可把失败前写入重定向父authority，原合成反例17files/21dirs与报告P1 OPEN保留。
未冻结stage19。后继先O_NOFOLLOW pin父管理root、保护目录inode树、固定Q06祖先，所有已有
alias检查先于任何mkdir；管理fork固定新case inode为cwd，真实stager只以`.`和显式
prepared_root_fd操作，要求同inode且空根。所有第三方copy/git/compiler保持相对case cwd；
母级只通过RAM pipe取D hash/root inode，pinned evidence fd发布declaration，label替换不能
把写入重定向到父authority。旧case-root仅后验核对的中间版本仍被独立审指出遗漏，未授关闭。

后继路径与预算组件02 48 passed/5.56s，18条路径控制覆盖8 protected roles、两个祖先层、
Q06父目录/evidence标签替换和新case basename替换；文件、目录及stat physical facts不变。
真实native staging组件01、02分别新根通过。最新02以prepared case cwd执行，D
`3257f1e3b33e325acce4027b2c5f71546ee3410bd2b4b3c0ee46363b205aaf31`、B
`5d12624bd9f09c18f4887d2e0a4f6f41714428e89c185921c9ba6568abf4999a`，8 protected raw/dirs
和主进程cwd不变；独立新case-root替换真实stager控制在不存在base prefix处停止，23832个
partial native文件只在原case inode，8 protected raw/dirs不变。日志分别为
`/tmp/hm-q06-budget-stage-native-component02.txt`和
`/tmp/hm-q06-budget-case-root-component01.txt`。这些仅只读借用旧93 wheel/input的组件，
该wheel没有budgetworker，不替代七个新安装原件；独立后继关闭审查仍在进行。

CI覆盖率新增coverage.py原生fork收集，以测量真实fork子进程，85%门槛不变。首个临时
组件诊断误带threshold override，发现后中断并保留9 passed/KeyboardInterrupt日志，未授
任何coverage门。新组件02遵守原85%门槛，79 tests passed/305.56s，因只运行组件子集而
全库coverage30.63% FAILED，明确不是Q12 PASS。79项trace中lifecycle worker实际收集168/
203 statements，fault worker135/228；仍需新冻结提交的全库CI测量，不降低门槛或排除模块。

独立[路径关闭审](../reviews/hm-q06-budget-path-closure-review.md)，SHA256
`731a112ada54b26177f513821a6feb6891fd79a5caa9b192e2d60cf13b24793f`，对后继明确源码
关闭具体ancestor/case-basename P1，原OPEN报告不改。独立最新两文件52 passed/5.22s，
native组件02重新只读核验B、D、inventory与两declaration通过，原组件完整raw/dirs不变，
deny execute/Workflow/network零调用。主agent最新prepared-root管理回归14 passed/6.52s、
预算/路径52 passed/5.34s；全src严格pyright、ruff及514文件format检查通过。
该关闭仍不授Q06或MVP资格；下一步冻结新源码运行完整七个installed预算worker与四个
lifecycle来源矩阵、剩余native Q05窗口和完整Q12。已准备新attempt19离线driver，未复用
旧失败root，也没有运行provider或读认证；完整资格声明继续等待全部门与HM09独立接受。

2026-10-01 后继实际安装与 Q12 修正记录：精确源码
`359338d35e880a93f06ff5bcffb005bdd7de5368` 的完整 worktree 为
`/tmp/hm-q06-installed-worktree02`。早先不完整资产复制的第一个 worktree 保留未复用。
attempt19 wheel SHA256 为
`ef0bf2a886a15a98d25242fed4986bc318506b668a6bac24cffb5513ea0475d8`，实际部署根
`/tmp/hm-stage-359338d-attempt19`，B
`5981c63df9b7fcf87ce83822de685da31e22e4987f3a43070fc1e5b1ea0a399b`，D
`7be62dc94bf362b96660d3c23445ded42dec0e4404fe403104a0b91896073a36`。
安装服务与 Q07 实际检查已采集；Q02、Q03、Q04、Q08 的管理 fixture 已采集，
Q05/Q06 矩阵仍在运行。另行启动的 Q05 `execution-started` 已有原生完成记录；
`execution-prepared` 与 `execution-execution_receipt` 仍待实际完成。
receipt 驱动首次错误使用非固定 case 名，CLI 在 case 执行前拒绝，原日志保留；
后继只使用冻结有限 case。所有这些新记录仍为 `NOT_QUALIFIED`，并非完整 scenario PASS。
原 live authority 未改写；其 initial request 已过期，不能重新设置 TTL 冒充 live。

359338d 全库 CI 实际完成为 **72 failed / 1314 passed / coverage 74.63%**，不通过 85% 门。
原日志 `/tmp/hm-ci-359338d-pytest01.txt`，SHA256
`5ce5390eb9c9a128813688784f1af2505a45da8cfefb4458b9fb343a35ddf983`；coverage XML
`/tmp/hm-ci-359338d-coverage01.xml`，SHA256
`dc293cba6595591db41208afa5bc1be9820ea490857dc39339e7d838c19cdd9f`。
60 项失败由整个 pytest session 收集时导入 Agent SDK、再 fork 原生 offline probe 导致；
保留生产 SDK 拒绝逻辑，后继仅让明确标记的原生 probe 在新 Python interpreter 执行准确
nodeid。独立先导入 SDK 再运行 atomic 的新回归 27 passed，子集全库 coverage29.55% 仍
FAILED，不算 Q12。其余 12 项来源控制的合成 profile 缺少新版 mount_policy_hash，已修正
测试 fixture；34 项 offline profile 回归通过。359338d 原格式/ruff 通过；严格 pyright
需显式真实 venv 路径，03 零错误，最初两次未找到依赖的失败日志不删除，不创建 venv symlink。

新 Q12 管理 capture/source predicate 已实现固定五个完整 CI 命令、逐项原 prelaunch/
waitpid/log、coverage 与 JUnit 重新计算、完整 tracked source 与 before/after authority
闭包，但还没有新冻结 full CI 原件，不能授 Q12。独立第一窄审
[原 OPEN](../reviews/hm-q12-regression-narrow-review.md)，SHA256
`36a94cf6b025b755ad63f41bd721877848fc3c673ee6e8cbb0de977ce206e621`，发现 pyright
默认版本探网、外部 Node、外部 Python prefix 及 EOF 后超时逃逸四项缺口。后继冻结 CI
完整前缀由 D 的 python/ 全文件派生，只加经冻结 coverage wheel RECORD 认证的官方
a1_coverage.pth；Node 显式复制为只读 ELF，原始 declaration 与 inventory 绑定每项字节。
固定 bwrap 只读基础/前缀/Node，明确禁止工具版本发现与 Node 下载；所有检查使用真实
独立网络 namespace，释放 exec 前由管理父读取 /proc 核查 PID、祖先、namespace 与
Python executable hash。EOF 继续使用原剩余 deadline，超时原 bytes 与实际退出完整保存。

独立第二[关闭复审](../reviews/hm-q12-regression-closure-review.md)，SHA256
`318214e13aea00e913a0f0c77091fd94da3159eee2b8ccb446734a75b46e28f6`，117 组件通过，
关闭三个原缺口但发现 bwrap 新会话下 kill 外层进程组留下真实孤儿后代，以及管理运行时
实际 isolated flags 未核对两个阻塞。该 OPEN 报告不追改。后继增加固定 PID namespace：
原管理父以真实 /proc children 与 NSpid 映射核对 init/bridge PID，在 exec barrier 前开
native init pidfd，完整 namespace 实际退出后才记录 namespace_exit_observed；失败时
对实际 pidfd SIGKILL，内核销毁 PID namespace 后代。冻结 Python/glibc 无公开 pidfd
wrapper，复用既有 libseccomp 名称解析与真实 Linux syscall，不模拟进程或硬编码 PID。
capture 和 verifier 同时硬要求真实 isolated/ignore_environment/no_user_site/safe_path。
新三项原生控制实际生成 start_new_session=True 的 60s 后代，以后代原 pidfd 确认正常、
普通超时与 EOF 超时三种退出均清理；同组 161 passed/45.15s，全 src 严格 pyright 零错误，
全库 ruff 及 525 文件格式通过。新的独立关闭审正在进行，尚未冻结后继源码。

CI staging 使用原 Q06 pinned-inode helper 的唯一新固定 Q12 家族，无研究 RPC 能力增加；
新增八 protected ancestor alias、retarget 与 finite-family 控制。真实 fork 准备的四控制
5.95s 通过，原安装与全部保护角色的 raw/dirs 不变；坏 hook/Node 和既有 root 原证据保留，
子进程实际 PID 被 waitpid 回收。实际固定工具组件01只读借用旧359安装、派生真实完整
前缀与 Node，网络 namespace 下 pyright exit0；由于该旧 wheel 没有新 Q12 capture，
它明确只是 `NOT_QUALIFIED` 组件，不能替代新冻结源完整 CI。后继 PID namespace 工具
组件另建新根；未启动的 driver 日志与所有 failed component/type/coverage 日志均保留。
当前仍待新源码独立关闭、冻结安装完整 Q01–Q12 原件、HM09 接受、Luna HM10 与 HM11。

后继第三[PID/flags 关闭审](../reviews/hm-q12-regression-pid-closure-review.md)，SHA256
`0797ae60cbdaad6178e3921e726eaa9870d835b31babc0b0ab20c3862af6d7d2`，在精确后继源码
上限定关闭剩余两项代码阻塞；两原 OPEN 报告和原反例不变。独立127组件65.84s通过，
另行三项原生跨session后代各自原pidfd观察退出，guest PID与管理父真实NSpid映射、init
及namespace闭包留存；四管理flags逐字段false的原记录负例均拒绝。工具component02的
真实pyright exit0、PID namespace退出已核对；它只读借用旧359wheel，仍不授新源资格。
本次准备冻结后继源码；新部署先bootstrap注册而不提前签发live请求，完整离线矩阵与
Q12之后才通过真实start创建请求，避免修改原TTL或重新签发过期请求。新Q12需真实冻结
管理前缀运行全部CI并通过原85%门，后续live/Q09/Q10/HM09与Luna文档仍未完成。

2026-10-01 科学工件快照后继：冻结提交
`c046e37c6618e1f65b025a57924c0fe4b0c5fd93` 已包含 Q12 的第三次独立代码关闭，
但其完整安装 CI 尚未开始。attempt20 在验证业务输入时因 release 资产目录布局错误失败；
保留 `/tmp/hm-stage-c046e37-attempt20.log` 与不完整 worktree03。
新完整 worktree04 的 attempt21 已冻结 B
`6ec54ad9b87d6ca27b6d12e55f42f1c60d46c965dd93ca5842246d2b63893dea`、D
`dd21804e9ac166cd48d29a7a311687695b6733b2a9e99055b03885039a7e6878`，
bootstrap 注册成功，但管理 pending 客户端不能处理“尚未签发请求”的 JSON null，故失败。
没有签发请求、执行 CI 或读取认证；服务已停止，原 root 与失败记录保留。
后继驱动直接只读核对原 protocol store 的零 requests，不提前调用 start/pending。

旧359安装的 execution-prepared 已实际完成 recovery-1 与两次 native execute，随后
管理快照在 Qlib 约30MB labels/predictions JSON 处遇到小型 typed-contract 的16MiB上限，
只有496个复制文件，未执行 recovery-2。execution-execution_receipt 的294个源文件中有
两个大文件，其 crashed 快照只复制248个文件、尚未开始 recovery。两个窗口均 FAILED，
原根不补写；不能因原生执行部分完成授予 Q05。
后继只修管理科学工件复制：raw inventory 的既有16GiB单文件上限不变，以已经观测的
文件 size 有界读取，逐项核对 SHA，再重核源和目标 raw/目录闭包。小型协议、模型响应和
typed reader 的16MiB默认上限、预算及TTL均不变。

新组件 `/tmp/hm-scientific-snapshot-native-component01` 只读借用旧 prepared 源，
完整复制616/616 files及4个大JSON，原 inventory
`44d59424f34705ad16af85c4122844f530899deaec7504cdcc6ac9b7f03536c9` 与目录完全一致，
原源与旧失败快照均未动；该组件 NOT_QUALIFIED，不能补齐旧窗口。
生产 helper SHA256
`074cd7d493b8aaed7595d926a79dc2c878d7692ebda9c908de19db23bf0ca261`。
原组件01为2 failed/81 passed/463.40s，两失败仅为新增测试的异常类型预期错配；
修正后的 unit03 两项 passed/1.72s，原失败日志不覆写。全src严格pyright零错误、ruff通过。
必要独立审查仍使用 gpt-6.1-sol/high；实际616项及旧失败496项前后重新核对、16GiB+1
sparse、增长、同大小内容变化、symlink/hardlink/FIFO和零长度控制已完成，独立17项通过。
下一步冻结限定代码修复，使用新完整 worktree、wheel、D 与新root执行实际Q12完整CI及
全部离线来源矩阵。HM07/HM08完整门、HM09接受、Luna HM10与HM11仍未完成。

科学cap[独立限定关闭审查](../reviews/hm-scientific-snapshot-cap-review.md)，SHA256
`b1f3d27eba7e641c9d5bb692c2bdd3d8dcd28b4f563e194f8c14aac808b8cac8`，已关闭上述具体代码缺口，明确仍为
NOT_QUALIFIED；原OPEN/FAILED报告与旧根均未改写。
