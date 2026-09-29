# 数据与 Evidence 采集

市场数据和公告 Evidence 使用不同的采集入口。
两者都先冻结输入，再由离线程序发布权威产物。

## Tushare snapshot

Tushare 只允许由 snapshot acquisition 层调用。Token 由运行环境提供给该层；
不得写入配置、文档、日志或 artifact。

真实构建需要以下已核验输入：

| 输入 | 要求 |
|---|---|
| 账号 capability | required endpoints、fields、schema 与权限有留证 |
| execution policy | 使用账号实际核验的额度和重试参数 |
| snapshot spec | 显式 endpoints、字段、日期和 universe |
| data-quality policy | 显式精度规则、完整性及跨 endpoint 检查 |

仓库保留的政策属于对应账号与日期的已核验记录。其他账号使用前需确认其适用性。

```bash
uv run --frozen quantos snapshot build-tushare \
  configs/tushare/snapshot.yaml \
  configs/tushare/execution_policy_20260904.yaml \
  --quality-policy configs/tushare/data_quality_20260905.yaml
```

采集先 checkpoint SSE/SZSE 日历，再生成有 row-limit 约束的完整 request plan。
重试、限流和断点续传保留请求证据。Normalization、DQ、PIT 和发布在本地离线完成。

数据修订产生新 snapshot，不覆盖旧 snapshot。单位、membership、availability 和
`SINGLE_SOURCE_NON_VINTAGE` 边界见[数据与 PIT](../architecture/data-and-pit.md)。

## 公告 Evidence：Collector → Publisher

P12 将可联网 Collector 与离线 authority publisher 分开：

| 进程 | 输入 / 输出 | 运行边界 |
|---|---|---|
| Collector | 固定 collection/collector policy → hash-addressed staging | 可联网；仅 staging 可写；不访问 authority |
| Publisher | 显式 staging、availability/parser policy、provenance → Evidence Store | 网络禁止；staging 只读；按批准根发布 |

以下命令本身不创建 OS sandbox；canonical 运行由外部 sandbox 强制这些网络和挂载规则。

```bash
env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run --frozen quantos-evidence-collector \
  configs/evidence/collection_example.yaml configs/evidence/collector_v1.yaml \
  --staging-root artifacts/acquisition/evidence

UV_CACHE_DIR=/tmp/quantos-uv-cache uv run --frozen quantos-evidence-publisher publish \
  'artifacts/acquisition/evidence/sha256-<staging_hash>' \
  configs/evidence/availability_v1.yaml configs/evidence/parser_v1.yaml \
  --code-commit-hash '<clean-implementation-commit>' \
  --runtime-fingerprint-hash '<runtime-fingerprint-hash>'
```

Collector 不读取或记录 token 值。Publisher 校验精确文件集合、大小、hash 和冻结 provenance。
`0` 条结果也需要 count/pagination 完整性证据，不能只凭空目录推断没有公告。

## 从 Evidence 到事件特征

Evidence Store 冻结来源字节及获取记录；抽取文本仍是带 parser provenance 的派生产物。
Agent 引用它们生成 proposal。只有 deterministic benchmark 或记录在案的人工审查，
再经 permission、引用范围、entity、availability 和 PIT 检查，才能 admission 为 EventFeature。

P12 历史 SZSE permission 为 `UNKNOWN`，这些记录不能直接 admission。
P13 v2 的单公告批准范围不能推广为通用公告抽取能力。

- [Agent、admission 与 campaign 设计](../architecture/agent-and-campaign.md)
- [P12 采集 ADR](../adr/0002-exchange-evidence-acquisition.md)
- [P13 v2 冻结](../p13-v2-freeze.md)
- [当前资格状态](../status/README.md)
