# HM-MVP 实施进度

日期：2026-09-30。整体状态：`NOT_QUALIFIED`，尚未完成 MVP 验收。

HM-01/02 的基线、冻结契约和独立契约审查已保存；HM-03/04/05 的版本化交接、
持久化业务编排和受限 CLI 已实现并通过组件回归。HM-06 的冻结安装、namespace、
Unix channel、可信 CLI 捕获及管理 staging 已实现；已有实际启动和 Q07 原件诊断，
尚未完成完整正式资格。
HM-07 的只读 raw/protocol/business verifier、保存 SUBMIT 导入和 offline 管理入口正在完善；
尚未实现完整 Q01–Q12 的 scenario verdict。HM-08 的实际模型驱动已接入受限 CLI，
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
