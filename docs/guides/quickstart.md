# 快速上手

目标：安装锁定环境，构建并核验最小 synthetic snapshot 和 Qlib view。
它验证离线工程路径，不产生真实市场资格。

## 1. 安装与检查

以下命令在仓库根目录运行。`uv run --frozen` 使用已有 lockfile，避免隐式重新解析依赖。
冻结运行环境使用 Linux x86_64、Python 3.11 和 `uv.lock`。
其他平台可以用于开发，但不继承冻结环境的数值复现结论。

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run --frozen quantos doctor
```

可选的 Agent SDK extra 见[开发指南](development.md)。安装 SDK 不授予 live Agent 资格。

## 2. 准备官方 Qlib 工具

Qlib wheel 未包含项目所需的官方转换器和 data-health 脚本。
以下命令下载并验证锁定的官方源码；已有缓存时会核验后复用。

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run --frozen python scripts/bootstrap_qlib_tools.py
```

这是可联网的工具准备步骤。后续 snapshot/view 示例使用本地 fixture 和缓存，离线运行。

## 3. 构建 synthetic snapshot

```bash
env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run --frozen quantos snapshot build-synthetic tests/fixtures/synthetic_snapshot
```

命令输出内容哈希与发布路径。下面变量中的占位符必须替换为输出的完整 SHA-256；
变量仅保存显式不可变路径，不解析 `latest`、`current` 或 `auto`。

```bash
snapshot_path='artifacts/data/snapshots/sha256-<snapshot_hash>'

env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run --frozen quantos snapshot verify "$snapshot_path"
env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run --frozen quantos qlib build-view "$snapshot_path"
```

## 4. 核验派生 view

同样使用上一命令输出的完整 view hash：

```bash
view_path='artifacts/data/qlib-views/sha256-<view_hash>'

env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run --frozen quantos qlib verify-view "$view_path"
```

不可变 Parquet 是本地事实源；Qlib `.bin` 是带转换器 provenance 的派生缓存。
查看 snapshot 或 view 的成功结果，不等于策略通过 Validation。

## 接下来

| 任务 | 入口 |
|---|---|
| PIT、回测、Validation 与 Registry | [离线工作流](offline-workflows.md) |
| 使用授权真实数据或公告 | [采集指南](acquisition.md) |
| 核对冻结资格 | [资格证据核验](qualification.md) |
| 理解失败、拒绝与 PASS | [Contracts 与 provenance](../architecture/contracts.md) |

授权市场数据通常不随 Git 分发。缺少数据时继续使用 synthetic fixture；它的结果保持
`data_qualified=false`，不能替代真实数据证据。
