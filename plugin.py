# -*- coding: utf-8 -*-
"""QwenPaw Browser Harness Plugin — 自愈浏览器控制。

PluginApi 入口。启动时检测 browser-harness 环境、
启动 daemon、写入 stdio MCP 配置。不启动任何服务器。
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
from pathlib import Path

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_plugin_dir = Path(__file__).resolve().parent


class BrowserHarnessPlugin:
    """Browser Harness for QwenPaw — 薄壳，接近裸 CDP。"""

    def __init__(self):
        self._api: PluginApi | None = None
        self._harness_path: Path | None = None
        self._helpers_path: Path | None = None
        self._domain_skills_dir: Path | None = None
        self._daemon_proc: subprocess.Popen | None = None

    # ── PluginApi 入口 ──────────────────────────────────

    def register(self, api: PluginApi) -> None:
        """注册插件到 QwenPaw。"""
        self._api = api
        self._load_meta()
        self._locate_harness()

        api.register_startup_hook(
            hook_name="browser_harness_init",
            callback=self._on_startup,
            priority=100,
        )
        api.register_shutdown_hook(
            hook_name="browser_harness_stop",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info("✓ Browser Harness plugin registered")

    # ── 启动/关闭 ────────────────────────────────────────

    def _on_startup(self) -> None:
        logger.info("[BrowserHarness] 启动中...")
        self._check_chrome_cdp()
        self._ensure_daemon()
        self._ensure_skill_available()

        # 生成并写入所有 Agent 的 MCP 配置（安装时自动注入）
        self._install_mcp_config()

        if self._harness_path:
            logger.info(f"[BrowserHarness] ✅ harness: {self._harness_path}")
        else:
            logger.warning("[BrowserHarness] ⚠️ browser-harness 未安装")
        logger.info(f"[BrowserHarness] ✅ 就绪")

    def _install_mcp_config(self) -> None:
        """自动将 MCP 配置注入所有 Agent 的 agent.json。"""
        mcp_script = _plugin_dir / "mcp_server.py"
        mcp_client = {
            "name": "browser_harness_mcp",
            "description": "Browser Harness MCP (Chrome CDP 自愈浏览器控制)",
            "enabled": True,
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(mcp_script)],
            "env": {"HARNESS_DIR": str(self._harness_path)} if self._harness_path else {},
            "cwd": "",
        }

        # 扫描所有 Agent 工作区
        ws_dir = Path.home() / ".qwenpaw" / "workspaces"
        if not ws_dir.is_dir():
            logger.warning("[BrowserHarness] 未找到工作区目录")
            return

        for agent_dir in ws_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_json = agent_dir / "agent.json"
            if not agent_json.is_file():
                continue

            try:
                with open(agent_json) as f:
                    config = json.load(f)

                clients = config.setdefault("mcp", {}).setdefault("clients", {})
                if "browser_harness" in clients:
                    logger.info(f"[BrowserHarness] ℹ️ {agent_dir.name}: 已存在，跳过")
                    continue

                clients["browser_harness"] = mcp_client

                with open(agent_json, "w") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                logger.info(f"[BrowserHarness] ✅ {agent_dir.name}: MCP 已注入")
            except Exception as e:
                logger.error(f"[BrowserHarness] ❌ {agent_dir.name}: {e}")

    def _check_opencli(self) -> None:
        """检测 OpenCLI 是否可用。"""
        try:
            r = subprocess.run(
                ["opencli", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                ver = r.stdout.strip()
                logger.info(f"[BrowserHarness] ✅ OpenCLI: {ver}")
            else:
                logger.info("[BrowserHarness] ⚠️ OpenCLI 未安装 (npm i -g @jackwener/opencli)")
        except FileNotFoundError:
            logger.info("[BrowserHarness] ⚠️ OpenCLI 未安装 (npm i -g @jackwener/opencli)")
        except Exception as e:
            logger.info(f"[BrowserHarness] ⚠️ OpenCLI 检测失败: {e}")

    def _on_shutdown(self) -> None:
        self._stop_daemon()
        logger.info("[BrowserHarness] 已停止")

    # ── 配置读取 ────────────────────────────────────────

    def _load_meta(self) -> None:
        meta = self._api.manifest.get("meta", {})
        self._chrome_port = meta.get("chrome_port", 9222)
        self._skill_dir = meta.get("skill_dir", "domain-skills")

    def _locate_harness(self) -> None:
        import os
        meta = self._api.manifest.get("meta", {})
        custom = meta.get("harness_repo", "")
        candidates = []
        if custom:
            candidates.append(Path(custom))
        env_val = os.environ.get("HARNESS_DIR", "")
        if env_val:
            candidates.append(Path(env_val))
        candidates += [
            Path.home() / "Developer/browser-harness",
            Path.home() / "src/browser-harness",
            Path.home() / "browser-harness",
            Path("/opt/browser-harness"),
        ]
        for p in candidates:
            if (p / "run.py").is_file() and (p / "helpers.py").is_file():
                self._harness_path = p
                self._helpers_path = p / "helpers.py"
                self._domain_skills_dir = p / self._skill_dir
                return

        logger.warning(
            "[BrowserHarness] browser-harness 未找到，"
            "设 meta.harness_repo 或 HARNESS_DIR 环境变量，"
            "或 git clone https://github.com/browser-use/browser-harness"
        )

    # ── Chrome CDP ─────────────────────────────────────

    def _check_chrome_cdp(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", self._chrome_port))
        sock.close()
        if result != 0:
            logger.warning(
                f"[BrowserHarness] Chrome CDP (:{self._chrome_port}) 未响应。"
                "  google-chrome --remote-debugging-port=9222"
            )
        else:
            logger.info(f"[BrowserHarness] ✅ Chrome CDP :{self._chrome_port}")

    # ── Daemon ──────────────────────────────────────────

    def _ensure_daemon(self) -> None:
        if not self._harness_path:
            return
        if self._daemon_alive():
            logger.info("[BrowserHarness] daemon 运行中")
            return
        self._start_daemon()

    def _daemon_alive(self) -> bool:
        if not self._harness_path:
            return False
        try:
            r = subprocess.run(
                [sys.executable, str(self._harness_path / "admin.py"), "status"],
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _start_daemon(self) -> None:
        if not self._harness_path:
            return
        try:
            proc = subprocess.Popen(
                [sys.executable, str(self._harness_path / "admin.py"), "start"],
                cwd=self._harness_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            import time
            for _ in range(10):
                time.sleep(0.5)
                if self._daemon_alive():
                    self._daemon_proc = proc
                    logger.info("[BrowserHarness] daemon 已启动")
                    return
            logger.warning("[BrowserHarness] daemon 启动超时")
        except Exception as e:
            logger.error(f"[BrowserHarness] daemon 启动失败: {e}")

    def _stop_daemon(self) -> None:
        if self._daemon_proc:
            self._daemon_proc.terminate()
            self._daemon_proc.wait(timeout=5)
            logger.info("[BrowserHarness] daemon 已停止")

    # ── Skill 可用性 ──────────────────────────────────

    def _ensure_skill_available(self) -> None:
        """确保 browser-harness SKILL.md 对 QwenPaw 可见。"""
        if not self._harness_path:
            return
        skill_src = self._harness_path / "SKILL.md"
        if not skill_src.is_file():
            return
        qwenpaw_skills = Path.home() / ".qwenpaw" / "skills" / "browser-harness"
        qwenpaw_skills.mkdir(parents=True, exist_ok=True)
        target = qwenpaw_skills / "SKILL.md"
        if not target.exists():
            import shutil
            shutil.copy2(skill_src, target)
            logger.info(f"[BrowserHarness] SKILL.md 已同步到 {target}")

    # ── MCP 配置（stdio 模式） ─────────────────────────

    def _generate_mcp_config(self) -> dict:
        """生成 stdio MCP 配置。"""
        mcp_script = _plugin_dir / "mcp_server.py"
        env = {}
        if self._harness_path:
            env["HARNESS_DIR"] = str(self._harness_path)
        return {
            "mcp": {
                "clients": {
                    "browser_harness": {
                        "name": "browser_harness_mcp",
                        "enabled": True,
                        "transport": "stdio",
                        "env": env,
                        "command": sys.executable,
                        "args": [str(mcp_script)],
                    }
                }
            }
        }

    def _write_mcp_config(self, config: dict) -> None:
        """写入 MCP 配置供用户导入。"""
        out = _plugin_dir / "mcp-config.json"
        try:
            with open(out, "w") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info(f"[BrowserHarness] MCP 配置: {out}")
        except Exception as e:
            logger.error(f"[BrowserHarness] MCP 配置写入失败: {e}")


plugin = BrowserHarnessPlugin()
