# AI 研究构建（x64）

`DBKKernel.vcxproj` 保留上游的 VS/WDK 工程配置。由于新 WDK 不再接受该工程的旧 `KMDF 1.9 + Windows 7` 元数据，Agent 构建使用旁路脚本 `build-ai-wdm-x64.ps1`。

它直接调用 MSVC `cl.exe`、`ml64.exe` 和 `link.exe`，使用 WDK 的内核头文件/库及同版本 Windows SDK 的公共头，按 WDM 驱动链接。未签名产物不设置 PE `Force Integrity` 标志。它不会运行 KMDF/INF/INF2CAT、签名、部署、服务安装或 UDL 加载步骤，也不会覆盖 `Cheat Engine\bin`。

AI 构建定义 `CEAI_UDL_COMPAT=1`。当 UDL/手动装载器创建了服务但没有提供 CE 原有的注册表 `A/B/C/D` 临时值时，驱动回退到固定契约：设备 `\Device\CEDRIVER73`、符号链接 `\DosDevices\CEDRIVER73`、事件 `DBKProcList60` 与 `DBKThreadList60`。普通上游工程不定义该宏，仍严格要求 `A/B/C/D`；`RegistryPath=nil` 的 DBVM 内部装载语义也不改变。

推荐由结构化 CLI 调用：

```powershell
ce-ai --json driver build F:\aicoding\ce1\cheat-engine `
  --wdk-root F:\tools\wdk-nuget\10.0.26100.6584\extracted\c `
  --vc-tools-root D:\VSBuildTools\VC\Tools\MSVC\14.44.35207 `
  --output F:\aicoding\ce1\.runtime\dbk-ai-x64
```

输出 JSON 包含 `.sys` 路径、大小、SHA-256、PE 架构、子系统和签名状态。构建成功不代表驱动已经加载；加载仍需单独使用 `ce-ai driver load <exact-path> --yes`。
