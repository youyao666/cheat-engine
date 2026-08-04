# Cheat Engine AI 研究版

这是 [Cheat Engine](https://github.com/cheat-engine/cheat-engine) 的研究分支，保留 CE 原有的扫描、调试、反汇编、自动汇编、地址表和 Lua 能力，并增加面向 AI Agent 的结构化控制层。项目目标是让经过授权的逆向分析工作可以通过命令行和 JSON 接口稳定执行，而不依赖 GUI 坐标点击。

> 仅用于你拥有或明确获授权的软件、驱动和实验环境。内核驱动、DBVM 和任意 Lua 执行都可能导致系统崩溃、数据损坏或安全风险，请在隔离的研究环境中使用。

## 主要扩展

### 面向 AI 的 CLI

`cli-anything/agent-harness` 提供 `ce-ai` 命令。它连接正在运行的源码版 CE，通过本地命名管道调用 CE 的真实引擎，并支持机器可读的 JSON 输出。CLI 不重新实现 CE 的扫描器或调试器，而是把请求转发给 CE 本身。

当前命令面包括：

- 会话和应用：`session`、`app`
- 进程和模块：`process`、`module`、`symbol`
- 内存和反汇编：`memory regions`、`memory read`、`memory write`、`memory disassemble`
- 扫描：AOB 扫描，以及基于 CE 原生 `TMemScan` 的 First/Next 数值搜索
- 调试：Windows、VEH、DBVM 接口，断点设置、删除、继续和单步
- 驱动：UDL 状态、设备连接、旁路 WDM 构建，以及明确确认后的加载/卸载
- 虚拟化：DBVM 前置条件、版本、空闲页和启动状态
- Lua：`lua exec` 执行内联脚本或 UTF-8 文件

`lua exec` 是有意保留的无限制扩展入口。它可以调用 CE 注册的 Lua API，包括地址表、内存记录、扫描器、Auto Assembler、UI、插件、DBK、DBVM 和其他组件；因此没有单独 CLI 子命令的 CE 功能仍可由 Agent 通过 Lua 使用。持有状态文件令牌等价于拥有源码 CE 进程内的高权限执行能力。

## 工作方式

```text
AI Agent / shell
        |
        v
ce-ai --json ...
        |  本地命名管道 + 随机令牌
        v
ceai_bridge.lua（CE autorun）
        |
        v
Cheat Engine Lua API 与原生 CE 引擎
        |
        +--> 用户态进程、扫描、符号、反汇编、断点
        +--> DBK 内核传输
        +--> DBVM CR3/NPT 或 EPT 内存路径
```

桥接层每个进程使用独立的命名管道和状态文件，请求长度限制为 1 MiB；普通内存写入要求显式 `--yes`。`lua exec` 不做内容过滤，因此状态文件和令牌必须按管理员级凭据保护。

## DBK 与 DBVM

DBK 和 DBVM 是两个不同层级：

- DBK 是内核驱动传输层，负责设备通信、进程和内核地址访问。
- DBVM 是硬件虚拟化层。Intel 使用 VMX/EPT；AMD 使用 SVM/VMCB/NPT。连接 DBK 不代表 DBVM 已经启动。
- DBVM 调试器成功附加后会记录目标进程的 CR3。匹配该进程句柄的内存读取、写入和区域查询优先使用 CR3 路径，失败时回退到 CE 配置的后端；调试分离时会清理上下文。

源码中包含 AMD-V/SVM 的 VMCB、VMMCALL 和 NPT 路径，但当前开发机的 DBVM 端到端验证使用的是 Intel VT-x/EPT。AMD 主机需要在 BIOS/UEFI 启用 `SVM Mode`，并确保没有 Hyper-V/VBS 或其他 hypervisor 占用虚拟化扩展；在 AMD 真机上仍应单独完成启动验证。

## 快速开始

### 1. 构建 CE

按照上游说明安装 Lazarus/FPC，然后打开 `Cheat Engine/cheatengine.lpi` 构建 64 位版本。DBVM 使用相邻的 `Cheat Engine/bin/vmdisk.img`。

### 2. 安装 Agent CLI 和桥接

```powershell
cd cli-anything\agent-harness
python -m pip install -e .
powershell -File bridge\install_bridge.ps1 -CheatEngineDir "F:\path\to\cheat-engine"
```

重启源码版 CE 后，可以使用：

```powershell
ce-ai --json session info
ce-ai --json process list
ce-ai --json process open <pid>
ce-ai --json memory regions --readable-only
ce-ai --json scan aob "48 8B ?? ?? 89"
ce-ai --json scan new
ce-ai --json scan first --option exact --type dword --value 100
ce-ai --json scan next --option increased
ce-ai --json debug attach --interface dbvm
ce-ai --json lua exec "return getOpenedProcessID()"
```

完整 CLI 说明见 [cli-anything/agent-harness/cli_anything/cheat_engine/README.md](cli-anything/agent-harness/cli_anything/cheat_engine/README.md) 和 [CE.md](cli-anything/agent-harness/CE.md)。

### 3. 构建研究用 DBK

上游 `DBKKernel.vcxproj` 使用较旧的 KMDF/WDK 元数据。此分支提供独立的 x64 WDM 旁路构建脚本：

```powershell
ce-ai --json driver build F:\path\to\cheat-engine `
  --wdk-root F:\tools\wdk-nuget\10.0.26100.6584\extracted\c `
  --vc-tools-root D:\VSBuildTools\VC\Tools\MSVC\14.44.35207
```

脚本只编译并链接未签名 `.sys`，不会自动安装、启动、签名或加载驱动。构建细节见 [DBKKernel/AI_BUILD.md](DBKKernel/AI_BUILD.md)。如使用 UDL 或其他手动装载器，请先确认驱动路径和设备名，再由 Agent 执行只读设备连接检查。

## 已验证能力

当前分支已经完成并验证：

- 本地 token-authenticated CE bridge 和 JSON CLI；
- 进程、模块、符号、内存区域、读写和反汇编；
- AOB 以及 First/Next 数值搜索；
- 断点、继续、单步和 DBVM 调试器接口；
- DBK 设备连接与 DBVM 状态/启动控制；
- DBVM CR3 内存路径与受限/PPL 进程的只读对照；
- 任意 CE Lua、Auto Assembler、临时地址表和扫描器调用；
- 结构化 CLI 的 Python 回归测试。

测试清单和实测边界见 [cli-anything/agent-harness/cli_anything/cheat_engine/tests/TEST.md](cli-anything/agent-harness/cli_anything/cheat_engine/tests/TEST.md)。

## 当前边界

这不是把所有 CE 附属项目都预编译进一个包：Speedhack、VEH、Mono/.NET、Java、TCC、DirectX 等能力仍需要按上游说明分别构建对应 DLL、EXE 或库。指针扫描、Ultimap 和部分高级工作流目前没有全部做成专用 CLI 子命令，但可在相关组件可用时通过 `lua exec` 调用 CE API。

DBVM 启动是主机级状态切换，失败后不要盲目重复启动；启动后应立即用 `dbvm status` 检查 `running`、版本和空闲页。驱动加载和内核内存访问也必须限定在授权的实验目标上。

## 上游与许可证

本项目基于上游 [cheat-engine/cheat-engine](https://github.com/cheat-engine/cheat-engine)。CE 的原始许可证、第三方组件许可和构建要求以仓库内文件及上游项目说明为准。
