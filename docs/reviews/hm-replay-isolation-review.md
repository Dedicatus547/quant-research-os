# HM 追加窄审：隔离解释器与保存协议重执行

日期：2026-09-30。结论：`APPROVED_IMPLEMENTATION_CLARIFICATION / NOT_QUALIFIED`。
审查模型 override：`gpt-6.1-sol`；reasoning effort：`high`；attempt：1；usage：`unavailable`。
最新用户的模型 override 适用于开发与本次独立审查，不修改冻结研究 profile 的
`gpt-6-sol/high`。本审查不调用研究模型、不执行研究 pipeline，也不授予任何 Q 门 PASS。

允许下面两项有界实现：初始化前固定 seed 的 CPython isolated embedding launcher；
仅由管理域离线 verifier 使用、逐操作导入保存 SUBMIT 的重执行驱动。
批准以本文条件全部满足为界；实际实现、安装、两根执行和机械证据仍须验证。
本文件是后继实施澄清记录，不改变冻结契约、验收矩阵、HM02 freeze manifest 或既有部署审查。
工作树正在开发，本文的代码观察不是 exact-clean-commit 接受记录。

## 隔离启动的裁决

C10 冻结的是 `hm-isolated-service/v1` 的导入、安装、身份、namespace 与 channel 边界；
没有把普通 Python `-I` argv 冻结为唯一实现。C11 同时要求进程启动前的
`PYTHONHASHSEED=0` 和入口实际观察到 hash randomization disabled。
普通 `-I` 忽略 `PYTHON*` 环境，单独设置该环境变量不足以满足两者。
[Python 3.11 命令行文档](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I)
明确该忽略行为；[初始化文档](https://docs.python.org/3.11/c-api/init_config.html#c.PyConfig.use_hash_seed)
提供 `use_hash_seed/hash_seed` 和 isolated config 的显式初始化机制。

因此允许 `PyConfig_InitIsolatedConfig` 后设置 `use_hash_seed=1, hash_seed=0`，
在 `Py_InitializeFromConfig` 前确定生效；管理 namespace 在 exec 前仍设置
`PYTHONHASHSEED=0`。这具体实现已有 C10/C11 条件，没有新增 hash 投影或降低隔离门。
不能声称该 embedding 与普通 `-I` 所有行为完全相同；其信号处理、标准流、argv 解析、
locale 和路径配置可能不同，须由实际实现明确设置并绑定。

最小安全条件：

1. 在首次加载项目、依赖或执行研究代码前检查实际
   `isolated=1, ignore_environment=1, no_user_site=1, safe_path=True,
   hash_randomization=0` 及 seed 环境值 `"0"`，失败即停止。
   这些是实际解释器观测，不以 profile 自报或 argv 存在某个 flag 替代。
   不允许先初始化随机 hash，再 setenv、修改 flags 或伪造观察结果。
2. 显式冻结 Python home 和实际导入搜索路径。isolated config 仍可能读配置文件决定路径；
   固定 prefix 内的 stdlib、site、扩展模块、配置文件、launcher 与实际 libpython 全部进入
   install/runtime inventory。任何允许的 import hook 必须来自这些冻结只读文件；
   checkout、CWD、用户 site、继承 PYTHONPATH、用户可改 plugin 不进入搜索路径。
3. 若 `parse_argv=1`，先设所有影响 preinitialization 的配置字段，并先调用
   `PyConfig_SetBytesArgv`，再调用设置 home 等其他 config methods。
   每个 PyStatus 错误均停止，不能退回普通 Python。
   [Python 3.11 初始化顺序要求](https://docs.python.org/3.11/c-api/init_config.html#c.PyConfig)
   是该顺序的依据。
4. 新 binary、源代码、编译/link 配置、实际依赖、固定入口 argv、seed 初始化模式和
   namespace 环境在真实运行前形成新的完整 DeploymentProfile 身份。
   原 profile、request、launcher record 不被补写；已经保存的旧对象不得取得新增保证。
   若已存在冻结的旧 schema 工件，新增契约字段须明确新 schema 版本或保持旧解析规则，
   不通过默认字段给旧 bytes 自动升级身份。
5. production entrypoint 由管理域固定，研究 channel 不接受任意 command/module/path。
   embedding binary 只是解释器启动设施，不增加研究、交易或组合会计引擎。
   Q10 两根服务使用相同已冻结安装；实际数值依赖/线程配置和所有研究子进程的有效 seed
   同样验证。父解释器的 flags 不证明新启动子进程满足 C11。
6. 替换实际启动组合后重新执行 Q07 的真实受限主体 probes。模型、网络、凭据边界仍执行
   原规则；本文不能替代实际 namespace、proc/fd、只读安装和 channel 授权证据。

## 保存协议导入的裁决

C11 明确允许受控导入已验证原 request/response/exchange/receipt/journal 序列，
禁止重新 live submit、修改原 timestamps/principal/budget 或复制研究结果当重执行。
现 `HostedProtocolStore` 将 `REGISTER/ISSUE/SUBMIT/BUSINESS` 的 INTENT 和 COMPLETE
放在同一条含 sequence/previous_hash 的链上；INTENT 还嵌入 publication canonical bytes。
因此只有最终文件名相同、重新生成 journal 或先复制整条 journal 都不足以证明符合。
提前复制 BUSINESS INTENT 会把原 trial/研究预算/完成事实作为目标 authority，违反独立重建。

允许如下窄驱动，保持完整原协议逐字节一致：

1. 先对保存源做独立 raw inventory、canonical schema、hash、journal 链、publication、
   request/response/exchange/receipt、预算、来源和 campaign 绑定验证。
   保存源只读；它不能通过 recovery 补齐未保存工件再被宣称原始 bytes。
   缺失、未完成、损坏或 source identity 不明确均停止。
2. 两个目标根分别 create-if-absent，检查根真实独立、无 symlink/hardlink/shared writable
   输出 alias，没有已有 execution receipt、result、事件、final Ledger、P14c 或 report。
   仅复用同一冻结输入 B/D、原 initial Ledger/events 和保存的模型协议/来源证据。
   运行前后的完整清单证明该边界；管理 source 验证材料不安装为目标业务 authority。
3. 每根应用从已核验 B/D 唯一派生 S，并通过原业务应用重新生成 REGISTER、初始业务事实、
   ISSUE/R 和后续 BUSINESS。控制时钟只属于离线管理驱动，发每个 R 前使用其保存的
   `issued_at`；每个生成 R 的完整 canonical bytes 必须等于对应原 R。
   expires_at、ContextPack、候选、输入、预算和 attempt 身份不能单独投影或重绑。
4. 按原 journal 的全序推进。在复制某个 SUBMIT 之前，目标已经生成的完整 prefix 必须与
   源逐字节一致；即将导入的下一对必须真是原 SUBMIT INTENT/COMPLETE。
   受控导入只发布该对原 bytes 与其中允许的协议 publication，检查完整序号、previous_hash、
   operation id/kind、request identity 和 publication 集合；禁止夹带 BUSINESS/研究结果。
   所有原 unique reject/conflict 及其预算事实保留，原 seen submission 不另收费。
   原时间、principal、receipt、预算 hash 逐字节保留，不用 replay OS principal 替换。
5. 导入后的原 ACCEPTED exchange 由正常 admission/确定性编排消费，独立生成
   PREPARED、STARTED、execution、result、trial/event、研究预算结算、Ledger/P14c/report。
   每个新生成 REGISTER/ISSUE/BUSINESS 的 INTENT+COMPLETE 都须与源中下一操作完整 bytes
   核对，不能只比 artifact hashes；一旦出现差异即停止，不能继续并事后删字段。
   最终完整 journal、对象集合、spec/request/response/exchange/receipt 原 bytes 均核对。
6. 目标根每个需要执行的候选各有一次真实 Qlib pipeline 调用，记录从零开始的调用/receipt
   计数及根绑定。保存源的 execution/results/events/final Ledger/P14c/report 只作为比较或
   独立核验输入，不供目标 execution adapter 查询或复用。
   STARTED 后没有有效目标 receipt 仍按 C07 停止，离线驱动不获得强制重跑权限。
7. 当前窄驱动可只支持已完整保存的正常 live 轨道；遇到未实现的 TERMINATE、乱序、
   超大拒绝、未知 publication/schema 或无法复现的操作，必须明确 fail closed。
   不得静默过滤原尝试、丢弃拒绝/冲突、重新排序或伪造缺失 COMPLETE。
   若该 live bundle 需要这些操作，Q10 不能通过，须补充严格支持或重新取得合法完整输入。
8. 导入只在离线管理 verifier 使用，与 online `submit/auth/TTL` 路径分开。
   原研究 channel/CLI 不新增 replay-import、时钟覆盖、source root 或管理路径参数。
   旧 live TTL/auth/cap 行为仍由真实 online 负例验证，不能因离线导入而放宽。

在每个 regenerated operation 上比原 bytes 属于保留 C11 原协议的具体实施，
不是赋予保存的业务事实新的证据权威。若完整 BUSINESS journal 无法字节一致，最小合法动作
是停止并修复确定性输入/时间/路径，而非投影 journal 或拷贝原 BUSINESS。
确需放宽该要求时只能新版本契约与独立审查，不能在本文或冻结 v1 加例外。

## 最小验证要求与资格边界

| 范围 | 必需测试/证据 |
|---|---|
| 启动 | 实际冻结 CPython 3.11 安装的两个 fresh exec；flags、seed 环境、binary/libpython/home/sys.path 指纹及稳定字符串 hash；普通 `-I`+seed=0 的拒绝对照；缺 seed、错误 flags、初始化失败均停止 |
| 导入隔离 | PYTHONPATH/CWD/user-site/plugin canary 不被导入；安装/config/launcher/libpython 替换拒绝；真实 host 无法触达管理导入或时钟控制；固定 production argv 不接收 host code/path |
| 原协议 | 修改保存 request、response、exchange、receipt、timestamp、principal、budget、SUBMIT publication 或 journal previous_hash 各一次，均在业务执行前拒绝；删/多/重排操作和未知操作拒绝 |
| 两根重执行 | 两个空根各独立 Qlib 调用与 receipt，保留 reject/conflict 的完整分母和费用；生成 S/R 与每个业务 journal 对精确比源；无复制结果/receipt reuse；一根预置结果或 source-output alias 拒绝 |
| 崩溃 | 导入 INTENT/物件/COMPLETE 的 durable 边界退出后核验；原目标 import 幂等且不再收费；目标 STARTED 无 receipt 保持 EXECUTION_UNCERTAIN；只对新生成目标事实执行已有恢复规则 |
| 比较 | 先核验每根完整 raw inventory；只有 C11 七种已验证 schema 的顶层 created_at 可作 inventory comparison projection，逐文件记 raw/projected hashes；journal、hosted receipt、nested/未知 schema 时间差异全部失败 |
| 离线与模式 | Q10 两根无模型/网络/Tushare transport；Q09 单独 receipt reuse，Qlib 调用增量为零；保存原来源和 transport 时间，当前运行耗时/OS principal 放独立 qualification observation |

当前独立执行的 `/usr/bin/python3` 对照使用 Python 3.10.12：相同 exec 前 seed 环境值
`"0"`，普通启动 `hash_randomization=0`，`-I` 启动 `isolated=1` 且
`hash_randomization=1`。它只证明当前机器普通 `-I` 的冲突，不是冻结 3.11 的资格证据。
管理实现方另报告临时安装 3.11 的两个 embedding exec 均满足 flags/seed，本文没有对其
原始记录做独立 bottom-up 核验，不能据此给 Q07/Q10/Q11 PASS。

读到的 C draft 设置 isolated/seed 后使用 Py_RunMain，方向符合裁决；读取时其
SetBytesString(home) 先于 SetBytesArgv，须按上述顺序修正。最终编译/安装/启动和导入实现
仍需结合 exact clean commit、完整 bundle 与 HM-07/HM-09 验证；整体保持 `NOT_QUALIFIED`。

## 本次审查输入身份

冻结文件已重算，contract/acceptance hashes 与原 freeze manifest 一致。
代码 hash 是读取时开发快照，不能绑定随后变化的工作树。
起始 commit：`d6c77055eaa4844a2e0d9423990475ef23dce15c`。

| 文件 | SHA-256 |
|---|---|
| docs/hosted/hosted-contract-v1.md | 14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df |
| docs/hosted/hosted-acceptance-v1.md | e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e |
| docs/hosted/hm02-freeze-manifest.json | ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e |
| docs/reviews/hm02-deployment-bindings-review.md | 784b573fe47c4e5838a74d2ce39bbb420c707ca39d8d4743610ff55ac3782381 |
| src/quantos/application/hosted_protocol.py | 297d2f75c0659e2feefd131da994a9bc51d093c077e29c45c554493a36049a74 |
| src/quantos/application/hosted_campaign.py | 22ad5bdfe1b7f364ac63ca9dd955fe80e40f1765b7bb2a19c902fe47f1371747 |
| src/quantos/infrastructure/hosted_store.py | f334be916dbea410fa70e8e07cafbaee55fef3dda5218b06eac9577c08b6cac6 |
| src/quantos/infrastructure/hosted_python.c | fd51c8ac5ec7aad6ca1f4ed1fa2ac49b4de177f2d364cde8d1c626f9cd5eda75 |
