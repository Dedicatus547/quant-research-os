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
