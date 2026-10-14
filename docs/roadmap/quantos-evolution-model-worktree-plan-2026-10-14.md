# QuantOS 演进：模型分工、worktree 与会话执行手册

日期：2026-10-14。任务依据：[路线图 v0.2 §10](quantos-evolution-roadmap-v0.2-2026-10-14.md#10-给-codex-的近期任务边界)与[P1/R0 材料及固定研究设计](quantos-evolution-p1-r0-evidence-2026-10-14.md)。

**本轮仅完成规划。没有创建 worktree、派发实施 agent、提交代码、运行测试或启动研究。** 下文命令与提示词供用户随后启动实施使用；提示词中的实施/验证授权仅在用户实际发给对应会话时生效。

## 1. 推荐配置：三个会话、两个新增 worktree

| 会话 | 主 agent / 思考强度 | 工作目录 | 职责与使用时段 |
|---|---|---|---|
| M：协调与集成 | **GPT-6.1-Sol / medium**；最终语义审查临时调为 **high** | 主工作区 `/home/zjw/quant-research-os`，实施时建立 `work/evo-integration-20261014` 分支 | 准备共同基线、管理跨分支合并、核对交接、最终集成。工作会话实施期间不循环轮询或重复审查源码。 |
| A：字段与 PIT 核心 | **GPT-6.1-Sol / high** | `.worktrees/evo-pit-20261014`，分支 `work/evo-pit-20261014` | 后继来源契约、PIT writer/reader、表达式与 signal 接线、相关定向验证。连续完成这一紧密耦合范围。 |
| B：收尾、执行与 CLI | 第一阶段 **GPT-6-Luna / medium**；进入执行接线后切为 **GPT-6.1-Sol / medium** | `.worktrees/evo-runtime-20261014`，分支 `work/evo-runtime-20261014` | 先做格式、固定 YAML 和事实性清单；接口确定后做 adapter/profile、预测来源适配、薄 CLI；集成后生成准备产物和报价。 |
| 可选 E：疑难复审 | **GPT-6-Astra / high**，短会话 | 只读检查指定提交；结论写独立复审文件 | 仅当旧/新 authority、来源核验或恢复语义存在具体未解冲突时开启。默认不开，不全仓重复审计。 |

日常最多两个实施会话同时运行，M 在交接点工作；无需第四个常驻“总监”。Astra 不承担格式、配置、普通 CLI 或反复状态汇总。默认不使用 xhigh/max/ultra，也不让各会话再派子 agent。

这是基于本项目任务耦合度和返工风险的分配判断。OpenAI Docs 将 Sol 定位为兼顾成本的复杂编码选择、Luna 定位为范围明确的重复任务；本机模型缓存也列出了上述三个型号及所用强度。实际账户可用性以启动时模型选择器为准。[模型说明](https://learn.chatgpt.com/docs/models)、[模型选择](https://developers.openai.com/api/docs/guides/model-selection)

订阅消耗还受上下文、推理、工具与缓存影响，不能用 API 单价推算固定节省百分比。各会话选择 **Standard** 速度，避免默认 Fast/Ultrafast；用 `/status` 或用量面板观察实际消耗。此处不购买额度、不切 API key。官方说明也明确速度档位会影响订阅用量。[额度与速度说明](https://learn.chatgpt.com/docs/pricing)

本机当前全局配置为 `gpt-6-astra / xhigh`。下面的启动方式显式覆盖本次会话，**不修改全局配置**，避免所有简单任务继承高强度默认值。规划依据为 2026-10-14 本地配置/模型清单及当日官方资料，不保证未来套餐或可用型号不变。

## 2. 工作包、依赖与并行

| ID / 负责人 | 任务 | 前置 | 交付与结束点 |
|---|---|---|---|
| M0 / M-medium | 检查现状、保留现有改动，建立本地集成分支；使四份计划/索引文件进入共同基线；建立两个新 worktree 与分开的持久交接目录 | 用户启动实施 | `coord/setup.md` 写实际 BASE_SHA、三个分支/路径、环境用法和文件所有权；通知用户启动 A/B。 |
| A0 / A-high | 先落定后继 PIT schema、source-map、版本 dispatch 和公开调用接口；梳理旧版本如何保持拒绝行为 | M0 | 一个可引用的实际提交 `INTERFACE_SHA` 与 `pit/interface.md`，写清真实类型/签名、旧/新边界及仍待实现部分；随后继续 A1，无需等待 B。 |
| B0 / B-Luna-medium | P0 两文件格式修复；C 义务事实表草稿；准备 V/P 显式 Safe DSL YAML 与配置引用清单 | M0；可与 A0/A1 并行 | 提交 B0 的独立改动，写 `runtime/b0.md` 后结束当前轮，等待接口接入。不构造虚假最终 hash 或推测未定接口。 |
| M-bridge / M-medium | 核对 A0/B0 handoff，在 B 已结束当前轮且工作区干净时，将 A0 实际提交合入 B 分支 | A0、B0 | `coord/bridge.md` 记录 B 的实际新 HEAD、INTERFACE_SHA 和 B1 入口。A 可以继续 A1。 |
| A1 / A-high | 实现 PIT 两来源、紧凑证据核验、表达式/signal 路径；复用受影响用例完成必要验证 | A0 | `pit/final.md` 与 PIT_HEAD；新旧语义、反例、未测项及相关日志可核对。 |
| B1 / B-Sol-medium | 依据 A0 真实接口，实现后继 field-study profile、adapter/恢复与预测来源读取接线、prepare/status/run/compare 薄 CLI | M-bridge；与 A1 并行 | `runtime/final.md` 与 RUNTIME_HEAD；CLI 和受控夹具验证完成，仍不运行真实研究。 |
| M1 / M-high | 顺序合入 A1/B1，集中检查两来源 PIT、旧语义、执行身份/恢复、源码/来源采用、prepare 无执行副作用；补必要集成验证 | A1、B1 | `coord/integration.md` 记录 INTEGRATION_SHA、已复用检查及新增检查。具体实现问题交回唯一所有者处理。 |
| B2 / B-Sol-medium | B 分支快进到 INTEGRATION_SHA，在干净源码 worktree 完成实际 prepare、价格对照复用判断、完整 quote 与资源需求 | M1 的相关接口与必要验证通过 | 固定双候选 preparation、实际命令、预算与 `runtime/preparation.md`；实际科学执行为零。 |
| M2 / M-medium | 只读核对交付完整性，更新短状态，汇总一次 R1c 具体运行请求 | B2 | 离线实施交付完成；停止在科学执行前。不因为计划完整就继续运行 R1c。 |

```mermaid
flowchart LR
  M0[共同基线与两个 worktree] --> A0[A0 后继契约与真实接口]
  M0 --> B0[B0 格式与固定配置]
  A0 --> A1[A1 PIT 与 signal 核心]
  A0 --> Bridge[M 合入接口到 B]
  B0 --> Bridge
  Bridge --> B1[B1 执行接线与 CLI]
  A1 --> M1[M 顺序集成与语义审查]
  B1 --> M1
  M1 --> B2[B2 实际 prepare 与报价]
  B2 --> M2[M 汇总运行请求后停止]
```

能并行的是 B0 与 A0/A1，以及接口落定后的 A1 与 B1。**同一 schema 的设计与消费、最终合并、正式输入冻结以及同一恢复链有依赖，不能为了增加会话数强行并行。** 不把 A 的 contracts、writer、verifier 拆给三个不同低成本模型反复对接。

## 3. 文件所有权与 worktree 规则

### 3.1 唯一写入范围

以下省略源码前缀 `src/quantos/`。相关测试按所测模块归属；共享测试文件由 M 明确一个所有者。

| 所有者 | 主写入范围 | 跨边界处理 |
|---|---|---|
| A | `contracts/research_execution.py` 及 PIT 后继契约、`application/pit.py`、`research/qlib/pit_evidence.py`、`research/qlib/expression.py`、`research/qlib/signal.py`，必要的相应导出；PIT/表达式/signal 测试 | B 需要改变 A 的类型或签名时，把具体调用差异写入 handoff，由 A 改；B 不自行改 PIT contracts。 |
| B0 | `src/quantos/application/sdk_prompt.py` 与 `tests/unit/test_sdk_prompt_projection.py` 的纯格式；拟新增 `configs/research/adjusted_volume_relative5_v1/`；C 表草稿在 handoff 中 | Luna 不裁定 P14d-C 资格，不修改科学/安全规则，不进行全仓格式化。 |
| B1/B2 | `application/autonomous_execution.py`、`application/discovery_prediction.py` 及其实际 reader 接线；拟新增窄 field-study 输入契约/application 薄封装、`scripts/frozen_field_study.py`、本工作包测试与使用说明 | 需要 `contracts/research.py`、enumeration 或共享源身份清单改动时由 M 指定唯一所有者后继续；不同时改同一文件。 |
| M | 计划/状态/索引的最终更新、跨分支合并、有限集成检查与最终交接 | 不在两个 worker 写入期间进入其目录修改源码；语义冲突回给所属 worker，只有明确机械冲突可直接解决。 |

A0 handoff 至少包括：后继 schema/版本名、两来源字段映射、真实构造/读取签名、profile 传递要求、旧对象的解释规则、一个小型结构示例、INTERFACE_SHA、验证与未实现项。它是接口交接，不新增审批或资格平台；不要求用户批准普通接口细节。

### 3.2 共同基线：先处理未提交文档

规划时主工作区 HEAD 为 `4b9961f3d3f7c58fa81424e719a10e877e96305c`，当前路线图/配套材料尚未跟踪，README 有改动。**直接从 HEAD 建 worktree 会漏掉这些计划。** M0 先在新本地集成分支保存下列四个明确文件，再把实际提交作为共同 BASE_SHA：

- `docs/roadmap/quantos-evolution-roadmap-v0.2-2026-10-14.md`
- `docs/roadmap/quantos-evolution-p1-r0-evidence-2026-10-14.md`
- `docs/roadmap/quantos-evolution-model-worktree-plan-2026-10-14.md`
- `docs/roadmap/README.md`

启动时重新看实际状态；若这些内容已提交且身份一致，直接采用，不再制造重复提交。只 stage 明确文件，不使用 `git add .`；保留未纳入本任务的 v0.1 文件和其他用户改动，不 stash/reset/清理它们。root 中的其他未跟踪文件不应被带入源码 capsule。

使用新的两个短期 worktree，不复用已有 `.worktrees/mainline`、`fr03`、`merge-review`；这些目录关联旧分支与持久证据。不运行 `git worktree prune`、不删除 prunable 条目或旧 worktree。新增分支/路径若碰撞，保留原对象，记录新的明确名字后更新启动命令。

### 3.3 合并方式与来源冻结

M 是跨分支 Git 操作的唯一负责人。A/B 在各自分支提交自己的工作；跨分支 merge 仅在目标 worker 已交接、当前轮结束且目标 worktree 无待提交更改时进行。

1. A/B 从同一个实际 BASE_SHA 出发。
2. A0 交付后，M 将精确 INTERFACE_SHA merge 到 B 分支；保持提交 ancestry，避免复制文件或 cherry-pick 后重复引入同一契约。
3. 最终在集成分支顺序合入 PIT_HEAD，再合入 RUNTIME_HEAD。合并结果包含共享 A0 祖先；不 squash/rebase 已被另一分支采用的公共提交。
4. 相关集成检查通过后，M 在 B 空闲且干净时将 B 分支 `--ff-only` 到精确 INTEGRATION_SHA，再交给 B2。不能在 B 正在生成输入/计算 hash 时移动其 HEAD。
5. B2 的真实 preparation 使用这个干净 worktree/source capsule。主工作区保留的无关未跟踪文件不应导致历史数据被复制，也不应污染正式源码来源。以后仅状态文档变化时，按实际依赖复用已冻结来源，不因为总 HEAD 不同重跑科学。

所有操作限本地分支；不合入/改写受保护发布状态，不 push、不部署。最终把本地集成分支及具体提交交付给用户。

### 3.4 输入、环境与输出隔离

复用主仓库已有 immutable 原件的**显式绝对路径**；新 worktree 没有 `artifacts/` 数据副本是正常现象。不要各复制一次 snapshot/view，不把旧相对路径解析失败误认为证据丢失。分开的未来持久写入根为：

```text
/home/zjw/quant-research-os/artifacts/evolution-implementation-20261014/
  coord/        M 唯一写入：setup、bridge、integration、final
  pit/          A 唯一写入：interface、checks、final
  runtime/      B 唯一写入：b0、checks、final、preparation
  escalation/   可选 E 唯一写入：具体疑难问题与结论

/home/zjw/quant-research-os/artifacts/field-study/
  adjusted-volume-relative5-20261014-01/
    preparation/  B2 唯一写入
    management/   B2 留存真实准备退出和资源说明
```

这些目录目前只是规划路径，由 M0 在未来实施时建立。正式研究的 execution/comparison authority 本轮不创建或写入。

两个 worktree 可以复用已锁定依赖，但不能共同修改一个可写 `.venv`，也不能让 editable install 把 A/B 的测试都导向主仓源码。优先用已存在的锁定解释器与显式工作树 `PYTHONPATH`，在各自 cwd 核对 `quantos` 解析路径确实属于本 worktree 的 `src`。必要时采用已有隔离环境做法；不因新增 worktree 自动重装两套大环境。

独立小型 contracts/纯函数用例可并行；涉及 Qlib、较大 fixture 或共享物理卷增长时由 M 安排，避免两个昂贵验证重叠。验证结果各自保存，最终仅补跨模块行为和依赖确实变化的检查；M 不机械重跑 A/B 全部已通过用例。未经明确范围授权，不启动测试、真实科学执行、联网采集或研究模型调用。

## 4. 节省额度的工作方式与升级规则

- 每个 worker 先读 AGENTS、实施纪律、本文自己的任务行及路线图相应段落；P1/R0 阅读结论和所需来源定位，不重新做全仓研究。只有某项依赖不明时再定向深入。
- 每个交接一页以内优先列提交、文件、接口、已完成验证、未测范围、未解决问题与下一步。详细日志保留链接，不把全部终端输出复制给三个会话。
- 到依赖边界就写 handoff 并结束当前轮；不要开计时器/反复轮询，也不要让强模型等待另一个模型工作。会话可保留，收到继续提示再工作。
- 同一会话可在阶段边界换模型，通常无需重开并重新读取项目。只有上下文已经过长或需要独立疑难审查时才另开短会话。
- Luna 遇到 source identity、PIT、恢复状态或跨模块 schema 设计时，留下具体差异交给 Sol；不让 Luna 通过多轮猜测扩大改动。B1 的普通接线用 Sol-medium，局部高风险问题可临时 Sol-high。
- A/M 在 Sol-high 下仍遇到有具体证据的语义矛盾时，才用 Astra-high 读取该问题、相关 diff 和原件。一次集中判断后回到原所有者修改；不默认 Astra 再审全部实现，不以“达到两次失败”之类新门槛代替判断。
- 不凭没有观测到的账单声称节省比例。记录各阶段实际模型/强度和可见用量即可，不为比较模型消耗再运行同一完整任务。

## 5. 用户实际操作顺序

**第一步只开 M。** 选 GPT-6.1-Sol / medium / Standard，目录主仓，发送 §6.1。M0 完成后会返回共同 BASE_SHA、两个真实 worktree 路径和 setup 文件。

**第二步同时开 A、B。** A 选 Sol / high，发送 §6.2；B 选 Luna / medium，发送 §6.3。A 交付接口后会继续核心实现；B0 完成后结束当前轮。

**第三步做一次接口交接。** A 的 interface 与 B 的 b0 都已落盘后，给 M 发送 §6.4。M 完成 bridge 后，在 B 会话将模型切为 Sol / medium，发送 §6.5；A1/B1 此时并行。

**第四步集中集成。** A/B final 都完成后，M 切为 Sol / high，发送 §6.6。若有具体修复，原 worker 收到问题后继续自己的分支，M 只重做受影响审查。没有问题时 M 交付 INTEGRATION_SHA 并将干净 B worktree 快进。

**第五步只做准备。** B 保持 Sol / medium，发送 §6.7；其完成后，M 回到 medium，发送 §6.8 汇总。到此结束；R1c 的真实科学执行需要用户针对该份具体报价另行启动。

若使用 CLI，可在相应目录已由 M0 建立后按下列方式启动。命令只选择会话模型/强度和必要写入根，不启动本文任何具体任务；启动后粘贴对应提示词。UI 用户在会话设置选择同样参数即可，切模型后核对强度没有继承旧值。

```sh
# M：先启动；在主仓的当前状态上做受控准备
codex -C /home/zjw/quant-research-os -m gpt-6.1-sol -c 'model_reasoning_effort="medium"'

# A：等 M0 建立目录后启动
codex -C /home/zjw/quant-research-os/.worktrees/evo-pit-20261014 -m gpt-6.1-sol -c 'model_reasoning_effort="high"' --add-dir /home/zjw/quant-research-os/artifacts/evolution-implementation-20261014/pit

# B：先 Luna-medium；B1 前在同一会话切换到 Sol-medium
codex -C /home/zjw/quant-research-os/.worktrees/evo-runtime-20261014 -m gpt-6-luna -c 'model_reasoning_effort="medium"' --add-dir /home/zjw/quant-research-os/artifacts/evolution-implementation-20261014/runtime --add-dir /home/zjw/quant-research-os/artifacts/field-study/adjusted-volume-relative5-20261014-01
```

CLI 的 `-C`、`-m`、`-c`、`--add-dir` 已通过本机 `codex --help` 只读核对。模型缓存显示本文使用的 medium/high 均受支持。若 UI/CLI 实际没有所选型号，不自动购买额度或换认证；主力可用已可选的 GPT-6-Sol 相同强度临时代替，Luna 不可用时让 B 全程 Sol-medium，简化为两个型号。若核心 Sol 也不可用，先调整模型配置计划，不让简单模型冒领核心任务。

## 6. 可直接复制的提示词

以下提示词以本页为共同规则，已包括未来实施所需的有限本地提交、worktree、定向验证授权。它们不授权研究调用、科学批次、外发或部署，也不要求重复确认已授权的可逆动作。

### 6.1 M0：初始化协调会话

```text
你是 QuantOS 演进实施的 M 会话，主模型 GPT-6.1-Sol，思考强度 medium。
请执行 docs/roadmap/quantos-evolution-model-worktree-plan-2026-10-14.md 的 M0。
先读 AGENTS.md、实施纪律、该计划与路线图 §10，复用已完成的 P1/R0 结论。
授权在本地创建集成分支、提交该计划列明的四份文档，并创建 A/B 两个独立 worktree
及分开的持久交接目录。只处理明确文件，保留所有其他现有改动和旧证据，不清理旧 worktree。
检查实际 HEAD、分支碰撞、依赖环境的源码解析路径和当前必要资源；不复制整份数据/环境。
将实际 BASE_SHA、三个分支/目录、输出根、文件所有权写入 coord/setup.md。
本阶段不做源码实现、不跑测试、不启动研究模型或科学执行，不 push、不部署，不派子 agent。
完成 setup 后结束当前轮，返回 A/B 的真实启动目录与提示词编号；不要循环等待 worker。
```

### 6.2 A：核心接口与实现

```text
你是 A 会话，GPT-6.1-Sol / high，在 evo-pit worktree 工作。
执行 docs/roadmap/quantos-evolution-model-worktree-plan-2026-10-14.md 的 A0、A1。
先读 AGENTS.md、实施纪律、coord/setup.md、自己的文件所有权及路线图 §10.2。
研究问题已固定，P2a 暂缓，不重做 P1/R0，不建记忆系统。
先提交实际后继 PIT 契约/公开接口，并在 pit/interface.md 给出 INTERFACE_SHA、真实签名、
两来源映射、版本读写分派、旧语义、示例及未实现部分。此时不伪称整条链已接通。
随后继续 A1：完整实现 bars.volume_shares 与 adjustment_factor 的时点/窗口/来源核验，
紧凑 PIT writer/verifier、adjusted_volume 表达式/signal 接线，保留旧版本身份及拒绝行为。
允许本工作包必要的受影响定向测试、实现验证与本地提交；使用真实小原件或合成夹具，
共享依赖时核对导入来自本 worktree。完成步骤及时留存检查记录，不重跑历史科学资格。
只修改 A 所属文件；公开接口如需调整，明确记录给 M/B，不在 B 目录改文件或改其分支。
不调用研究模型、不执行真实科学任务、不新增采集/外传、不 push、不派子 agent。
完成后写 pit/final.md：实际提交、修改范围、验证及未测项、剩余风险；结束当前轮。
```

### 6.3 B0：廉价且独立的工作

```text
你是 B 会话第一阶段，GPT-6-Luna / medium，在 evo-runtime worktree 工作。
执行 docs/roadmap/quantos-evolution-model-worktree-plan-2026-10-14.md 的 B0。
先读 AGENTS.md、实施纪律、coord/setup.md 和 B0 文件范围。
仅修复 sdk_prompt.py 与 tests/unit/test_sdk_prompt_projection.py 的必要格式；
把 C 义务、已有 A1 证据和缺口整理成 runtime/b0.md 中的短事实表，不裁定新资格。
依据配套研究设计准备 V/P 两份显式 Safe DSL YAML 及共同配置引用清单。
不要扩窗口、发明 runtime hash、设计 PIT schema 或提前实现未知接口。
允许受影响格式/配置的必要定向检查与本地提交；不跑完整测试、模型或科学任务。
不改 A 文件、不操作另一分支、不派子 agent。提交后写 runtime/b0.md，列实际提交、
文件、检查及依赖 A0 的事项，然后结束当前轮，等待 M 完成接口 bridge。
```

### 6.4 M-bridge：接口接入

```text
继续 M-bridge。读取 pit/interface.md 与 runtime/b0.md，核对它们对应的实际提交。
确认 B 当前轮已结束且 worktree 干净后，将精确 INTERFACE_SHA 合入 B 分支；
只做接口/文件所有权核对，不重新审查全部 PIT 实现。A 可继续自己的 A1。
写 coord/bridge.md，给出 B 的实际 HEAD、公开接口和 B1 可用范围。
如有明确接口问题，用具体文件/签名描述，继续完成不依赖该问题的工作。
不执行科学任务，不派子 agent。完成后结束当前轮，提示我将 B 切到 Sol-medium 并发 B1。
```

### 6.5 B1：执行与 CLI

```text
本会话已切换为 GPT-6.1-Sol / medium。执行分工计划 B1。
读取 coord/bridge.md、pit/interface.md、路线图 §10.2–10.4 和自己已完成的 B0。
基于实际后继接口实现固定 field-study profile、执行身份/预算/恢复、预测来源 reader
以及 scripts/frozen_field_study.py 的 prepare/status/run/compare 薄封装。
复用 QuantosResearchExecutionAdapter、Qlib Workflow、checkpoint/receipt 和现有预测统计。
prepare/status 必须没有科学执行副作用；只接纳冻结 V/P 两候选，不伪造 generation response。
不修改 A 所属 PIT 契约/核心文件；需要变更时留下具体接口差异交给 M/A。
允许本范围必要的定向测试、受控夹具验证和本地提交；未集成 A1 的真实能力如实列为依赖，
不能以 mock 通过代替最终接通。此阶段不要生成绑定临时源码的正式 preparation。
不运行真实科学任务、研究模型、采集/外传，不 push、不派子 agent。
完成后写 runtime/final.md：实际提交、入口、验证、未测项及剩余依赖，结束当前轮。
```

### 6.6 M1：集成与一次集中审查

```text
本会话已切换为 GPT-6.1-Sol / high。执行分工计划 M1。
读取 A/B final，核对精确提交、实际验证范围与文件归属，按计划顺序合入集成分支。
集中审查两来源 PIT、新旧版本接受/拒绝、profile 和 execution identity、恢复/预算、
源码/预测来源采用及 prepare/status 无执行副作用，检查 V/P 与固定研究设计一致。
允许必要跨模块集成验证和本地提交；复用 worker 已通过且实际依赖未变的检查，
不要另跑全量历史矩阵或科学任务。语义问题给唯一所有者，机械合并问题可直接修复。
相关必要检查完成后，在 B 空闲、干净时将 B 分支快进到精确 INTEGRATION_SHA。
写 coord/integration.md：提交、复用/新增验证、未解决项和 B2 是否具备准备条件。
不 push、不执行真实科学任务、不派子 agent；完成后结束当前轮。
```

### 6.7 B2：准备真实输入与运行报价

```text
继续 B2，保持 GPT-6.1-Sol / medium。先核对 B worktree 已在 coord/integration.md
指定的 INTEGRATION_SHA，相关必要检查通过且源码来源干净。
按路线图 §10.3 和配套固定设计执行实际 prepare：固定双候选、请求、完整日期、
coverage policy 和所有真实来源 hash；核对旧 return5 是否能按实际依赖复用。
用最终配置和现有 quote 算完整科学工作量，按既有宿主卷/guard/lease 记录准备资源需求。
使用主仓原件的显式绝对路径，不复制整个数据目录，不解析大预测来重做 P1/R0。
产物写入计划指定的 field-study preparation 根，真实退出和检查写持久 management；
只准备，不执行 run 或真实科学 compare。给出最终可运行命令、最小新增任务数、预算、
未知成本及恢复入口，写 runtime/preparation.md 后结束当前轮。
有实现缺陷先做最小修复并交给 M 有序集成；不要把带缺陷/未验证状态说成运行就绪。
```

### 6.8 M2：交付并停止在运行前

```text
本会话恢复 GPT-6.1-Sol / medium。执行分工计划 M2。
只读核对 runtime/preparation.md 与实际小型准备产物，确认源码/输入/两个请求/比较政策/
报价/资源范围一致。复用已有验证，不再读取大预测或重复跑完整检查。
更新短状态与 coord/final.md，交付本地集成分支、提交、实际命令、已完成和未解决项。
把 R1c 尚需用户决定的最小科学运行范围和完整预算一次列清；没有科学授权就结束本轮。
不要启动模型、研究批次、采集/外传、push 或部署，不派子 agent。
```

### 6.9 可选 E：只处理具体疑难

```text
你是独立疑难审查会话，GPT-6-Astra / high。本次只读审查 M 指定的具体问题和提交。
读取 coord 中的问题描述、相关 diff、原冻结契约与必要小原件；不要全仓重新审计。
判断是否存在 PIT/authority/恢复/来源身份错误，引用实际符号和证据，给最小修正建议。
不实现、不跑测试或科学任务，不放宽冻结规则，不派子 agent。
将结论写入 escalation/ 对应问题记录，列明确结论与仍缺证部分后结束当前轮。
```

E 的问题输入由 M 在需要时写明实际 commit/diff 和争议点；当前不预造问题或预启动第四个会话。任何升级都只消费该具体范围，修复与最后交付仍归原所有者和 M。
