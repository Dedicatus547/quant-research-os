# 后继顺序生成实施与交接

2026-10-12，D06/N3。政策来自[后继决策设计](post-hm-next-decision-design.md)。此页仅记录实施与静态检查，不授予研究模型调用、历史新增外传或科学执行。

已经实现独立 `hm-discovery-sequential/v2` 路径。旧 v1 contract class AST 与 HEAD 完全相同；原基础请求、singleton family、旧 baseline 默认路径和原 Hosted transport response/receipt 格式继续复用。该静态比对不是运行时 canonical bytes 回归证明。新增的 policy、attempt、history、batch wrapper、Hosted request 与 origin 均有显式 schema；不在旧 v1 model 增加默认序列化字段。

## 管理入口

准备脚本新增 `--generation-policy sequential-v2 --max-compute-units <显式正值设计cap>`；cap不是运行授权，不采用首轮余额。省略新政策时保持 `legacy-v1` 与原360设计cap。后继 exposure声明首轮报告 `b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be` 已被设计消费、2023–2025仍属回顾性；不加入指标或失败诊断。新准备产物包含 `sequential-policy.json` 和 v2 preparation inventory，模板与随机配置引用后继生成器；不会只生成新提示词。

`post_hm_discovery.py --generation-root <持久根> prepare` 接收旧的 design/三 request 参数及 `--sequential-policy <新政策原件>`。政策必须先于请求和尝试保存，不能附着到旧批次。普通 `GenerationStore` 自动识别 `policy.json`，不能经旧入口忽略后继规则。

- `reserve --request ... [--revision-of <此前响应hash>]` 先占用槽位，再原子保存 reservation+整个静态前缀。最多五机会；失败、重复、修订与中断均保留。
- `history --request ... --ordinal ...` 读取并从原件重建该槽位的原历史，不重收后来的内容。
- `capture --request ... --ordinal ... --text ... --offline-import` 明确导入；导入操作自身实际模型调用为零，不赋予 Hosted 身份。
- `capture ... --hosted-origin ...` 可复用已经留存的 Hosted origin；后继 SDK capture 没有历史绑定，因此拒绝。
- `recover-hosted --request ... --ordinal ...` 从原 source pointer、inner launch completion、record、原始 output 复读，复用现有 source verifier 生成 receipt/origin，完成同一槽位。只适用于最后一个尚未完成的槽位；无新模型调用。完整 source 缺失时保持未完成，不编造响应、退出或 usage。
- `freeze --design ...` 保存 `SequentialDiscoveryBatch`；全部 producer 原件、静态前缀和 singleton mappings 重新核验。冻结之后所有 store 写入拒绝；只拿内层旧 batch 验证后继根也拒绝。

真实 `run_post_hm_generation.py` 仍使用既有 formal lease、宿主卷 guard、隔离 namespace、私密 auth memory fd 和一次 launcher 上限。正常新生成占新槽；`--reserved-ordinal` 仅允许恢复最后一个未完成槽位、复用原 history/source pointer。launcher 一旦有原 prelaunch 就拒绝再次调用；已有完整 capture 应用上述离线恢复入口。新管理 job 的失败或恢复记录另保存在该 job 根，不改写原来源指针。

## 原件、历史与恢复语义

基础三请求由政策哈希固定，按 LLM/RANDOM/TEMPLATE 排序。第 k 个 attempt 的历史恰好是本请求前 k−1 个 reservation/response 原件的静态抽取；包含原件 hash、AST、结构 fingerprint、解析/能力准入/重复状态及安全失败分类。没有其他方法、未来响应、预测、信号失败、Validation 或回测指标。方法内静态重复和科学 batch 中跨方法共享结构的映射分别保留。

保存第 k+1 个 reservation 时，第 k 个及更早缺响应槽位永久关闭：下一份不可变前缀明确记录 `UNFINISHED/NO_RESPONSE_CAPTURED`，之后 complete/reject 都不能补写该缺口。没有虚构终止响应。最后一个尚未关闭的槽位可以恢复；已完成的失败不能改成成功，修订占新槽并引用此前同方法响应。

Hosted v2 request 同时携带 policy 与 attempt，投影独立保存 policy/attempt/history 的 canonical bytes；prompt 显示相同历史。projection inventory、launcher prompt hash、source receipt 的 request hash及 v2 origin 的 attempt hash绑定实际调用。source verifier 复读管理来源与 GenerationStore 的原前缀，freeze 再核验所有 producer，不将 proposal 当 evidence。

每个真实 runner 槽位在 launcher 之前保存 `SequentialLaunchSource`，含管理 principal、request/reservation hash及 manager/evidence/job 持久根；无凭据、auth 路径或日志原文。wrapper 同序保存 `launch_sources` 与 `launch_observations`。后者只绑定冻结当时已观察到的 job/inner launcher prelaunch/completion 与 record hash；null 表示 `UNKNOWN_AT_FREEZE`，不能当零调用。以后出现的 completion 不回填冻结观察。核验复读已经绑定的原件，不能重新收集未来 completion 后悄改报告。

## D07 与主 agent 的后续接线

D07 在 `discovery_baselines.py` 提供：

```python
def generate_sequential_baseline(
    design: DiscoveryDesign,
    request: GenerationRequest,
    policy: SequentialGenerationPolicy,
) -> tuple[str, ...]: ...
```

模板 return/rolling_mean/rolling_std/rank 分层轮转，随机 seed1729 无放回；共同空间耗尽拒绝，不能 reset。`discovery_sequential.sequential_baseline` 已作为显式策略入口调用该函数；函数尚未安装时拒绝，绝不退回旧生成器。

D07 读取 wrapper 的冻结 `launch_sources/launch_observations`，分别统计已确认/未知的实际管理模型入口与可观察重试、授权/占用候选机会、不同候选科学执行及尝试/恢复。prelaunch 意图不算已确认实际调用；provider 内部调用仍未知。后续生成报告需消费 wrapper，不能只消费旧内层 batch。

主 agent 已接入 execution service 的 `sequential_batch` 参数：service 使用旧内层 singleton batch，并先核验新 wrapper。CLI 传同样参数。生成分析报告与 counts 为 D07，最终集成为 D09；D06 没有修改 baseline/report/comparison 或预测证据模块。准备入口默认与首轮身份保持原义。

## 实际检查与未做项

本次静态检查使用主仓库 `.venv`：Ruff 0.16.5 的最终 `check` 和 `format --check --no-cache` 均退出0；显式 venv 的局部 strict Pyright 退出0（0 errors）。检查范围为两个 discovery contract、generation、sequential、hosted、launcher 及三个管理脚本。原始输出、配置和源码身份保存在[持久目录](../../artifacts/post-hm-next/sequential/)。早期 Pyright 误用 worktree 缺失的 `.venv`，随后一份绝对 include 配置未检查文件；两次输出均保留且不算通过证据。最终配置使用相对 include 与主仓库 venv。

没有运行测试、完整 CI、第二轮研究模型、科学执行、首轮重跑、依赖升级或 commit；没有读取大 native prediction。没有新增宿主资源平台，也没有声称本路径已经真实运行资格化。后续真实调用仍需明确新增外传载荷、额度、host 全量增长和 lease；历史额度不是余额。
