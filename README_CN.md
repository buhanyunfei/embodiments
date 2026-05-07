# Embodiments

**可分享、可移植的包格式，让 LLM agent 系统安全地与物理机器人和传感器交互。**

> [English Documentation](./README.md)

---

## 概述

Embodiments 是一个开放标准，用于将物理硬件接口（机器人、传感器、执行器）打包为可安装、可分享、可迁移的包，让任何 LLM agent 系统都能像使用 Skills 或 MCP 一样发现、挂载和使用物理设备。

```
Agent 系统 (Codex / OpenClaw / LangGraph / 自定义)
├── MCP Servers    — 外部数据和 API 访问
├── Skills         — 可复用的任务流程 (SKILL.md)
├── Tools          — 单次调用的函数接口
└── Embodiments    — 物理世界：设备接口 + 多节点协作 (EMBODIMENT.md)
```

一个包，两个文件。下载后填入你的硬件 IP，agent 就能看到和控制物理世界。

## 核心特性

- **即插即用** — `discover() → activate() → get_tools()` 三行代码接入
- **硬件可移植** — 包只声明需要什么硬件，不包含 IP 地址；挂载时绑定端点
- **安全优先** — 默认 sensor-only，禁止动作强制执行，危险操作需人类审批
- **可分享** — 发布你的机器人 embodiment 包，任何有相同硬件的人都能直接使用
- **热插拔** — 运行时添加/移除/替换包，无需重启
- **Agent 可读** — `EMBODIMENT.md` 告诉 agent 一切：可用工具、安全规则、工作流、故障模式

## 快速开始

### 安装

```bash
pip install pyyaml  # 唯一依赖
```

### 在 agent 系统中使用

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()
loader.activate("g1_usb_dual_view", bindings={
    "robot_local_view": "http://192.168.1.100:8080",
    "external_view":    "http://192.168.1.101:8081",
})

# 注入到 agent
context = loader.get_context()    # EMBODIMENT.md → 系统提示词
tools = loader.get_tools()        # OpenAI 格式的 tool 定义

# Agent 按需调用工具
result = loader.dispatch_tool("g1_realsense_color_sensor.capture_frame", {
    "resolution": "1080p"
})
```

### 验证和构建包

```bash
# 验证
python builder/build_embodiment.py validate packages/g1_usb_dual_view

# 构建可分发的 zip
python builder/build_embodiment.py build packages/g1_usb_dual_view --out dist

# 从拓扑生成
python composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id my_lab_context \
  --out generated
```

## 包格式

两个必需文件：

```
<package>/
  EMBODIMENT.md       # agent 读取（类似 SKILL.md）
  embodiment.yaml     # runtime 读取（registry + tools + safety）
```

### 包类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `robot` | 单个机器人设备 | `unitree_g1_sensor_only` |
| `sensor` | 单个传感器设备 | `usb_1080p_camera` |
| `embodiment_context` | 多设备协作场景 | `g1_usb_dual_view` |

设备包是可分享的原子单元。场景包将它们组合成协作场景。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│ Runtime Loader (runtime/loader.py)                           │
│                                                             │
│  discover() → activate(bindings) → get_context/get_tools    │
│  dispatch_tool() → 安全门 → 合作检查 → 执行                    │
│  cooperation: approve / revoke / rollback                    │
│  hot_plug() → 运行时添加包                                    │
└─────────────────────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
  ┌──────────────┐      ┌─────────────────────────┐
  │ EMBODIMENT.md │      │ embodiment.yaml          │
  │ (agent 上下文) │      │ (registry + tools +     │
  │               │      │  cooperation + safety)   │
  └──────────────┘      └─────────────────────────┘
```

### 合作网络

人类审批控制层。控制哪些节点可以协作：

- **approve** — 节点对可以交换数据（默认状态）
- **revoke** — 边变为 dormant，该节点的工具对 agent 隐藏
- **rollback** — 原子重置所有运行时覆盖到策略文件默认值

### 安全模型

| 类别 | 行为 |
|------|------|
| `safe` | Agent 自由调用 |
| `confirmation` | 需要人类审批后才能执行 |
| `supervisor` | 需要主管 + 人类审批 |
| `forbidden` | 工具不注册，对 agent 完全不可见 |

## 项目结构

```
runtime/                    Runtime Loader（agent 系统直接 import）
  loader.py                   EmbodimentLoader + EmbodimentPackage
builder/                    离线验证器 + zip 打包器
  build_embodiment.py         validate / build / build-all
composer/                   确定性优先的包生成器
  compose_context.py          拓扑 → 上下文包
packages/                   参考包
  g1_usb_dual_view/           v3 多设备上下文包（参考实现）
  unitree_g1_sensor_only/     v2 单机器人设备包
  usb_1080p_camera/           v2 单传感器设备包
policies/                   安全策略 + 合作策略文件
specs/                      8 份权威规范文档
skills/onboard-embodiment/  即插即用设备接入 skill
templates/                  配置模板
```

## 安全保证

1. **构建离线** — 验证器永远不接触硬件
2. **安装不动** — 安装包时不触发电机命令
3. **默认 sensor-only** — 运动/操作/音频默认禁止，需显式提升
4. **无 mock 替代** — 真实设备必须存在，否则快速失败
5. **合作默认批准** — 撤销创建 dormant 边，不是删除边

## 更新日志

### v0.4.0 (2025-05)

**Runtime Loader** — 面向 agent 系统的可插拔适配器
- `EmbodimentLoader` 类：discover → activate → get_context/get_tools → dispatch_tool
- 硬件可移植：`@role:xxx` 占位符 + 挂载时绑定端点
- 合作管理：approve/revoke/rollback，dormant 边语义
- 安全门控派发：forbidden 操作隐藏，confirmation 操作包装审批流程
- 热插拔：运行时添加包无需重启

**架构精简** — 移除执行引擎
- 移除 graph 执行引擎（LangGraph/OpenClaw 等 agent 系统自行编排工作流）
- 265 行严格 `graphs:` YAML schema → 10 行 `workflows:` 索引
- 协作流程用 EMBODIMENT.md 中的 markdown 步骤描述，可读性强
- Loader 只提供 context + tools + safety gates，不做流程编排

**包可移植性** — 像 npm 包一样可分享
- `hardware_requirements` 声明需要的硬件角色
- `@role:xxx` 参数化端点（包内无 IP 地址）
- Bindings 文件模式（本地使用，不提交到仓库）
- `check_requirements()` 激活前验证硬件需求

**设备包升级**
- `unitree_g1_sensor_only` 和 `usb_1080p_camera` 现在有 `tool_interface`
- 通过 loader 暴露工具：health_check, capture_frame, get_state, record_audio
- 添加 `hardware_requirements` 实现可移植
- Registry 升级到 v2，含 `participant_type`

**Composer 精简**
- 输出 `workflows:` 索引代替冗长的 graph 定义
- 严格 profile 下始终包含标准禁止动作列表
- 完整工作流步骤在 EMBODIMENT.md 中描述

**Builder 更新**
- 接受 `workflows:` 作为 `graphs:` 的替代方案
- 新增 `_validate_workflows()` 校验工作流引用的节点
- 向后兼容：旧 `graphs:` 格式的包仍然通过验证

### v0.3.0 (2025-04)

- 双层 graph 架构（合作网络 + 执行网络）
- Agent 节点作为一等参与者（llm_agent, human_operator）
- 每节点 tool interface 含 safety_class
- 每包多 graph（通过 trigger_keywords 意图匹配）
- 合作网络规范：人类审批门控
- 集成规范：对接 Codex/OpenClaw
- 确定性优先 composer（LLM 可选，仅润色文案）

### v0.2.0 (2025-03)

- 精简 2 文件包格式（EMBODIMENT.md + embodiment.yaml）
- Builder：离线验证 + zip 打包
- Composer：拓扑 → 上下文包生成
- Onboarding skill：探测 → 生成 → 验证 → 构建
- 参考包：unitree_g1_sensor_only, usb_1080p_camera, g1_usb_dual_view

### v0.1.0 (2025-02)

- 初始规范：包格式、节点注册表、安全策略
- EMBODIMENT.md 作为 SKILL.md 风格的 agent 入口文档

## 许可证

Apache-2.0
