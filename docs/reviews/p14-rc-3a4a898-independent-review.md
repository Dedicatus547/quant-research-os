# P14 RC 文档权威表述独立复审：3a4a898

日期：2026-09-29。独立结论：**APPROVE**。

| 身份 | 精确值 |
|---|---|
| reviewed_commit | `3a4a898f74ce2f60a14d2a69250024e92a4378c1` |
| reviewed_tree | `f08ae13455a74c5f1478c506253f52df54eb7497` |
| reviewer | Codex，`gpt-6-sol`，reasoning `high` |
| reviewer task path | `/root/p14_rc_independent_review` |
| context | 全新独立上下文；未参与目标提交的修改 |
| production implementation | `e318dc450e5c02f1120da7644250767bf682b6f9` |
| frozen documentation source | `9e2fc41a41f2d2b253e04c67b10519e6926c79dd` |

本审阅由用户授权的独立子代理执行，先读取 `AGENTS.md` 和 `PLAN.md`，再独立取得下述核验证据。未将主代理的预检、准备文件或审阅结论作为独立证据。本审阅只读项目，在 `/tmp` 写入审计脚本和本报告；没有编辑项目、Git stage/commit/tag、联网、采集数据、调用 live Agent 或启动其他子代理。未读取或输出任何 secret 值。

`APPROVE` 的对象是上表精确提交的 RC 文档权威表述。它确认文档修正消除了完整原始树的无范围限定 byte-exact 声明，并准确沿用现有工程资格、报告和权限边界；它不重新资格化实现。

## Findings

| 级别 | 结论 |
|---|---|
| 阻塞 / required fix | 无 |
| 权威边界或证据身份缺陷 | 无 |
| 信息项 | 累计 `e318dc4 → 3a4a898` 的 `git diff --check` 只报告归档原件 `docs/history/2026-09-29/docs/fr03-codex-account-routing-diagnostic-v2.md` 第 3、4 行的两个行尾空格；这两处是原文已有的 Markdown 换行 bytes，已独立确认与 `9e2fc41` 相同。后继 `1e76aff → 3a4a898` 的 `git diff --check` 通过。保留冻结原件身份不需修订这些字节。 |

## 实际执行的核验

工作目录始终为 `/home/zjw/quant-research-os`。Python 审计与 verifier 使用现有 `.venv/bin/python`，调用时移除 `TUSHARE_TOKEN` 并设置 `PYTHONDONTWRITEBYTECODE=1`；DQ verifier 和外部输入核验的进程从启动时设置 `PYTHONHASHSEED=0`。

| 检查 / 实际命令 | 结果 |
|---|---|
| `git rev-parse HEAD`；`git rev-parse 3a4a898f74ce2f60a14d2a69250024e92a4378c1^{tree}`；审阅前后 `git status --porcelain=v1 --untracked-files=all` | HEAD/tree 与上表相等；工作区始终干净 |
| `git diff --name-status e318dc450e5c02f1120da7644250767bf682b6f9 3a4a898f74ce2f60a14d2a69250024e92a4378c1`；两提交 `git ls-tree -r` 对照 | 根 README、PLAN、`docs/` 之外的 591 个已跟踪文件，其 blob 与 mode 全部相同；无非文档增删或变化 |
| `git diff --name-status 1e76aff09b03c4cda2d821c2f7b09257659151da 3a4a898f74ce2f60a14d2a69250024e92a4378c1`；对应 `git diff --check` | 后继涉及 10 个 Markdown 文件；diff check exit 0 |
| `env -u TUSHARE_TOKEN PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/quantos-p14-rc-3a4a898-independent-check.py` | 最终审计 exit 0：Git 边界、归档、完整文件集合/size/SHA-256、报告 canonical encoding/content hash、双根 raw/projection/principal、实际 ValidationReport gate facts 全部核对通过 |
| `env -u TUSHARE_TOKEN PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/p14c_qualification.py --verify artifacts/qualification/p14c/sha256-d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a` | exit 0；`p14c-qualification-verification/v1`；`SUCCEEDED / PASS`；精确资格 hash `d0412a30…5836913a` |
| `env -u TUSHARE_TOKEN PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 .venv/bin/python scripts/p14dq_qualification.py verify-bundle --artifact artifacts/qualification/p14-dq-qlib-drain-e318dc4/sha256-f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a` | exit 0；`p14dq-bundle-verification/v1`；`SUCCEEDED / PASS`；`external_inputs_reverified=false`，按 bundle 检查层级记录 |
| 同一 seed-0 Python 进程导入 `scripts.p14dq_qualification`，调用 `verify_external_inputs(workspace=Path.cwd(), snapshot_path=workspace / SNAPSHOT_RELATIVE_PATH, view_path=workspace / VIEW_RELATIVE_PATH, release_report_path=workspace / UPSTREAM_RELEASE_RELATIVE_PATH)` | exit 0；实际 snapshot/view/upstream release 全部只读核验；返回 `bindings == report.external_bindings`，`external_inputs_reverified=true`；没有采集或重建数据 |
| 同一进程调用 `capture_runtime_fingerprint()`、`_require_v3_contract_approval()`、`_require_amendment_approval()`，并计算当前契约/批准文件 SHA-256 | runtime 与报告相等；批准记录及精确原始文件哈希相等 |
| 使用 `CampaignSelectionReport.model_validate_json` 核对每根自然选择报告、内容 hash、完整候选 dispositions 和 trial bindings | 两根各有两个候选、两个 trial bindings；两项均 `NONPASS_VALIDATION`；零 scores、selected candidate 为 null |
| 对重点 9 页中的相对文件链接逐一检查路径存在 | 74 个链接通过，包含授权工作区内的 artifact 链接；该结果不表示新克隆包含 gitignored artifacts |
| 只读检查两个 retained full-verifier 日志和三份回归日志的终态/摘要，计算日志 raw SHA-256 | 精确终态和计数见下表；没有重跑这些操作 |

审计脚本 raw SHA-256：`a270317c15917d881abf45b90c0e7b5c236f7846154746ee329549583d7a6f43`。脚本属于本次 `/tmp` 核验材料，不是生产资格产物。

重点页为 `README.md`、`PLAN.md`、`docs/releases/README.md`、`docs/releases/p14-rc-v1-equality-correction.md`、`docs/reviews/p14-rc-documentation-successor-review.md`、`docs/status/README.md`、`docs/status/p14.md`、`docs/guides/qualification.md`、`docs/architecture/contracts.md`；同时阅读 reviews/contracts 索引、FR-03 状态、原冻结记录、契约、批准与 principal-conformance 记录，以及相关 runner/contracts/provenance/Qlib lifecycle 实现。

## 冻结原件与原始文件树

独立解析 `docs/history/2026-09-29/inventory.json`，逐项用 `git show 9e2fc41a41f2d2b253e04c67b10519e6926c79dd:<path>` 取得原文，与归档 bytes、size、SHA-256 比较。50/50 一致。原位保留的 32 个原始 docs 文件也与 `9e2fc41` bytes 一致，包含冻结契约、批准 policy 和旧 release/review 记录。

Inventory 文件自身 raw SHA-256：`a886328b84076d64cfec37e36da29fa2cfe39ff6c081f40ec9099dd2b39e7944`。

报告全部文件清单独立核验了精确集合、每项 size 与 raw SHA-256，未发现额外、缺失、hash mismatch 或 symlink。清单数不包含 `qualification-report.json` 本身；报告另行核验 canonical encoding、内容身份及 raw SHA-256。

| Bundle | 清单项数 | 含报告的实际文件数 | 每根文件数 | 双根原始差异 |
|---|---:|---:|---:|---|
| P14d-B | 1848 | 1849 | 922 | 51 个文件：50 个 `manifest.json` 仅顶层 `created_at` 不同；另 1 个 `root-evidence.json` 仅 `root_id` 不同 |
| P14-DQ | 1054 | 1055 | 519 | 69 个文件：68 个 `manifest.json` 仅顶层 `created_at` 不同；另 1 个 `root-evidence.json` 仅 `root_id` 不同 |

各根相对路径集合相同，未发现其他原始差异。独立计算了冻结 contracts 定义的 principal payload canonical bytes，两根完全相同。DQ inventory 按 runner 的 Path 排序，排除相对路径 `root-evidence.json`；仅对包含顶层 `created_at` 的 JSON object 删除该字段并 canonicalize，其余内容保留 raw bytes，嵌套字段不删除。独立计算的两根 inventory hash 与各根 `artifact_tree_hash` 完全相等。

因此当前文档中“principal byte-exact”“批准投影一致”“完整原始树不 byte-exact”的区别有实际文件证据支持。排除根 evidence 是现有 runner 的规则，根 evidence 仍由报告文件清单单独绑定，本次未放宽 verifier、浮点比较或字段域。

## 精确报告与 provenance 绑定

`qualification_hash` 是排除报告自身该字段后的 canonical 内容哈希；raw report SHA-256 包含该字段并绑定报告文件原始字节。两种身份均已独立计算，不互换。

| 对象 | qualification_hash | report raw SHA-256 | implementation |
|---|---|---|---|
| P14c retained | `d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a` | `187fba53b5870698c2593b28bee99a788863f1fe900898e4ac3781e9a70ca2dd` | `618498a64b8e46ab5c38f66ea08a03a2afdaea32` |
| P14d-B | `41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71` | `34ecdcbc3cdc92398bc6de85d586bdf08c643db5cfd6be59d9ea894bed7d5fa3` | `e318dc450e5c02f1120da7644250767bf682b6f9` |
| P14-DQ | `f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a` | `7dceffb8d8563d82e94d3bb31b5aefea3bc8d55f36f2344280681dd8568b974d` | `e318dc450e5c02f1120da7644250767bf682b6f9` |

| 绑定域 | 精确 hash |
|---|---|
| P14d-B / DQ CodeProvenance 内容 | `3e0c13bc57462fa00f7107ce6756a6eee03ba5c00108b929e5c032896eb4c43c` |
| Lockfile 原始文件 | `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca` |
| RuntimeFingerprint 内容 | `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321` |
| P14d-B contract 原始文件 | `eaa9e35b5141bc75648945718455e7b88b8ad3c2dd34df0d1f937df99e099136` |
| Approved v3 contract 原始文件 | `563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17` |
| v3 approval record 原始文件 | `6010a6c2d53727fabce7e3a6caf9cc5f0dd9dfd2ced131e2a524cd1993f0aa74` |
| Runtime amendment 原始文件 | `a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce` |
| Amendment approval record 原始文件 | `26e331ce4a2df4664995e23f615a205b817bd3318b4ea9e43c9649fc32577ca9` |
| Snapshot authority identity | `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` |
| Qlib view authority identity | `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` |
| Upstream release report 原始文件 | `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca` |
| DQ ExternalBindings 内容 | `cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3` |
| P14d-B root principal，两根相同 | `ea4e80d3248a25ebf6c978fd58411c20b9da3e2b4a93681a4948a2ff2421164f` |
| P14d-B report principal summary | `db5c8a0dfe0672fb5c326971d44bd9e8d29c720bb998c281c42c1b0ada96ab64` |
| DQ root principal，两根相同 | `affa9baefe5880b1bc54886e1c48688a4be5fcb92f41fd699a74326ef1abaf9b` |
| DQ report principal summary | `4bfb5d37b380e9da08f205b8a23b213596b97d1f17b9185983922e97a1fbb64b` |
| DQ projected tree inventory，两根相同 | `d459a2d9d1e5d6995647521f9ac9ad698a078fa5fab01f40cf28de6c479d1be2` |

两个 bundle 的 CodeProvenance 都记录精确 `e318dc4` 与 `worktree_clean=true`。报告、bundle 的 frozen lockfile 及当前 lockfile bytes 相等；当前进程重新捕获的 RuntimeFingerprint 相等。DQ runtime-environment 为 `p14dq-runtime-environment/v1`，绑定上表 amendment/fingerprint，`python_hash_seed="0"`、`hash_randomization_enabled=false`。批准记录的历史实现绑定与 `APPROVE` 字段均经现有只读 guard 核验，契约仍保留原始 draft 文案而由单独批准记录授予使用权。

实际外部输入位于冻结规定路径，分别为上述 `sha256-<snapshot>`、`sha256-<view>` 与 `artifacts/releases/data-qualified-v0.1-f3fc768/report.json`。现有只读 verifier 核对实际完整文件、canonical metadata、数据质量、Qlib lineage/health、release 状态与 non-vintage 限制，所得 ExternalBindings 与报告整体相等。

## 工程结果、研究结果与权限

P14d-B 报告为 `SUCCEEDED / PASS`，两根共 54 个 negative cases、6 个 restart cases，每根分别 27、3；canonical cases 为 `SELECTED`、`NO_SELECTION`、`FAILED_NOT_EVALUATED`。Synthetic SELECTED 和 `READY_FOR_SEALED_CONFIRMATION` 仍限定为选择工程路径，未被提升为市场选择或 sealed qualification。

DQ 报告为工程 `SUCCEEDED / PASS`。两根共 54 个 P14d negative cases、24 个 DQ negative cases、6 个 restart cases；每根分别 27、12、3。

两根自然选择报告内容身份均为 `f80fa8b2ed7f5bd43fdaecb7c54d43089f2f6c13cf931d661beacc0681b1c943`，真实研究结果为 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`；`eligible_candidate_count=0`、`selection_performed=false`、无 selected candidate、无 selection event、sealed authority 为 false。每根完整分母为两个冻结候选、两个独立 execution identities、两个 trial bindings，均为 `NONPASS_VALIDATION`，无 score。

| 冻结自然候选 | 实际 ValidationReport 内容身份 | 两根均核对的结果 |
|---|---|---|
| `b7ca426ad868e15827365aa2bfcceb20870893a91add47713ff88dc2a43d444f` | `a4558c227d5150ebebe8bd9603503b2f2d17559963ba5e404e37707388f23665` | `SUCCEEDED / REJECT`；TrialOutcome `SOFT_REJECT` |
| `f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96` | `d7c8bf7d3e94d32feffffe40b1fe880c3ef8ee9de2b6017eadfbd02151049fd2` | `SUCCEEDED / REJECT`；TrialOutcome `SOFT_REJECT` |

实际四个 ValidationReport 文件的十一项 gate facts 与 qualification evidence 相等：仅 `G5_OUT_OF_SAMPLE / SOFT / REJECT / SOFT_THRESHOLD_NOT_MET` 拒绝，其余十项 PASS，无 NOT_EVALUATED。完整候选 manifest `b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae` 和 family `fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb` 未缩减。批准 v3 的例外由完整 gate allowlist 决定，`QLIB_EXECUTION_FAILED`、PIT、artifact 或缺失证据失败仍不能使用该例外。

当前措辞没有把工程 PASS 转化为研究 PASS、alpha、盈利、投资适用性或 sealed confirmation。Live Agent 保持 `NOT QUALIFIED / BLOCKED`；FR-03 保持 `NO_GO / THIN_MAINTENANCE`；P14d-C 保持 `BLOCKED_UNIMPLEMENTED`；sealed、vendor-vintage PIT 与 unrestricted autonomous research 未获资格，来源仍为 `SINGLE_SOURCE_NON_VINTAGE`。Scripted/Replay proposal 和 receipt 不提升 Agent 输出的证据权威。

只读实现核对确认 `model.fit → recorder async queue wait → clear stopped queue → SignalRecord.generate` 生命周期修复。当前安装的 Qlib `Position.calculate_stock_value()` 仍通过含 set 顺序的 `get_stock_list()` 累加；`qlib/backtest/position.py` raw SHA-256 为 `b91246317db2eb6fefccc307441850ce919d93d3d69961120211b076d8485c26`。文档保留 seed-0 范围，未声明任意 seed 下确定性。

## 继承的 full-verifier 与回归证据

以下是本次独立读取并计算 hash 的既有日志，不是本次新执行的 full verifier 或回归。其精确 report 终态、原冻结记录及未变化的生产文件共同支持仅文档修订继承已有证据。

| 保留日志 | 本次观察到的终态 / 摘要 | raw SHA-256 |
|---|---|---|
| `/tmp/p14d_e318_final_verify.out` | `p14d-qualification-verification/v1`；`41a27c6f…fadc71`；`SUCCEEDED / PASS` | `5140f27dbf5f7939d275f46963521972e4069d46bf04d8713618c008a50e2ac5` |
| `/tmp/p14dq_e318_verify.out` | `p14dq-qualification-verification/v1`；`f912cb0b…64d38a`；principal `4bfb5d37…fbb64b`；`SUCCEEDED / PASS` | `6f7f43fb526f8db60dc3cd7deb468a3f32cac888c06c6e344b41e276fdf0c201` |
| `/tmp/p14_rc_final_plain.out` | 699 passed，113 warnings，197.66s | `fd635b1daf4bb335777f9de2efd6602a01a2dd75a6024acba0728c859d6fce2e` |
| `/tmp/p14_rc_final_hashseed0.out` | 699 passed，113 warnings，197.00s | `be1fbfcb57fab4bcf68a1748321fabcc7b1bfe58c689e95c748a739f7722b887` |
| `/tmp/p14_rc_final_coverage.out` | 699 passed，113 warnings；85.01%，达到 85.0% 门槛 | `22f6e18996c62c7fc160431f5d5f2cbece924fe3d32f3b644afa52df32961783` |

只读检查现有 full-verifier 实现确认：P14d verifier 在完整 bundle/provenance 检查后重建双根；DQ full verifier 检查 seed/批准、精确 clean implementation HEAD、runtime 与实际外部输入后重建双根并比较 evidence。文档提交 HEAD 不等于 `e318dc4`，当前资格指南明确要求在独立干净 implementation checkout 执行 full verifier，并正确区分 bundle、外部输入与 bottom-up 层级。

本次没有把 retained 日志改写为自己执行的新重建；本次运行的 DQ `verify-bundle` 明确仅是 bundle integrity，而单独执行的 `verify_external_inputs` 仅证明实际外部输入核对通过。现行文档没有混淆这些层级。

## 未执行范围与后续步骤

本次未运行 pytest、新软件回归、Ruff/Pyright、新 P14d-B/P14-DQ Qlib 双根重建、qualification 生成、数据采集、runtime requalification、live Agent、sealed 或研究选择。完整 verifier 和回归结论继承上表既有日志与原冻结记录；本次取得的是独立文档复审、保留产物完整性和实际外部输入核验结果。日志是保留本地证据，本审阅不把它们解释为本次重新执行的证明，也不推导超出冻结 lineage/environment 的资格。

该精确 reviewed_commit 的文档复审已通过，允许后续开展仅发布管理性质的 RC tag/release-marker 记录。登记应明确绑定本 reviewed_commit、production implementation、精确 reports 与本结论，继续保留原冻结/失败/批准记录，以及上述工程、研究和权限边界。后续登记提交应记录它的自身完整 SHA，并明确它是记录本审阅结果的后继，不能自动声称本独立审阅已覆盖登记提交。

RC marker 只能表示在这些条件内的发布管理状态，不能授予新的生产、研究、Live Agent、sealed、盈利、投资适用性、vendor-vintage 或无限制自主权威。若后续修改生产实现、冻结输入、契约、policy、runtime/environment 或比较规则，本结论不能跨绑定沿用；需要相应独立资格与审查。
