# 开发指南

先阅读仓库根 [AGENTS.md](../../AGENTS.md)。当前工程范围见[状态页](../status/README.md)，
验收与依赖见[路线图](../../PLAN.md)。

## 环境

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen
```

涉及已实现 SDK adapter 的开发环境使用：

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen --extra agent-openai
```

版本以 `uv.lock` 为准。SDK 安装成功不改变 [FR-03 NO_GO](../status/fr03.md)。
Canonical 数值结果还绑定 Python、OS/kernel、架构、libc、依赖和运行环境记录。

## 目录职责

| 目录 | 职责 |
|---|---|
| `src/quantos/contracts/` | 严格 schema、enum、canonical serialization |
| `src/quantos/data/` | snapshot acquisition/normalization、PIT 来源、Qlib view |
| `src/quantos/research/` | safe expression、Qlib workflow、Signal/ResearchResult |
| `src/quantos/backtest/` | Qlib 执行适配、产物、reconciliation |
| `src/quantos/validation/` | G0–G10、稳健性、ValidationReport |
| `src/quantos/application/` | admission、typed capabilities、Ledger、campaign 编排 |
| `src/quantos/evidence/` | 分离的公告 Collector/Publisher |
| `src/quantos/artifacts/` / `src/quantos/registry/` | 不可变发布与事件历史 |
| `configs/` | 版本化 policy、冻结 benchmark 与 spec |
| `scripts/` | 工具准备、feasibility、qualification、diagnostics |
| `tests/` | synthetic fixtures、gate/golden、权限与失败用例 |
| `artifacts/` | 授权工作区的证据；通常不入 Git |
| `docs/` | [分层文档目录](../README.md) |

Contracts 不导入 Qlib、Tushare、Agent harness 或 LLM SDK。
Normalization、PIT、执行、回测和 validation 不调用 LLM。

## CI 质量门

[CI 配置](../../.github/workflows/ci.yml)使用冻结依赖；pytest 默认禁网，
line/branch 综合 coverage 门为 `85%`。显式要求验证实现时，可运行：

```bash
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pyright
uv run --frozen pytest --cov=quantos --cov-report=term-missing --cov-report=xml
git diff --check
```

无 token CI 和 synthetic 结果只证明工程范围。
账号能力、授权数据和 live runtime 分别资格化；不能靠调低阈值解决资格缺口。

## 文档维护

| 内容 | 维护位置 |
|---|---|
| 项目介绍与阅读入口 | 根 `README.md` |
| 下一项任务与验收依赖 | 根 `PLAN.md`、`docs/roadmap/` |
| 操作步骤 | `docs/guides/` |
| 技术规则 | `docs/architecture/` |
| 当前资格与阻塞项 | `docs/status/` |
| 契约、批准、冻结、失败 | 原始记录与新补充记录 |
| 重组前原文 | `docs/history/` |

新文档需从 `docs/README.md` 或对应索引可达。
避免把历史运行日志再次复制到 README、PLAN 和状态页。

P14 qualification 脚本按精确路径/hash 读取少量契约、批准记录和 policy。
这些文件保持原位；修订应新增明确的 superseding record，而不改写旧证据。
归档清单记录原始文件 SHA-256，用于检查迁移完整性。

文档修改检查相对链接、`git diff --check`、冻结文件与非文档文件完整性。
软件回归与 qualification 重建按任务所需的验证范围执行；
纯文档检查不声称已重跑或重新资格化生产实现。
