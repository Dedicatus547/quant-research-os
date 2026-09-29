# Contracts 与 provenance

Contracts 固定输入、输出和状态语义。
公共 schema 在 `src/quantos/contracts/`，不依赖 Qlib、Tushare、Agent harness 或 LLM SDK。

## Schema 与 canonical encoding

- Pydantic v2，`extra=forbid`；schema 有明确版本，enum 不使用自由 magic strings。
- 对象逻辑 ID 与 schema version 分开；时间戳显式时区。
- Canonical JSON 禁止 NaN/Inf，包含默认值，规范 enum/time/numeric representation，排序 keys。
- 校验后的内容经确定性 UTF-8 serialization 生成 SHA-256。
- `ArtifactRef` 使用 `kind / sha256 / size_bytes / media_type / logical_path`；
  相应 verifier 重新核验具体产物的文件集合及 lineage。

Runtime-only 字段的排除范围由具体 contract 定义，不能把所有时间字段统一忽略。
例如来源 availability 参与 PIT 权威；它不是可删除的运行元数据。
项目编码不声明跨语言 canonical JSON 标准兼容性。

资格报告的 `qualification_hash` 是排除自身字段后的 canonical 内容 SHA-256，
并非 `qualification-report.json` 原始文件的 SHA-256。文件清单中的 `sha256`
则绑定原始字节。两种哈希分别使用，不能直接互换。

## 三个状态轴

| 状态轴 | 值 | 含义 |
|---|---|---|
| RunStatus | `SUCCEEDED / FAILED` | 程序是否成功产生所需证据 |
| ValidationVerdict | `PASS / REJECT / NOT_EVALUATED` | 验证是否接受研究结果 |
| StrategyStatus | `DRAFT / CANDIDATE / VALIDATING / REJECTED / VALIDATED` | Registry 策略版本生命周期 |

| 情况 | 正确状态 |
|---|---|
| 完整执行且通过启用的 gates | `SUCCEEDED / PASS` |
| 证据完整但 PIT/hard gate 或 soft threshold 失败 | `SUCCEEDED / REJECT` |
| 依赖、Qlib、程序等执行异常，证据未完成 | `FAILED / NOT_EVALUATED` |
| 上游失败导致后续 gate 未运行 | 该 gate 为 `NOT_EVALUATED` |

`QLIB_EXECUTION_FAILED` 保持执行失败。
研究阈值拒绝不能替代它；Agent 不能更改任一 verdict。

工程资格又是独立层级：证明正确地产生拒绝结果，可以是工程 PASS。
它不把 Validation REJECT 改为 PASS，也不证明盈利或投资适用性。

## Provenance

Canonical runs 绑定：

| 类别 | 内容 |
|---|---|
| 代码 | 精确实现 commit、clean/dirty 标记、相关 schema/policy |
| 环境 | `uv.lock`、Python、OS/kernel、架构、libc、锁定 runtime/numeric packages |
| 数据 | snapshot、view、PIT、上游 release 和输入 ArtifactRef |
| 研究 | authoring/resolved spec、模型/表达式配置、seed、thread counts、预算 |
| 执行 | converter/source/config、Qlib records、导出文件集合与 hashes |

各产物按自身 schema 保存或引用这些绑定，不是每个 manifest 都直接含全部字段。
当前 RuntimeFingerprint 的 package 集合为 LightGBM、NumPy、pandas、PyArrow、
Pydantic、pyqlib、ruamel.yaml、Typer；完整依赖还由 `uv.lock` 绑定。
P14-DQ 的 `PYTHONHASHSEED` 另由批准的 runtime-environment 记录绑定。

Canonical 默认拒绝 dirty worktree。开发报告标记 `NON_CANONICAL`，
不通过省略 provenance 获得资格。Qlib run ID 和本地 recorder 路径仅用于追查运行。

## 不可变发布

产物使用 `sha256-<content_hash>` 地址，拒绝 mutable alias、路径逃逸、symlink 和特殊文件。
写入通过临时文件、同步、原子创建/目录发布完成。
单写者锁保护多文件写入；冲突不能覆盖已有 target 或分叉事件链。

数据修订、schema 修订、策略版本和失败尝试产生新证据。
Rejected/failed experiment、原始 provenance 和 superseded history 保留。

## 对象内容、principal 与原始字节

这些比较范围分别记录：

1. Contract 的内容 hash，按该对象定义的字段域计算。
2. Qualification 的 principal summary，绑定其指定的权威对象。
3. 各根原始文件清单，绑定实际 size 与 SHA-256。
4. 获批的文件树投影，例如 P14-DQ 仅排除 JSON 顶层 `created_at` 后的 canonical bytes。

投影一致不代表所有原始 manifest 字节一致。
具体 P14 差异与数目见[RC 修正记录](../releases/p14-rc-v1-equality-correction.md)。

- [冻结契约索引](../contracts/README.md)
- [验证与 Registry](validation-and-registry.md)
- [资格证据核验](../guides/qualification.md)
