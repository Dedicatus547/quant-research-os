# HM bubblewrap 有界修复方案

本页是2026-10-06安装前研究记录。后继安装和实际运行已完成，过程见
[实施历史](hm-implementation-history-2026-10-10.md)；当前接受范围见
[component-v2 发布记录](../releases/hm-mvp-component-v2-freeze-marker.md)。
下文的工具缺失、未下载和 NOT_QUALIFIED 属于研究时点，不是当前状态或待执行任务。

2026-10-06 安装前只读研究记录。研究阶段未下载、构建、安装或变更 system mount，
未运行完整 CI、资格门或大复制；整体仍为 `NOT_QUALIFIED / NOT_APPROVED`。
实际宿主身份、Windows VHD映射、内存和外层 scratch硬配额由真实宿主检查另行绑定。
遵循 [存储恢复边界](hm-storage-recovery.md) 和仓库 `AGENTS.md`。
后继主代理实际安装、失败原件、quota及进程验证见[完整实施历史](hm-implementation-history-2026-10-10.md)；
下面的工具缺失/尚未下载描述保留安装前观察时点，不能代替后继真实证据。

## 固定上游与本地观测

官方 [v0.7.0 发布说明](https://github.com/containers/bubblewrap/releases/tag/v0.7.0)
明确在此版本新增 `--size`。本方案固定使用 **v0.11.2**，不把 0.7.0作为推荐安装版本。
官方 [v0.11.2 发布说明](https://github.com/containers/bubblewrap/releases/tag/v0.11.2)
和 [固定源码 NEWS](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.2/NEWS.md)
记录 2026-04-23更新，并建议关闭 setuid支持；本方案显式 `-Dsupport_setuid=false`，
安装 mode为0755，不能改为setuid。

官方 [release assets](https://github.com/containers/bubblewrap/releases/expanded_assets/v0.11.2)
给出以下 archive身份；不使用 GitHub自动生成的 source zip/tar.gz代替它：

| 项目 | 固定值 |
|---|---|
| Archive | [bubblewrap-0.11.2.tar.xz](https://github.com/containers/bubblewrap/releases/download/v0.11.2/bubblewrap-0.11.2.tar.xz) |
| SHA256 | `69abc30005d2186baf7737feacd8da35633b93cf5af38838ecff17c5f8e924f6` |
| 官方显示大小 | 114KB；实际下载设置1MiB硬上限 |
| 校验文件 | [bubblewrap-0.11.2.tar.xz.sha256sum](https://github.com/containers/bubblewrap/releases/download/v0.11.2/bubblewrap-0.11.2.tar.xz.sha256sum) |
| 校验文件大小/hash | 91B / `29418c9d2354f7bb423993b4a7b4baabd9fd8359f00b391c34142b09f843e542` |

当前沙箱视图 `/usr/bin/bwrap --version` 为0.6.1；dpkg元数据为
`0.6.1-1ubuntu0.3`。可见gcc/make/libcap2；指定路径检查没有发现
`sys/capability.h`、`libcap.pc`、`pkg-config`、`ninja`，Meson未安装。
这不是对真实宿主或别的namespace的断言。有限128KiB GitHub API请求在沙箱中DNS失败；
archive字节尚未下载核验。网页发布信息只用于选择固定来源，不能冒充安装证据。

## 最小依赖与有界构建

固定 [meson.build](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.2/meson.build)
要求 Meson至少0.49.0、C编译器、Python3和libcap。
[meson_options.txt](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.2/meson_options.txt)
允许关闭man、tests、SELinux和completion。选择Ninja后还需Ninja和pkg-config。
已有Python/C runtime无需复制；关闭这些可选项无需DocBook、xsltproc或SELinux开发包。

当前APT缓存的精确候选如下。真实宿主必须重新模拟，不能沿用沙箱候选证明已安装：

| 包版本 | 下载字节 | Installed-Size (KiB) | 缓存记录的deb SHA256 |
|---|---:|---:|---|
| meson=0.61.2-1 | 518618 | 3255 | `54d4a5b9f2c82c37a5ce0bce9027c623aab5505437d87f12fa858ecf32d0b506` |
| ninja-build=1.10.1-1 | 111368 | 350 | `ca8aae8ac7efad41d1f96a7e227653bd62b24e89cc7ddb18cec262f1869877b2` |
| pkg-config=0.29.2-1ubuntu3 | 48218 | 131 | `69da4190d948d0bf7444ead040791b7924bd1a08a10ec13cd7f0bb9baab09c53` |
| libcap-dev=1:2.44-1ubuntu0.22.04.3 | 39674 | 147 | `5c733a6f0d9e438763ab123e15b26113efc391ced3a785e20e8723c5b354aefc` |

总下载717878B，Installed-Size合计3883KiB。只读
`apt-get --simulate --no-install-recommends install` 的明确版本方案报告
0升级、4新增、0移除。不要运行全系统upgrade或autoremove。APT缓存hash只是当前本地元数据；
真实下载须来自经过APT签名验证的发行版来源并重新核对，离线依赖须保留deb/hash/inventory。
不把已下载且未验证的任意deb作为构建输入。

优先在已核验、容量固定的独占64MiB scratch中构建，单进程 `-j1`，
外层总运行设120秒上限、日志设256KiB上限。64MiB是这次小型构建的拒绝上界，
不是科学环境或CI预算；耗尽即停止，不自动扩容。仅在容量守卫通过后执行：

```text
python3 -B /usr/bin/meson setup <独占build> <核验后的source> \
  --prefix=/usr --bindir=bin --wrap-mode=nodownload \
  -Dman=disabled -Dtests=false -Dselinux=disabled \
  -Dbash_completion=disabled -Dzsh_completion=disabled \
  -Dsupport_setuid=false
/usr/bin/ninja -C <独占build> -j1 bwrap
```

源码解包先限制archive总解压字节、条目数和每条路径，只接受固定顶层目录内的
regular file/directory，拒绝绝对路径、`..`、link及special file；不直接解包未审查archive。
构建环境使用固定allowlist，不继承任意父环境或打印认证变量；Python使用 `-B`。
需要离线构建时，可先将上述四个deb核验并解到独占prefix，指向该prefix的Meson/Ninja/
pkg-config和libcap include/library路径；依赖及系统libcap ABI均须绑定。
不需要复制Python虚拟环境或安装科研依赖。

## 系统安装、隔离与局部验收

实际替换 `/usr/bin/bwrap` 由负责真实宿主操作的主流程执行。先核对它的regular-file身份、
当前owner/mode、hash和package归属，记录原文件到独占持久修复目录并核对副本。
构建binary先在独占目录核对版本/help、ELF依赖与hash；不能先覆盖再验证。
优先制作只含新binary和必要package metadata的小型本地deb，由dpkg完成安装，
避免仅覆盖binary却保留旧dpkg来源。使用明确本地revision（例如 `0.11.2-quantos1`），
记录它是本地构建，保存deb与binary hash、源码/依赖绑定、package control和安装结果。
依赖必须匹配实际ELF所需libc6/libcap2 ABI，不能凭包名推测；关SELinux后不应需要libselinux。
新包仅拥有明确审查的路径，root:root、0755，不加入maintainer scripts、setuid、后台服务
或替换其他package文件。安装前核对既有diversion，拒绝未经处理的覆盖。
保留并核验旧精确版本deb，使回滚也能由dpkg恢复一致的package/binary来源；
只有旧binary和 `dpkg-query` 摘要不能证明package状态可以一致回滚。
也可采用独立记录且可回滚的package diversion方案，但不能混用两种所有权策略。
安装前后逐项核对并保存新identity。回滚同时恢复正式入口的quota拒绝，
不能因回滚而绕过quota门。APT下载cache、安装packageDB/log和本地deb持久留存
必须另计入明确空间预留，不能把64MiB构建scratch宣称为所有系统写入的硬配额。

官方 [固定bwrap.xml](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.2/bwrap.xml)
保留 `--unshare-pid`、`--info-fd`、`--die-with-parent` 和 `--new-session`。
`--size BYTES`只作用于下一项 `--tmpfs`，后续tmpfs会恢复默认；每个需要有界的可写tmpfs
都必须单独指定size。保持仓库外层监督器的独立PID namespace、真实info-fd与pidfd绑定、
wrapper实际wait和namespace退出观察；保留内层角色的原参数及v3 `/tmp` 512MiB上限。
不能删除独立PID namespace、伪造info-fd、使用 `--as-pid-1` 或回退旧mount policy。

真实小型验收须限制运行30秒、日志64KiB、最大尝试写入2MiB，且不读取科研/认证文件：

1. 核对安装后的version/hash/help及 `require_bounded_bwrap()`；help只是能力预检。
2. 在独立user/PID namespace、只读系统映射中使用 `--size 1048576 --tmpfs /tmp`，
   child以64KiB chunks尝试最多2MiB；核对 `statvfs` 总容量不超过1MiB，并要求内核返回
   `ENOSPC`。记录实际写入量和返回值，不把计划上限当作强制成功证明。
3. 通过真实private FD取得JSON `child-pid`，在child仍存活时核对父子关系和PID namespace
   identity，再观察wrapper实际wait及namespace退出；清理若不可观察则保留失败/未知。
4. 外层独立tmpfs挂载根另做同等小额越限检查、mount身份核对及容量守卫检查。
   私有 `/tmp` 的成功不能证明外层scratch、宿主卷余量或VHD映射已经通过。

这些局部检查只验证runtime修复及quota/退出链的范围，不授予旧证据、新安装或完整HM资格。
失败和拒绝原件保留，后继正式工作仍须冻结新的源码、wheel、installation及管理绑定。
