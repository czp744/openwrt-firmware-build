# OpenWrt x86/64 UEFI 通用预装镜像

此仓库仅通过 GitHub 托管的 Ubuntu 24.04 runner 运行官方 OpenWrt 25.12.6 Generic ImageBuilder。目标为 Intel Pentium Gold 7505、约 8GB RAM、512GB SSD、六个 Intel I226-V 网口的 UEFI 设备。构建成功不代表已经通过实机测试。

软件版本与来源固定在 `sources.lock.json`，请求的包见 `packages.txt`。包括 LuCI HTTPS、包管理、PBR、诊断工具、ZeroTier、流量统计、PPPoE、OpenClash 0.48.002 APK 和 Mihomo 1.19.33 amd64-v1。完整依赖版本由官方 APK 仓库解析后锁定用于同一次镜像构建；实际安装清单和下载包 SHA256 随构建记录交付。官方 feed 可能后续更新，若需长期完全重现还需保存对应 APK 文件，不能只依赖包名或版本号。

保留官方 Generic 默认驱动、安全组件和 IPv6，包括 `kmod-igc`、firewall4、odhcp6c、odhcpd-ipv6only。OpenClash 依赖 `dnsmasq-full`，因此用它替代 `dnsmasq`，保留官方 DHCP/DNS 配置；使用 `ip-full` 替代有冲突的小版本。根分区设为 1024 MiB，不扩展或写入实际 SSD。

OpenClash、PBR 和 ZeroTier 默认不启动。没有节点、订阅、用户密码、ZeroTier 身份或针对具体服务的路由规则。保留 OpenClash 上游通用数据库与功能资源；不代表已经配置任何代理策略。OpenClash 首次启动初始化文件保持上游内容，设备启动时可产生设备自身的新随机管理密钥，镜像不包含预置密钥。后续启用插件、加入 ZeroTier 网络和策略配置由用户另行决定。

工作流仅手动触发，不发布 GitHub Release、不部署或刷机。权限只有 `contents: read`，checkout 不保存凭证，Actions 固定至提交 SHA。下载仅使用官方 OpenWrt 与两个项目的上游 GitHub 发布，并在解包前对照固定 SHA256。ImageBuilder 的 APK 安装使用 `--no-scripts`；OpenClash 的安装脚本被记录，构建阶段的 post-install 设为 no-op，且不在构建主机加载其 init 脚本。其他官方包按官方 ImageBuilder 处理；OpenClash 运行文件保留。

构建脚本对 25.12.6 ImageBuilder 的包版本格式化循环加入变量重置，修复同时使用完整版本锁定和默认包时版本串被错误沿用的问题。此修正不删除默认包，修改后的 Makefile 随构建记录保存。

成功产物为 `openwrt-25.12.6-x86-64-uefi` artifact：

- `*generic-ext4-combined-efi.img.gz` 与 `*generic-squashfs-combined-efi.img.gz`。
- `SHA256SUMS`、`installed-packages.txt`、`sources.lock.json`、`verification.json` 与 Mihomo 版本记录。
- 完整构建日志、安装包记录、APK 元数据和修改记录位于 `openwrt-build-records` artifact。保留期 7 天，请及时下载保存。

验证检查下载哈希、APK 依赖解析、所有请求包、igc 内核模块、Mihomo 版本与静态 ELF、服务关闭状态，以及两个最终镜像的 gzip 完整性、GPT 校验、EFI x86-64 引导文件、根文件系统和关键文件哈希。没有运行虚拟机或硬件启动测试，没有测试六个网口的实际顺序、链路、PPPoE、代理、ZeroTier 或吞吐量。UEFI Secure Boot 兼容性也未验证。镜像不是对实机可用性的保证。

首次使用仍按官方默认网络行为处理，网口映射和管理口需要现场确认。本项目不修改现有路由、不设置双 WAN 自动切换、不启用流量管控、不包含 mosdns、AdGuard Home 或 ZTNet。请不要直接对正在使用的磁盘进行未经确认的写入。

上游来源：

- https://downloads.openwrt.org/releases/25.12.6/targets/x86/64/
- https://github.com/vernesong/OpenClash/releases/tag/v0.48.002
- https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.33
