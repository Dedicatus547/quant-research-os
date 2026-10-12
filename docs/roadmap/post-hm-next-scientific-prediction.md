# 十二候选的跨来源预测 cohort

2026-10-12。新科学阶段已有用户明确授权；本接口保留首轮旧八来源、执行新四候选，不新增LLM调用或测试。沿用[单来源预测证据](post-hm-next-prediction-evidence.md)的严格v1域，新增独立 [cohort契约](../../src/quantos/contracts/discovery_prediction_cohort.py)、[cohort适配](../../src/quantos/application/discovery_prediction_cohort.py)与[管理入口](../../scripts/post_hm_scientific_prediction.py)。科学完成后的首次导入发现D05两项metadata绑定错误，有限修复如下；科学执行核心、原来源、失败、科学门槛均未改。

## 事前冻结及实际来源

现行政策原件是 [authorized-comparison-policy-02.json](../../artifacts/post-hm-next/science-02/authorized-comparison-policy-02.json)，原始字节SHA256为 `65e48c123d53c50b680a80313c0cba9844def97eb07f0657141bd5365a10831b`。它保留0.9覆盖、600共同日期、0.002有实际意义的LLM增量及300秒生成入口/14,400秒新科学manager时限；完整增长估计依据实际保留体积从20GiB改为6GiB，前身原件保留。数值由主agent在用户新科学授权内事前选定，并非用户逐值指定。货币成本仍unknown，不作货币优越性裁定。

稳定准备API：

```python
policy = policy_from_design(PredictionFileSource(path=policy02_absolute, sha256=policy02_raw_sha))
cohort = pure_cohort_prepare(service, policy=policy, expected_dates=calendar_726_dates)
```

service必须已核冻结wrapper、科学declaration与来源采用计划。pure接口消费其cached `ScientificVerifiedAdoption`：旧八项使用旧实际request；新四项使用 `service.task_request`，按实际code/lock/Qlib tuple建立各自独立 `PredictionEvaluationProfile`。cohort绑定scientific declaration、wrapper、来源plan/dependency hash、完整12个target→actual request/source subtask映射、726日期、政策及新的跨来源核验实现身份。旧code04与新科学code不被混成一个v1 profile，不制造新request或receipt覆盖历史来源。

准备只读取政策及核验实现身份、消费已核来源映射，不解析预测/标签、不执行data/PIT或读取新分数。CLI构造service时会核原generation/plan/native文件hash，仍不解析预测。科学manager已将准备步骤置于新science run之前；科学engine源码和统计adapter身份可分开固定，不因统计adapter晚成重训。政策/来源/日期先冻结，统计实现只允许在首次质量消费前机械完成身份绑定，不能根据新分数改规则。

## 发布与独立比较

`assemble`在真实结果出现后按actual request/outcome/receipt、workflow reservation/completion、native split与signal构建explicit source descriptors；旧无native的SOURCE_INCOMPLETE保留source missing/null。新research-policy小文件是从原冻结wrapper明确投影的后继输入，记录wrapper来源，不伪称历史失败时已有独立policy文件。

`import`逐来源复用D05 `publish_prediction_evidence`，已完成候选独立落盘；原件仍保留原hash和来源。比较重新调用D05 `verify_prediction_evidence`从实际原件完成data/PIT/split/keys/native stats重建，不消费manifest self-PASS或hash摘要代替核验。硬来源/PIT/完整性失败是拒绝；合法常数输入无定义保留原值与数学null。

各自profile分域，比较则对来源核验及覆盖准入的不同结构取同一global共同有效日期交集。主值为共同日期Rank IC mean，各自均值仅敏感性。全12候选和15机会保留，重复来源共享一个候选结果并保留方法归属；共同日期不足或方法无可比较结果时增量为空。各方法最高共同均值及LLM减两基线较高最高值按冻结规则报告，旧Validation/P14c不改。

旧八项标为 `REUSED_HISTORICAL_ORIGIN`，新四项为 `NEW_SCIENTIFIC_EXECUTION`。科学计数按实际request-bound outcome观察分域；没有退出/attempt/resume证据时保留null，不把attempt编号当完整执行次数，旧预算不重新计费。生成计数复用已核wrapper的同scope原件。新科学时间观察必须从prelaunch→completion绑定到本declaration、wrapper和actual science code；费用unknown与墙钟观察分别表述。投入判断是冻结政策上的回顾性资源建议，不授予方法优越性、策略PASS或自动后续额度。

## 管理入口

所有子命令公共参数：

```text
<fixed-source python> scripts/post_hm_scientific_prediction.py <command>
  --generation-root <A-root> --generation-hash <sequential-wrapper-hash>
  --execution-root <science-execution-01> --workspace <scientific-capsule/workspace>
  --snapshot <explicit-snapshot> --view <explicit-view>
  --declaration <v2-declaration> --declaration-hash <sha>
  --output-root <independent-output> --operation-root <new-durable-operation>
  --expected-new-bytes <stage-increment-estimate>
```

| 子命令 | 附加参数 | 输出 |
|---|---|---|
| `prepare` | `--policy/--policy-hash`、`--calendar/--calendar-hash`（日历原字节hash）、`--predecessor-cohort/--predecessor-cohort-hash` | `cohort.json`、`profiles/sha256-*.json`、顶层`cohort-repair.json`、operation result |
| `assemble` | `--cohort/--cohort-hash`、`--cohort-repair/--cohort-repair-hash`、`--historical-management-exit/--historical-management-exit-hash`、`--new-management-exit/--new-management-exit-hash` | source index、逐候选真实source descriptors、后继policy投影 |
| `import` | `--cohort/--cohort-hash`、`--cohort-repair/--cohort-repair-hash`、`--source-index/--source-index-hash` | immutable evidence及完整12项evidence index；逐候选result立即持久化 |
| `compare` | `--cohort/--cohort-hash`、`--cohort-repair/--cohort-repair-hash`、source index与evidence index各path/hash、`--new-science-completion/--new-science-completion-hash`、`--new-science-prelaunch/--new-science-prelaunch-hash` | content-addressed `report.json`，绑定前身cohort与repair hash |

四步输出根采用独立兄弟目录，不能进入原件存储；修复轮formal manager根使用 `prediction-cohort-02`、`prediction-sources-02`、`prediction-evidence-02`、`prediction-comparison-02`及各自operation根，保留全部01原件。prepare小型输出预留1MiB；后继步骤按实际完整增长/既有预算给定估计，不重复预留整笔6GiB。主仓既有`.venv`、固定统计源码PYTHONPATH和既有host guard/有效lease复用；`--workspace`仍是原科学code33b0的冻结workspace，declaration不变。不安装依赖，不把WSL free当宿主容量，不与占用global lease的作业并发。

正式操作从prelaunch开始持久化capacity、结果/失败、completion与postjob wall/CPU/RSS。入口返回码与外层实际进程退出观察分开；中断或未观察退出不补写。完整data/PIT成本由真实操作计时保存，不为测量额外重跑。

## 实际核对与交接

[保留检查与接口材料](../../artifacts/post-hm-next/science-02/prediction/)记录仅三新Python文件的Ruff、strict Pyright、CLI help和真实policy02小metadata采用。最终各退出0；初始局部类型/格式发现及修正保留。普通QLib optional-model/Gym导入信息不触发安装新依赖。

首轮正式科学由manager完成，形成九个native完整来源与三个source missing。首轮import管理入口实际0，九来源全部在data/PIT/native前因`ValueError`拒绝，未发布证据；其UNAVAILABLE比较及失败保留。诊断只观察小metadata，精确定位`RESOLVED_SOURCE_BINDING_MISMATCH`和其后的`ACTUAL_WORKFLOW_STAGE_BINDING_MISMATCH`。

第一个错误把resolved的候选派生authoring哈希与request的基础authoring哈希直接等同。修复要求显式`base_authoring: ExperimentAuthoringSpec`；其全hash必须等于request.authoring_hash，再机械调用原`QuantosResearchExecutionAdapter._authoring`纯方法，以窄context读取基础authoring而不construct执行器，核派生全hash与experiment_id。D05 build/publish/verify/compare均接受keyword；缺输入硬拒绝`BASE_AUTHORING_REQUIRED`，不猜文件。科学接口从已核wrapper自动传基础authoring；通用CLI由主agent接显式canonical输入path/hash。

第二个错误只对workflow inputs求hash，原生产者实际绑定request、runtime、stage、inputs与固定recovery policy完整envelope。修复复原完整哈希并严格核reservation runtime与既有`capture_runtime_fingerprint()`重建值相等；原data/PIT/split/键/统计/覆盖/完整日期核验均继续执行。受控metadata prefix在`verify_snapshot`前强制停止，修复后九/九到达该停止点，实际0；这只证明接口前缀，不授予来源或科学资格。没有读取大预测、data/PIT、重训、LLM或tests。

修复准备API为`prepare_scientific_prediction_cohort_repair(service, predecessor_reference)`，从原`21a1fce529c4c9684f5021513f013fa50cd15782dc4e6e7c892c974f564d7d6d`原件取policy/726 dates，机械重建当前profiles/cohort，仅允许verifier identity与由此产生的profile hash变化。typed独立repair记录绑定原件path/hash与新cohort hash，原v1模型默认字段与canonical bytes不改。CLI caller原policy/calendar也必须精确一致；后续assemble/import/compare均重读前身验证repair。后继统计代码须在任何新分数消费前独立固定；守卫下的正式导入与比较由manager接续，最终判断由主agent完成。
