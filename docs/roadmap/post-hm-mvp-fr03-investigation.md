# F0：FR-03 只读入口调查

调查日期：2026-10-11。范围来自[实施计划 F0](post-hm-mvp-execution-plan.md)与[研究指南 §5.5](post-hm-mvp-research.md#55-fr-03-有界重开与研究接入)。本轮未启动 runtime、account/read、模型/provider、安装或资格执行，未运行测试或大型工件解析，未修改 canonical 依赖锁。

**当前继续 `NO_GO / THIN_MAINTENANCE`。** 新稳定候选 `0.162.1` 已核验 package/executable，并在已授权续接中通过唯一一次initialize/account-read；随后唯一一次原P10得到7/9、`NO_GO / POLICY_NOT_ATTESTED`。P10失败原件与候选offline replay均已保存，未重试、未进入P13；P14d-C仍为 `BLOCKED_UNIMPLEMENTED`。以下F0/F1初期停止记录保留调查历史，最新结果见末节。

## 已核对的身份与来源

| 对象 | 本轮核对 | 可声明范围 |
|---|---|---|
| canonical SDK/runtime `0.154.0` | `pyproject.toml`、`uv.lock`、`integrations/codex/versioning.py` 及本地 `.venv` 两包 METADATA 一致；SDK 依赖精确的同版本 cli-bin | 依赖配置与安装元数据仍锁定 `0.154.0`；本轮未重算 executable bytes，不新增运行资格 |
| 官方 candidate `0.156.1` | 读取 retained provenance 小原件；其 SHA256 重算为 `6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af`；preflight report 重算为 `d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945` | 复用历史 executable identity **VERIFIED**；本轮只确认这两个原件内容身份，未重放全部 provenance verifier 或大 wheel/executable |
| 新候选发现 | 官方 PyPI SDK/cli-bin 与 GitHub 均发布 `0.162.1` | **已发现**，F1 准备进一步核验了 executable；未资格化 |
| 新候选身份/资格 | F1 准备完成固定 wheel、SDK dependency、RECORD/CRC/ELF、双 executable SHA256 与 PyPI publisher metadata绑定 | **身份已核验 / NOT_EVALUATED**；未执行 account/read 或 P10，不授运行资格 |

`0.156.1` retained provenance 绑定 manylinux x86_64 wheel SHA256
`84a12567ca54ba6ae4ed755911c04e7cdf658315f8719963c8daa8592d8fe068`，executable SHA256
`0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f`，以及 `openai/codex` publishing commit
`8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f`。历史 frozen literal 的错误只由 superseding provenance 修正解释，未改写历史 report。`account/read` 仍失败，离线分类 `UPSTREAM_ACCOUNT_ROUTING_FAILURE`、内部 subtype `UNKNOWN`；candidate P10 保持 `NOT_EVALUATED`。原件与完整出处见[provenance 记录](../history/2026-09-29/docs/fr03-codex-runtime-identity-provenance.md)及[重资格记录](../history/2026-09-29/docs/fr03-codex-0.156.1-requalification.md)。

## 可适用入口

官方 [Codex SDK 文档](https://learn.chatgpt.com/docs/codex-sdk)说明 Python SDK 经 JSON-RPC 控制本地 app-server，发行包绑定 runtime；自选 executable 需要明确配置。该机制与现有隔离 SDK host 的方向一致，但不证明账户路由恢复或本仓 P10/P13 合格。[官方 changelog](https://learn.chatgpt.com/docs/changelog)未提供具体 package identity，随后补查了官方发行源。

仓库 `versioning.py` 只有 canonical `0.154.0` 与有限的 `openai-codex-0.156.1-p10-v3` profile；新的版本不能直接传给现有 host。`sdk_host.py` 在 `turn` 前核对包版本、读取 bundled executable hash、执行 account/read 与 server version 检查，不应绕过。`scripts/codex_capability_spike.py` 默认执行 canonical P10，并非通用新候选入口；F1 若触发，应复用冻结 host/normalizer/rubric并作最小有限 profile 适配，不直接运行该脚本假定候选已切换。

SDK 研究入口继续受 P10→P13 资格约束。研究准备可推进已有 Hosted/proposal 交接的后继适配；`application/hosted_inputs.py` 仍消费冻结业务输入，不能据已有 HM 接受证明新候选表示已经可用。不新增 CLI fallback、双栈或 D0.x 排障。

## 最小后续范围与未解决项

1. 固定已发现的 `0.162.1` 候选，补齐 SDK wheel 内精确 runtime dependency 与来源 commit 的对应，以及完整 attestation 核验；不重跑 `0.156.1`。
2. 触发后在隔离环境核对 package/executable/provenance；沿已有原件/verifier复用可核验部分，改变候选字节才补做对应身份核验。安装增长、wheel/executable、输出及失败留证空间必须按真实宿主卷预留。
3. 有真实调用授权与可用预算后，只执行一次最小 account/read；失败立即留证、记 `NOT_EVALUATED` 并停止。预检 PASS 才执行一次原 Code Mode-aware P10 v3：`gpt-5.6-sol`、`max_attempts=1`、9/9；之后按既有资格依赖决定 P13，P14d-C 单独处理。

F0 本轮只执行调查；用户随后已授权 F1 一次最小预检与预检成功后一次冻结 P10。该授权不代表已执行或已有合格证据；候选依赖与接口材料须先准备完成。候选身份、隔离输出、宿主卷预算和额度授权已补齐；现有scratch未满足本轮预算与隔离布局；独立account/read的最小预算仍待核算；未知量未补写为零或已批准，耗尽的 HM campaign 额度不可续用。现有 F1 范围授权如后续记录已明确授予，应按实际范围复用，不重复请求。

关键阅读材料：`AGENTS.md`、[实施与恢复约定](../guides/implementation-discipline.md)、[FR-03 状态](../status/fr03.md)、研究指南 §5.5、实施计划 F0/F1、历史薄维护政策及上述两份 provenance/requalification 记录；源码核对限于版本映射、SDK host、P10 入口与 Hosted loader。身份原件核对不新增科学或工程资格结论。

## 官方发行补查

已读取 [SDK PyPI 0.162.1](https://pypi.org/project/openai-codex/0.162.1/)、[runtime PyPI 0.162.1](https://pypi.org/project/openai-codex-cli-bin/0.162.1/) 与 [官方 release](https://github.com/openai/codex/releases/tag/rust-v0.162.1)。SDK wheel 发布 digest `ebb2254a7ae97432eda6c2fe9b48b5b7f2c59c6e1ea25686a45ceca11ddec4b2`；glibc x86_64 runtime wheel `openai_codex_cli_bin-0.162.1-py3-none-manylinux_2_17_x86_64.whl`，页面大小 141.5 MB、digest `b087e5e0b2285309a56336ca0c2375105bf56ffacf00b4efec7fbd7c22b51f7b`。PyPI 页面声明 Trusted Publishing，仓库 `openai/codex`、发布 commit `52950c592404f11cc245a83a27fb02f2c23bc0c1`、workflow `.github/workflows/python-sdk-cli-release.yml`。F0 时这些仅为上游元数据；F1 后续下载、解包并核验了 wheel/RECORD/executable。PyPI publisher metadata及certificate所含发布commit已绑定，未声明独立 Sigstore 签名/透明日志核验。release 所列 background server feature/default 启动兼容修复不证明 retained account/read failure 已修复；本轮不声明该因果关系。

## F1 已完成准备与停止点

持久原件在 [候选准备根](../../artifacts/hosted-evidence/post-hm-fr03-01621-02/status.json)，[qualification 小索引](../../artifacts/qualification/fr03-codex-0.162.1/preparation-index.json)只引用该根，不复制大工件。SDK wheel `98390B`，绑定 cli-bin `0.162.1`；runtime wheel `141505894B`，executable `294415048B`。复用原 provenance verifier 的机械 wheel/RECORD/CRC/ELF/双 SHA256逻辑，其 private module 实例仅参数化本次版本，历史 verifier 源文件与原证据未改。所得 executable SHA256为 `628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1`，与 retained Hosted executable 相同；这项相同是在本次 PyPI 来源链核对后成立，未以旧 CLI 运行结果授 SDK 资格。

准备重用同一个 hosted-evidence 全局 lease。保留 Linux 16GiB / host 32GiB floor，新增预算 1GiB；下载/解包直接写持久根，未复制科学输入。既有 VHD path `C:/Users/zjw/AppData/Local/Packages/CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc/LocalState/ext4.vhdx` 与 `/mnt/c` mount沿用，guard容量检查观察 host约65.9GB / Linux约733.9GB可用。准备完成的 [guard实际退出](../../artifacts/hosted-evidence/storage-control/run-1791656156970443202-449469/exit.json)为0，wait、namespace exit和cleanup均已观察；不是资格PASS。

**停止原因是资源未满足本轮实际预算与隔离布局。** 旧1GiB池只余 `12242944B`，旧64MiB池不足本轮512MiB reservation；未删旧池内容。独立宿主mount需要本会话没有的sudo权限；bwrap可创建512MiB私有tmpfs，但noswap remount与初始mount均失败（32）。各启动的实际退出1与零runtime/account reservation事实保存于候选根 `private-scratch-launch-01/02/03-exit.json`；退出后目标再次为ext4父挂载，未留下私有tmpfs。前序网络与publisher-envelope解析失败亦原样保留，成功准备没有改写失败父记录。

当前 `account/read=NOT_EVALUATED`（0次、reservation尚未消费），P10/P13未执行，FR-03仍NO_GO。已新增有限候选profile `openai-codex-0.162.1-p10-v3`，canonical仍0.154.0。后继可独立核算一次account/read的最小写入预算与可用硬quota池（不削现floor、不重下载大包、不自动包含P10完整job），复核同卷并发预算后用 [有界准备/预检脚本](../../scripts/fr03_candidate_01621.py)执行一次预检；失败留证即停。成功后还需明确候选P10 artifact verifier的版本绑定适配，再执行冻结的 `gpt-5.6-sol`、250000 input / 4096 output token上限、900秒、`max_attempts=1`、原9/9 rubric；不自动进入P13。

### Scratch 停止依据澄清

上述512MiB是本轮完整job准备预留与本次private scratch policy，不是SDK account/read的冻结最小容量。已有Hosted namespace的 `NAMESPACE_TMPFS_BYTES` 固定512MiB并绑定mount-policy hash；SDK预检使用storage supervisor，不调用该Hosted业务namespace recipe。现有storage guard要求真实独立有限tmpfs、容量不超policy及至少1MiB可用，并未规定512MiB下限。因此可将一次account/read与后续P10资源预算分开核算，不能把本轮保守预留当作不可变SDK门禁。

只读 `findmnt` 核对发现64MiB `recovery-runtime01` 约61.2MiB可用，但实际mount options不含 `noswap`；1GiB `acceptance-pool01` 含 `noswap`、只余约11.7MiB。不能把前者称为已核验noswap池，也不能仅按空闲容量断言预检增长足够。最小后继是核对独立预检的runtime临时写路径与硬quota预算，以及可用池的真实mount能力；若满足现有守卫要求，可在既有一次预检授权内使用较小池，无需先为P10准备512MiB。本次没有启动live或改变floor。

## T8 Hosted 后继的离线开发范围

新增 [Hosted后继契约](../../src/quantos/contracts/discovery_hosted.py)与[离线管理适配器](../../src/quantos/application/discovery_hosted.py)，profile为 `hm-discovery/v1`。请求绑定design、GenerationRequest与已持久reservation，projection保存有界hash对象；prompt要求提出一条AST，不依赖未来campaign或从已有候选清单选择。旧 `hm-mvp/v1` 契约、loader与资格判断没有据此改写。

来源检查从管理所有的 `TrustedLauncherEvidenceStore` 读取真实launcher record、独立后继projection fact、真实pre-launch mount observation与raw CLI原件；复用既有单轮提取规则，核对request/design/reservation/configuration/projection/isolation绑定及原始proposal bytes。mount信息来自 `TRUSTED_PRE_LAUNCH_BWRAP_PROBE` 原件；HostObservation仍是有显式局限的自报信息，不能代替隔离观察。source receipt资格固定 `NOT_EVALUATED`，不会授予新profile历史资格。

**T8真实调用为0。** `capture` 只保存持久阻塞记录并保留unfinished reservation，不启动runtime/provider。既有真实launcher尚未发出新的后继projection fact，新profile未资格化，资源适用性亦须按所用路线重新核对；本轮交付是可审查的离线准备/原件校验接口，不能称实际generation已接通。两个owned模块最终Ruff与strict Pyright静态检查通过；没有测试、科学执行或live资格重跑。

候选脚本的 direct `prepare` / `preflight` 已要求 existing configured guard、durable root、有效全局lease与现有1GiB job预算检查；不能直接绕过supervisor。较小的独立预检预算尚未写成执行政策，本轮没有因此启动任何真实预检。

## F1 有界续接的最终结果

进一步核对[冻结storage政策](../hosted/hm-storage-recovery.md)第129–140行，独立有限tmpfs可以消耗swap；`noswap`不是SDK standalone预检的冻结谓词。512MiB完整job预留及noswap要求属于本轮先前更严准备选择。固定官方发布commit的小源码记录保存在候选根 `preflight-source-review/`：arg0 helper在隔离CODEX_HOME创建目录/锁/symlink而非复制executable；初始化SQLite也写入该持久home。SDK的临时schema checkout只在未知runtime或特定后继选项触发，initialize/account-read不使用它。

因此没有要求管理员新挂载。复用现有64MiB `recovery-runtime01` 独立硬quota，原16GiB Linux / 32GiB宿主floor与全局lease不变。独立预检预算32MiB持久增长、scratch预计≤4MiB，实际初始化持久文件合计2819538B、scratch净增长0；认证原件只读bind、不复制，host根只读，仅本次authority输出、scratch及机械lease核验所需单一锁文件可写；supervisor白名单不带Tushare或其他父token环境。

第一次内层只读布局启动退出1、没有到达SDK/account reservation，其[守卫退出原件](../../artifacts/hosted-evidence/storage-control/run-1791658010829212333-458730/exit.json)保留。机械lease检查需要O_RDWR打开锁文件，增加该单文件bind后执行真正一次预检：[account/read原件](../../artifacts/hosted-evidence/post-hm-fr03-01621-02/account-read-report.json)记录initialize PASS、account/read PASS、1次、2.73062026896514秒、thread0/turn0；[后继状态](../../artifacts/hosted-evidence/post-hm-fr03-01621-02/preflight-status.json)引用旧准备状态，未覆盖失败或初期停止记录。实际guard退出0、wait/namespace exit/cleanup已观察，lease释放。这只证明本次候选账户读取可用，不授P10资格，也不解释旧版本失败根因。

随后使用[有限候选P10 wrapper](../../scripts/fr03_p10_candidate_01621.py)：私有runner实例只参数化固定0.162.1身份，沿既有SDK adapter指定有限candidate profile及已核overlay；同实例重用原offline artifact verifier。旧runner源码、canonical锁与原9/9 rubric未修改。固定gpt-5.6-sol medium、输入250000/输出4096上限、900秒、max_attempts1；9个冻结输入总7902B。完整job预算256MiB持久增长、整个64MiB scratch硬容量及1.5GiB内存预留；host/Linux容量、VM内存与root cgroup无memory.max接口的事实均保存在[资源记录](../../artifacts/hosted-evidence/post-hm-fr03-01621-p10-01/resource-review.json)。执行中scratch净增长超过32MiB初期估计，真实64MiB内核上限与完整job预算没有改变；该偏差保存在状态，不补写为估计成立。

**P10最终7/9、NO_GO。** [状态与真实用量](../../artifacts/hosted-evidence/post-hm-fr03-01621-p10-01/status.json)记录classification `POLICY_NOT_ATTESTED`，失败项 `SANDBOX` 与 `FAILURE_RECOVERY`；5个command lifecycle完整，Code Mode发起/嵌套dispatch仍UNKNOWN，不补写为已证明。单个SDK turn本身完成、attempt1/retry0，输入16741、输出102、cached16384。候选offline verifier与live summary一致；[实际guard退出](../../artifacts/hosted-evidence/post-hm-fr03-01621-p10-01/candidate-p10-supervisor-exit.json)为1，wait/namespace exit/cleanup均已观察，lease释放。正式bundle只在authority根保留；[qualification索引](../../artifacts/qualification/fr03-codex-0.162.1/p10-index.json)不复制大工件。

单次资格链已耗尽并停止：没有再次account/read预检、没有模型retry，没有P13或任何科学执行。FR-03保持NO_GO；后继研究依指南5.5沿已有Hosted交接准备推进。两个候选脚本最终Ruff/Pyright通过，未另运行测试或资格矩阵。
