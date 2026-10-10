# HM-02 追加审查：部署与请求投影的无环绑定

日期：2026-09-30。结论：`APPROVED_IMPLEMENTATION_CLARIFICATION / NOT_QUALIFIED`。
模型：`gpt-6-astra`；reasoning effort：`high`；本追加审查 attempt：1；usage：`unavailable`。
本记录仅裁定 hash 依赖方向，不证明现有实现已满足所有检查，不授予 Q07/Q11 或 HM-MVP 资格。
原 [冻结契约](../hosted/hosted-contract-v1.md)、[验收矩阵](../hosted/hosted-acceptance-v1.md)
与 [HM02 清单](../hosted/hm02-freeze-manifest.json) 保持原字节。

## 裁决与契约依据

允许将 profile 的 input projection inventory 明确为**部署初始静态投影 I0**，并将每个
真实 request 的完整投影 Ii 作为随后发布的独立可信事实绑定。这符合 C02 的逐请求冻结
allowlist、C08 的部署配置/投影身份、C10 的实际运行前冻结 profile 及 launcher 绑定实际
request/input projection 的要求。C08/C10 没有要求 profile 包含尚未生成的 request hash。

它不能被解释为只记录 I0 就覆盖所有模型输入。每次模型启动前都须验证、冻结、发布 Ii 与
请求的可信绑定，模型只看到该次经过验证的只读投影。实际 Q07/Q08/Q11、底向上 verifier
和 replay 必须检查它。这是已有门的具体实现，未删字段、未放宽 gate、未新增时间投影。
不能用 dummy hash、先填零再改、exclude_fields、后补配置或重新签发冻结文件解环。

## 最小 DAG 与完整字段绑定

下列箭头表示左侧的完整内容已固定，右侧才可构造并绑定左侧 hash：

```text
B ──→ L ──→ C ──→ D ──→ S ──→ R ──→ Ii ──→ Pi ──→ launcher record
                 I0 ──↗      ↑       ↑         ↑        ↑
                         B ──┘   frozen objects D,S,R ───┘
```

| 顺序 | 对象与必需绑定 | 禁止的逆向依赖 |
|---|---|---|
| 1 | B=`HostedFrozenBusinessInputs`：原 `ResearchCampaignSpec`、research budget、完整 family/template/manifest、initial Ledger/events、execution bindings、selection、所有 policy、code provenance、输入文件清单及完整 hosted recipe | 不嵌 `HostedCampaignSpec`；不含 D/S/R/Ii/Pi 的 hash |
| 2 | recipe=`HostedCampaignRecipe`：hosted budget、requested model configuration hash、contract/acceptance hash、started_at；所有其他构造 S 的输入在 B 有确定唯一来源 | 不在 loader 用当前时间、mutable defaults 或未绑定文件补字段 |
| 3 | L=`HostedBusinessLoaderConfiguration`：`business_inputs_hash=B.hash`、固定 factory 和只读输入/来源/业务根的管理域路径 | 不含 D/S hash |
| 4 | C=`HostedServiceConfiguration`：`business_configuration_hash=L.hash`、完整 channel policy、roots、principals、capability fd 声明和 campaign 静态授权 | 不含 D/S hash；不排除 L 或 auth 字段计算 C.hash |
| 5 | I0：真实初始静态文件的精确 inventory；D=`HostedDeploymentProfile`：`configuration_hash=C.hash`、`projection_inventory_hash=I0.hash`、安装/来源/OS/mount/network/CLI/model/extraction 等全部已有字段 | I0 不含 S/R/Ii/Pi；D 不含 request 或未来 projection hash |
| 6 | S=`HostedCampaignSpec`：由完整 B/recipe 和已验证 `deployment_profile_hash=D.hash` 唯一构造，完整 canonical bytes 留存 | 不修改 B/L/C/D；不让 caller 任意覆盖 recipe |
| 7 | R：持久化 request，绑定 S/D、业务 campaign、预算、ContextPack 和精确 object allowlist | R 不含 Ii/Pi（因为 Ii 包含 R bytes） |
| 8 | Ii：完整逐请求 inventory，文件集合恰为 R.projection_object_hashes 对应对象加 R 自身 canonical bytes | 不添加 I0 中未获 R 授权的文件；不覆盖旧 request 投影 |
| 9 | Pi：管理域可信 pre-launch projection fact，绑定 D/S/R/Ii、campaign、host instance、初始 I0 身份 | Pi 不放入自身所描述的 Ii 中；不要求 R 反向绑定 Pi |
| 10 | launcher record：引用 Pi，绑定实际进程/配置/输出/提案及原有身份 | 不将后置 capture record 充当先于模型启动的投影冻结证据 |

C 对 B 的 L.hash→B.hash **传递绑定**足够；不必在 C 重复 B.hash，但必须实际读取 L 和 B
全字节并重算，不能仅声明存在。D 对 C 也必须绑定完整 C canonical bytes，包括静态授权。
管理目录可同时存放所有这些独立文件；D 的 configuration_hash 只标识 C 对象，不能改成
“包含 D 自身的整个 /config 目录 hash”。目录安全/文件清单另行验证，避免新的自引用。
I0 不得包含带 D.hash 的文件。当前 inventory 类型要求非空时使用真实必要的静态输入，
不能填占位假文件；若确需空初始投影，必须用明确允许空集的 typed inventory 和测试。

## 静态授权与 bootstrap 注册

`C.campaigns` 只含静态业务 `campaign_hash` 是允许的。bootstrap 必须在开放 socket 前：

1. 从管理域固定入口读取 D，核验其完整 canonical identity；核验 D.configuration_hash=C.hash。
2. 重算 C→L→B 全链以及安装、I0、实际 namespace 配置；验证 B.campaign.hash 属于 C 静态授权，
   principal 的 campaign 集合不扩大，model config、policy 与 D 的对应字段一致。
3. 使用固定 factory 从 B 和 D.hash 构造唯一 S，建立只读 `Smap[campaign_hash]=S.content_hash`，
   注册完整 S bytes；单 campaign 多份不同 S 必须拒绝。MVP 单 bundle 时授权集合与加载的
   campaign 集合应相同，不能把未加载 campaign 留作可动态注册入口。
4. `start(campaign_hash,target_hash)` 只接受 `target_hash == Smap[campaign_hash]`；所有其他
   operation 仍验证 request/campaign/attempt/receipt 绑定。宿主不能提交 S bytes 或登记新 S。
5. 重启重新推导相同 Smap，并和持久化 spec/request 逐字节核对；不一致 fail closed，不能
   用新 S 自动迁移旧请求。bootstrap 可在可信根发布单独 RegistrationFact 绑定 C/D/L/B/Smap；
   它是派生后继，不反写 C。该辅助事实不替代逐项重算。

因此 `load_hosted_campaign_application(..., deployment_profile_hash=...)` 的参数只能来自
上述管理 bootstrap 已验证的 D；普通调用参数或“hash 格式合法”不证明可信部署身份。
构造 callback holder 解决 Python 对象引用顺序是允许的，但它不能替代以上内容验证。

## HM-06 的最小 contract / 文件建议

在 `contracts/hosted_deployment.py` 新增纯 `HostedProjectionFact`，建议 schema
`hosted-projection-fact/v1`，字段至少：

```text
schema_version
source = TRUSTED_PROJECTION_MANAGER
phase = PRE_LAUNCH
campaign_hash
hosted_spec_hash
deployment_profile_hash
request_hash
host_instance
initial_projection_inventory_hash
projection_inventory_hash
```

全部 hash 字段重算；Pi 使用完整 canonical content hash，无排除字段。若加入发布时间，
只能由可信 manager 生成并原样保留，不能进入 Q10 新投影例外。source 标签本身不是证明：
Pi 必须由管理域从实际投影 root 读回验证后，fsync/create-if-absent 发布到研究宿主不可写的
可信证据根。管道/launcher 实际开始前发布；不能由 response 自报、接收宿主上传后认证。

`infrastructure/hosted_deployment.py` 保留 `export_projection` 精确集合检查；增加受控
publish/verify Pi 辅助函数。一个 R 使用独立不可变 root。动态 root 挂入 host 的 `/projection`
前后应重验 inventory，并保证模型存活期间管理者不替换 root/file，宿主只有只读 mount。
I0 与 Ii 是不同阶段的明确对象，不能覆盖 I0 或把 D.projection_inventory_hash 改成 Ii。

`HostedLauncherRecord` 增加 `projection_fact_hash`（采用明确新 schema 版本，不能让已保存的
旧 record 获得新增字段的隐含保证）。`hosted_launcher.py` 的 capture 在启动前验证 Pi、Ii、
R、D、S、host_instance 和实际挂载 root，记录 Pi.hash；source verifier 重算同链与完整
inventory，而不是只读 record.projection_inventory_hash。Pi/Ii/所有 bytes 都进入完整 bundle。
失败的 projection、launch 和捕获尝试按已有有界政策留存，不能只记录最后成功的一次。

实施可以采用等价命名，不能省略语义。此处不要求泛化 runtime 或新研究业务流程。

## 所需负例与当前结论

Q03/Q04：错 Smap target、另一个 profile、修改 B/recipe/L/C、错误 campaign/principal、
替换 R/对象、Ii 缺项/多项、symlink/hardlink/挂载竞态均须拒绝，无模型/研究执行副作用。
Q07/Q08：宿主不能写 Pi/Ii/source root；伪 source 标签无效；capture 未预发布 Pi 时拒绝；
实际 mount 与 Pi hash 不符拒绝。Q09/Q10 保存原 Pi/launcher/protocol bytes，离线复核不
重新 live submit，不重写时间或 principal。Q11 用实际部署和真实来源通过上述链路。

本次读取的工作树已经出现 deployment-independent recipe、C 的静态 campaign 授权及
loader 从 recipe+D 构造 S，方向符合本裁决。仅此不足以断言 bootstrap、Pi、source verifier
和实际 mount 已实现或通过；这些仍是 HM04/HM06/HM07 的实施与测试义务。
阅读对象与 hash 记录于同目录 `hm02-deployment-bindings-review-inputs.json`，是本追加审查
快照，不改写原 HM02 清单。提交仍为 d6c77055eaa4844a2e0d9423990475ef23dce15c，工作树有
并行开发改动；这里的代码观察不等于 exact-clean-commit qualification。
