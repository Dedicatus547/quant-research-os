# 本地公告 Evidence Store

本地交付 PDF 使用独立的 `local-evidence-store-manifest/v1`，入口为
`quantos.evidence.local_store.publish_local_evidence_store`，核验入口为
`verify_local_evidence_store`。原 HTTP 采集发布器及其核验器保持原样；两个格式不隐式互换。

导入复用已冻结的 PDF、UTF-8 文本及物理页映射，不重新提取 PDF，不联网核验来源。
每份材料保存原件、文本、页映射、用户来源声明、原解析元数据、真实本次本地读取收据、
`EvidenceRecord`、`ExtractedTextArtifact` 和绑定项。整个目录及逐文件内容均绑定 hash；
多余文件、缺失文件或内容变化会被拒绝。

`fetched_at` 是本次可观察的本地读取时刻，**不代表远程下载时刻或历史可获得时间**。
原解析器身份和局限保留；导入 commit 只标识这次绑定，不能冒充原解析代码身份。
来源 URL、日期是用户声明；未知来源权利仍为 `UNKNOWN`，用户允许发送的操作授权单列，
不把操作授权或人工标签批准改写成来源许可。历史可获得性为 `UNKNOWN`，无研究准入或 PIT 资格。
`ORIGINAL` 仅表示该本地记录未声明前件，完整修订历史未知；显式前件必须位于同一 Store。

引用通过既有 `EvidenceMcpService` 生成，再以物理页映射确定第一张覆盖页。
Unicode 字符位置、逐字文本、hash 均须一致。旧空行页码只留为 sidecar，不改写历史引用。
引用可定位只证明字节和位置，不证明字段语义，也不赋予单个分段独立支持完整结论的含义。

主线包含可复用的离线入口：

```text
.venv/bin/python -B scripts/announcement_understanding_pilot.py --help
.venv/bin/python -B scripts/announcement_understanding_pilot.py score --help
```

该脚本不调用模型；其 v1 评分规则保持原样。新模块
`quantos.evidence.citation_groups.group_match` 只做完整批准引用组的集合精确匹配，
允许调整顺序，拒绝重复、缺段和额外引用，不判断语义等价；它不自动替换 v1 评分。

本地导入使用 `LocalImportSource` 和 `LocalImportPolicy` 显式传入文件路径、原件和文本 hash、
来源声明、解析器身份及采用记录，再调用本页所列发布函数。
发布得到的 `sha256-<hash>` 目录必须通过本页所列核验器；引用使用 `local_binding`、
`local_citation` 及保留的物理页映射。接口不启动模型或提升权限。

原 `scripts/announcement_understanding_trial.py` 是仅供这批本地材料的历史调用脚本，依赖
未入库的材料、既有 SDK 运行环境及原授权，不作为通用主线入口提交。
2026-10-22已按原SHA256移入本地持久归档，原路径与归档映射见
[收尾审核](../reviews/workspace-review-2026-10-22.md)；历史记录中保留原路径，不据此重启调用。
PDF、标签、响应、使用量和失败记录仍在 `artifacts/`，不随源码入库。
原运行对应的两份导入源文件已按原 hash 保存在
`artifacts/announcement-understanding-pilot-20261020/mainline-integration-01/frozen-source/`，
路径映射见同目录 `start.json`。复现原运行必须在独立工作树采用这些原字节及原冻结输入；
整理后的主线源码不冒充原运行源码，不改写原 freeze。

本轮属于已有 AI 曝光材料的描述性测试，不能据此宣称独立盲测、节省人工时间或投资有效性。
引用组不完全相同时不自动认定语义错误，也不自动新增等价白名单；人工后续裁定另存，
本轮冻结分数和历史标签不回写。
