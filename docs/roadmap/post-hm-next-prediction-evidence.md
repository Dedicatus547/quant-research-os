# 后继预测证据接口（D05 / N2）

2026-10-12。依据 [N1 五失败归因](post-hm-next-failure-diagnosis.md)，四份完整 native 预测满足新语义设计前提；signal失败继续缺证。本次交付独立版本 contracts/application/管理入口，旧 ResearchResult、导出门、比较入口、Validation、P14c及历史失败保持原义。未重训、运行测试、调用模型或执行新导入/核验/比较。

## 规则与来源

[PredictionEvaluationProfile](../../src/quantos/contracts/discovery_prediction.py) 固定新规则版本及规范hash，并绑定实际新 verifier identity。调用方必须在分析前给出：完整 ordered `expected_dates`、全部 singleton `execution_request_hashes`、snapshot/view/research-policy/实际code/lock/Qlib身份、`min_defined_fraction`及`min_common_days`。本实现没有为研究擅定覆盖下限或改善幅度。四份新解释仍属回顾性探索，改名或新hash不产生未见数据资格。

verifier identity 与旧实际运行code04分开：包含新adapter/contracts、复用的数据/PIT/split源码、Qlib/pandas/SciPy实际统计实现文件hash及运行版本。依赖集合有意包含相关schema和复用package的源码；不是以总体commit替代依赖。实现完成后应从固定代码环境生成identity再冻结profile；源实现或环境改变须重新说明采用范围，不能给旧证据直接换标。

`PredictionImportSource` 为显式原件路径/hash输入：旧request/outcome/receipt/resolved、research policy（可来自原冻结design/batch，避免捏造旧独立policy文件）、实际workflow reservation/completion、原management退出观察、source capsule/inventory/独立workspace、native split hash、snapshot/view/signal根与signal hash。缺signal/native保持 `SOURCE_MISSING`/`EVIDENCE_MISSING`，不需要伪造source。

## 独立导入、核验与消费

[application/discovery_prediction.py](../../src/quantos/application/discovery_prediction.py) 提供：

```python
prediction_verifier_identity() -> dict[str, object]
build_prediction_evidence(source, profile) -> PredictionEvidence
publish_prediction_evidence(source, profile, output_root) -> Path
verify_prediction_evidence(path, *, expected_hash, source, profile) -> PredictionEvidence
compare_prediction_evidence(profile, sources, references) -> dict[str, object]
```

核验先绑定request/receipt/outcome、frozen cohort、resolved与原source capsule/独立clean Git/inventory，再复用 `verify_snapshot`、`verify_qlib_view`、quality及硬PIT机械重建、signal原件核验和 `verify_model_data_split`。原workflow即使因旧export失败，原native与sample审计仍可独立采用。实际test样本index hash必须从原预测键重建一致，不能以purge配置字段代替真正DatasetH样本；source03未purge产物不会满足source04 profile。

预测/标签原键必须唯一、完全对齐，daily timestamp、完整日历与历史membership逐键核对；预测非有限、标签Infinity、source/hash/PIT不成立都拒绝，不能归为统计无定义。只允许原生NaN标签从有限配对中排除；完整原行数、有限配对数、逐日NaN数、raw key hash、被排除键hash及原始native文件hash均保留。canonical数据仍是immutable Parquet snapshot，Qlib view仅为核验绑定的派生缓存。

IC和Rank IC通过官方Qlib `calc_ic` 从原预测/标签精确重建；不新增统计执行器、模型、Trainer或组合会计。每日期保留native value/state，并单列 mathematical value/status/reason。有限配对少于2、预测常数或标签常数时，两类数学统计值为空；即使native Pearson有限也不改为有定义。非退化输入上的无解释NaN、原生统计Infinity或重建不符是证据拒绝。原NaN文件不改字节，不填零、前向填充或删日隐藏。

publication保存小型immutable manifest/evidence/source/profile/verifier identity；受控大型原件保持原根与原hash。独立verifier从原件重新完成来源、数据、PIT、split、键/日历与统计核验，再逐字比较后继payload；不消费manifest自报PASS，也不要求旧ResearchResult成功。所有输出根均须与原件存储分离。profile/manifest中无策略PASS域；旧结果、原错误码/退出记录仅通过hash引用。

compare固定profile全部请求分母，每请求均保存 `SOURCE_MISSING`、`EVIDENCE_MISSING`、`SOURCE_VERIFICATION_REJECTED`、`COVERAGE_REJECTED`、`COVERAGE_ADMITTED`或`COMMON_DATES_INSUFFICIENT`及reason。只对机械核验且满足各自覆盖要求的候选取共同数学defined日期，主值为 `primary_common_rank_ic_mean`；`own_dates_rank_ic_mean_sensitivity`仅为敏感性展示。共同日期不足时主值为空，标签原件不一致拒绝比较。共同日期完整列出；未定义日期仍在各自完整日历证据中。此窄接口不作方法最高值或投入裁定，方法/机会完整映射由主agent的批次适配接入。

## 运行材料与持久记录

[run-materials.json](../../artifacts/post-hm-next/prediction/run-materials.json) 已组装四个failed-native source descriptor及全部10个原singleton请求引用。来源descriptor是可审阅输入材料，不是新导入、资格或新统计结果；其本身hash均在材料中列明。其余候选的source/evidence可在同一冻结cohort中补齐，缺失仍留在分母，不自动从cohort删除。调用方仍须决定覆盖参数和冻结profile。

独立入口 [post_hm_prediction_evidence.py](../../scripts/post_hm_prediction_evidence.py) 有 `identity`、`import`、`verify`、`compare` 子命令：

```text
identity --output <durable-identity.json>
import --profile <canonical-profile.json> --profile-hash <sha256>
       --source <canonical-source.json> --source-hash <sha256>
       --output-root <independent-guarded-persistent-root>
       --operation-root <new-operation-root> --expected-new-bytes <bounded-estimate>
verify --profile <...> --profile-hash <...> --source <...> --source-hash <...>
       --artifact <sha256-directory> --artifact-hash <manifest-sha256>
       --operation-root <new-operation-root> --expected-new-bytes <bounded-estimate>
compare --profile <...> --profile-hash <...>
        --inputs <canonical-input-map.json> --inputs-hash <sha256>
        --operation-root <new-operation-root> --expected-new-bytes <bounded-estimate>
```

compare输入map的schema为 `prediction-comparison-inputs/v1`，`entries`逐个列全冻结请求。entry含 `execution_request_hash`，已取得时另有 `source_path/source_hash`与`artifact_path/artifact_hash`；缺项使用null，不能省略请求分母。所有输入由明确hash选择，实际调用使用主仓既有`.venv`并明确将当前固定源码根置于PYTHONPATH；不安装新依赖。

除便宜的identity输出外，CLI需复用既有配置的host storage guard及有效lease，要求调用方提供完整增量估算；没有以WSL free替代真实宿主卷容量。完整data/PIT verifier会扫描受控源，成本尚未实测；未来执行前须按原输入、并发保留和安全空间核对既有预算。本次没有为性能统计调用这些verifier，也没有新增另一套配额/门禁。

有限layout检查确保可写根不进入原件存储；正式操作先保存prelaunch，再写capacity、结果/失败及completion。receipt记录入口真实返回码；外层进程退出观察单列，不把返回意向或进程存活当实际退出。中断未由入口处理时返回码为空；没有退出原件时不补写。API调用方承担同一持久记录与预算责任。已存在相同immutable发布可经重建采用，不覆盖冲突输出。

## 实际核对与限制

仅对3个新文件使用锁定Ruff和strict Pyright作静态检查；CLI `--help`真实退出0，普通Qlib/Gym包导入warning单独留存。没有执行identity生成profile、import、verify或compare，没有读取新的大型预测或生成第二轮结果。

静态检查失败与恢复记录位于 [prediction](../../artifacts/post-hm-next/prediction/)：初次Pyright继承worktree内不存在的`.venv`设置，随后明确主仓环境；一次配置绝对include被工具忽略的退出0列为未实际覆盖，不冒充通过。局部类型/lint发现修复后，最终实际范围与退出见static交接。没有测试、全CI/HM或科学重跑。

本交付是已实现的后继接口及准备材料；**运行端独立核验/发布/消费尚未执行，不能宣称首轮后继证据已准入或新比较已经完成**。signal旧根因仍UNKNOWN。完整方法/机会适配、运行覆盖参数与新运行授权由主agent继续衔接。
