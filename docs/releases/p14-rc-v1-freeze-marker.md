# P14 RC v1 release marker 与主线冻结

日期：2026-09-29。状态：**FROZEN**。

## Release marker

| 绑定 | 精确身份 |
|---|---|
| Annotated tag | `p14-rc-v1` |
| Annotated tag object SHA-1 | `e20f97e24ee650f28f74be314e7f1d7913e29d6f` |
| Tag target commit / reviewed tree | `3a4a898f74ce2f60a14d2a69250024e92a4378c1` / `f08ae13455a74c5f1478c506253f52df54eb7497` |
| Independent review | `gpt-6-sol / high`，结论 `APPROVE`，无阻塞项或必修项 |
| Review report | `docs/reviews/p14-rc-3a4a898-independent-review.md` |
| Review report raw SHA-256 | `633c1a761c5d95f24186691fbe7814fa92c1b68a85963fe89bb09babf5c18ae9` |
| Review result registration commit | `e5d419089638b425834c68406dd59b964f000766` |
| Qualified production implementation | `e318dc450e5c02f1120da7644250767bf682b6f9` |
| P14d-B qualification hash | `41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71` |
| P14-DQ engineering qualification hash | `f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a` |

本 tag 指向独立复审通过的精确文档提交。Review report、报告摘要与实现/资格身份也写入
annotated tag message；报告文件的内容可直接核对上述原始 SHA-256。

本次创建本地 annotated tag，没有推送远端。可用以下只读命令核对 marker：

```bash
git cat-file -t refs/tags/p14-rc-v1
git rev-parse refs/tags/p14-rc-v1
git rev-parse refs/tags/p14-rc-v1^{}
git cat-file -p refs/tags/p14-rc-v1
```

预期对象类型为 `tag`，peel 后的 commit 是上表目标；tag object SHA-1 由 Git tag object
绑定。Marker 文件和这次登记它的文档提交是后续发布记录，不改变 tag target 或其审阅范围。

## P14 v1 冻结范围

P14 v1 主线已冻结在独立复审通过的文档提交 `3a4a898`，其生产实现资格仍精确绑定
`e318dc4`。后续文档提交只负责记录该 tag 和冻结状态。已沿用的 P14d-B 与 P14-DQ
报告、approved contracts/policies、输入 lineage 和环境边界继续按原 hash 识别。

P14-DQ 工程结果仍为 `SUCCEEDED / PASS`；自然研究结果仍为
`FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`，eligible candidate 为零且未执行选择。
Live Agent、FR-03、P14d-C、sealed confirmation、alpha/盈利、投资适用性、vendor-vintage
PIT 与 unrestricted autonomous research 的资格边界均未改变。

本冻结是 P14 v1 的发布管理状态，不增加工程、数据、研究或运行时资格。
要修改 P14 v1 实现、契约、输入、policy、runtime/environment 或权威表述，需先开具独立
变更范围，更新适用的独立审查与资格证据，再发布新的、精确绑定的版本 marker。

- [独立 RC 复审报告](../reviews/p14-rc-3a4a898-independent-review.md)
- [历次 RC 与发布记录](README.md)
- [当前 P14 资格状态](../status/p14.md)
