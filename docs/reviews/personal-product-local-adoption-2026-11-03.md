# 个人研究产品本地差异审阅与采用

2026-11-03。本页为源码阅读与采用范围记录，不是独立资格报告、接口测试结果或科学证据。
本地基线main `761ba39`；产品原源码 `1820f1c`，先行文档 `364c152`。采用[收尾登记](../releases/personal-research-closeout-2026-11-03.md)中的历史来源及限定结论。

差异已在集成前读取：原产品51文件/12443新增行；此次新增独立显示投影，接入MCP及显式CLI后继动作，仓库Skill与指南默认选择摘要。旧service及其capabilities/data_describe/results实现、不可变验证函数、全部科学runtime和contracts不变。旧客户端仍返回完整结构；无静默schema替换。四个后继有各自v1显示schema。

结果投影从原service.results返回值选择固定字段；不按状态过滤行，不把null填零，不复制完整comparison或逐日清单。经典保留原prepared/receipt/outcome和origin哈希。边界分页只回原file/sha256；正文只接受当前候选已绑定的hash，使用现有confined_regular_file和安全目录读取，再比对原字节hash；文本分片保持原UTF-8内容。results读取仍会沿原status进行既有UNKNOWN对账，因此MCP结果工具沿用write annotation。

能力页默认20、最多100数据集；边界页默认20、最多100引用；正文默认8000、最多32000字符。空目录、未运行或未观察状态保留null/NOT_OBSERVED，未引入就绪即零暴露的断言。完整manifest与年度/子期、部分原生产物仍通过旧完整工具读取。

本次只读取源码、manifest与旧检查原件，整理格式；未执行接口、完整性用例、pytest、类型检查、CI矩阵、科学、信号重编译或Qlib回测。旧最终静态检查的初次exit1与配置修复后的exit0均保留，43个旧定向用例不改标为本次投影PASS。后继工程验证状态为未运行，不能作为新组合资格接受。

本地源码/文档集成可采用本页列明的显示修改；这不扩大旧工程资格或科学结论。集成完成后本地main快进到产品分支头，精确提交见Git历史；不推送、不部署、不重启现有MCP进程，不移动历史tag。启用新工具的下一动作是用户重启MCP客户端/进程。

实际依赖对照：冻结manifest的27个仓库条目中26个仍匹配，唯一变化为CLI；22个外部runtime/工具条目仍按原证明采用，未重新核验。新投影/MCP/Skill属于展示传递依赖，虽不在该科学manifest中仍明确列出。展示层无Qlib计算、执行或授权发放调用；import原service不改变其验证与科学谓词。

| 文件 | 冻结SHA256（如有） | 此次内容SHA256 |
|---|---|---|
| `scripts/run_hs300_study.py` | `81965628b2f111a17b8fc616f9eb9a93f2e3b2d4dc4022c3d4614f4ab997a262` | `b7e4e41d365faebbb0453e0eea25b45c95094bc98095896463239c116326c748` |
| `src/quantos/application/personal_projection.py` | `不在原科学manifest中` | `5104d83fe7065202206b606452c62325664b5436e3c7cbb1d7d1c1a766eba07e` |
| `src/quantos/personal_research_mcp.py` | `不在原科学manifest中` | `4b370e6da2ed78c8de4fc5901251e1bc5898737c664429317cd9765bb9fb7b44` |
| `skills/quantos-research/SKILL.md` | `不在原科学manifest中` | `941176279eaa7a68979014b9419e2f4d01c9b13eac4b0ca152966543f4095c8d` |
