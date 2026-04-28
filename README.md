# QwenPaw Browser Harness Plugin

这是一个为 [QwenPaw](https://github.com/agentscope-ai/QwenPaw) 设计的浏览器自动化 MCP 插件。
基于 [browser-use/browser-harness](https://github.com/browser-use/browser-harness) 构建，并进行了增强。

## ✨ 核心功能

1.  **🧠 自我进化闭环 (Self-Evolving Loop)**
    *   Agent 不仅执行任务，还会在成功后自动沉淀代码（`helpers.py`）和工作流（`domain-skills`）。
    *   内置 `self-evolution-loop.md` 技能指南，引导 Agent 遵循“先查询、后执行、最后固化”的最佳实践。

2.  **🛡️ AST 级安全沙箱 (AST-Level Security)**
    *   在 `browser_helpers_add` 和 `browser_skill_save` 中实施了严格的 Python AST 静态分析。
    *   自动拦截危险导入（`os`, `subprocess` 等）和危险调用，确保 Agent 在沙箱内安全运行。

3.  **🔗 动态端口嗅探 (Dynamic Port Sniffing)**
    *   增强了 `daemon.py`，支持自动扫描 9220-9229 端口。
    *   通过 `/json/version` 接口精准定位存活的浏览器实例，解决多开浏览器导致的连接失败问题。

4.  **📖 丰富的交互技能库 (Interaction Skills)**
    *   集成了完整的 `interaction-skills` 指南（如 iFrames, Shadow DOM, Downloads 等）。
    *   Agent 可通过工具自主查阅文档，解决复杂 UI 操作难题。

## 📂 项目结构

```text
├── plugin.py            # QwenPaw 插件入口 (MCP 配置注入)
├── mcp_server.py        # MCP Server 实现 (工具定义、安全沙箱)
└── engine/              # 浏览器引擎核心 (基于 browser-harness 修改)
    ├── daemon.py        # (已修改: 支持动态端口嗅探)
    ├── admin.py
    ├── helpers.py
    ├── run.py
    └── interaction-skills/  # 官方交互指南 + 自定义进化协议
```

## 🚀 安装与使用

### 1. 部署 Engine

```bash
# 克隆本仓库
git clone https://github.com/a1461750564/qwenpaw-browser-harness.git
cd qwenpaw-browser-harness

# 确保安装了依赖: pip install browser-harness cdp-use
```

### 2. 配置 QwenPaw 插件

将 `plugin.py` 和 `mcp_server.py` 复制到 QwenPaw 的插件目录：
`~/.qwenpaw/plugins/browser-harness/`

在 QwenPaw 配置中注册 MCP 客户端（注意修改 `env` 中的 `HARNESS_DIR` 为你克隆仓库的路径）：

```json
{
  "mcp": {
    "clients": {
      "browser_harness": {
        "name": "browser_harness_mcp",
        "enabled": true,
        "transport": "stdio",
        "command": "/path/to/your/python",
        "args": ["~/.qwenpaw/plugins/browser-harness/mcp_server.py"],
        "env": {
          "HARNESS_DIR": "/path/to/your/qwenpaw-browser-harness/engine"
        }
      }
    }
  }
}
```

## 🤝 参考与致谢

*   **Browser Harness**: [browser-use/browser-harness](https://github.com/browser-use/browser-harness) - 核心浏览器自动化引擎。
*   **QwenPaw**: [agentscope-ai/QwenPaw](https://github.com/agentscope-ai/QwenPaw) - 强大的 AI Agent 平台。

## 📜 License

本项目遵循原项目 License。
