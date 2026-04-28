#!/usr/bin/env python3
"""Browser Harness MCP Server — FastMCP stdio 模式。

QwenPaw 将此脚本作为子进程启动，通过 stdio 通信。
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("browser-harness")

# ── 路径自发现 ───────────────────────────────────────

def _find_harness() -> Path | None:
    candidates = []
    env = os.environ.get("HARNESS_DIR", "")
    if env:
        candidates.append(Path(env))
    candidates += [
        Path.home() / "Developer/browser-harness",
        Path.home() / "src/browser-harness",
        Path.home() / "browser-harness",
        Path("/opt/browser-harness"),
    ]
    for p in candidates:
        if (p / "run.py").is_file() and (p / "helpers.py").is_file():
            return p
    return None

HARNESS = _find_harness()
HELPERS = HARNESS / "helpers.py" if HARNESS else None
SKILL_DIR = HARNESS / "domain-skills" if HARNESS else None
INTERACTION_SKILLS_DIR = HARNESS / "interaction-skills" if HARNESS else None

# ── 安全黑名单 ──────────────────────────────────────

BLOCKED_PATTERNS = [
    "os.system", "subprocess.run", "subprocess.Popen",
    "shutil.rmtree", "os.remove", "os.unlink", "os.rmdir",
    "Path.unlink", "Path.rmdir",
    "__import__", "compile(", "eval(", "exec(",
]

def _check_safe(code: str) -> None:
    """String-level security check."""
    for pat in BLOCKED_PATTERNS:
        if pat in code:
            raise ValueError(f"禁止的操作: {pat}")

def _validate_ast(code: str) -> None:
    """AST-level security check."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"语法错误: {e}")

    dangerous_modules = {'os', 'subprocess', 'sys', 'shutil', 'socket', 'pathlib'}
    dangerous_calls = {'eval', 'exec', 'compile', '__import__', 'open'}
    
    for node in ast.walk(tree):
        # 1. Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in dangerous_modules:
                    raise ValueError(f"禁止导入模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module in dangerous_modules:
                raise ValueError(f"禁止导入模块: {node.module}")
        
        # 2. Check dangerous calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in dangerous_calls:
                    raise ValueError(f"禁止调用函数: {node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                # Heuristic check for attribute access like os.system(...)
                # This is a simplified check; full protection requires deeper analysis
                # but catching common dangerous attribute names is better than nothing
                if node.func.attr in ['system', 'popen', 'rmtree', 'remove', 'unlink', 'rmdir']:
                    raise ValueError(f"禁止调用方法: ...{node.func.attr}")

def _count_funcs(path: Path) -> int:
    return sum(1 for l in path.read_text().splitlines() if l.strip().startswith("def "))

def _docstring(lines: list[str], i: int) -> str:
    for j in range(i + 1, min(i + 6, len(lines))):
        d = lines[j].strip()
        if d.startswith('"""') or d.startswith("'''"):
            return d.strip('"\' ')
        if d.startswith("#"):
            return d.lstrip("# ")
    return ""

# ── 工具 ────────────────────────────────────────────

@mcp.tool()
def browser_status() -> str:
    """检查 browser-harness 环境 / daemon / helpers / skills 状态。"""
    lines = []

    if HARNESS:
        try:
            # 检查 daemon 状态，这比固定端口更可靠
            r = subprocess.run(
                [sys.executable, str(HARNESS / "admin.py"), "status"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                # 尝试从输出中提取端口信息（如果存在）
                output = r.stdout.strip()
                lines.append(f"Daemon: ✅ {output}")
            else:
                lines.append(f"Daemon: ❌ (Exit {r.returncode})")
        except Exception as e:
            lines.append(f"Daemon: ❌ ({e})")
            
        if HELPERS and HELPERS.is_file():
            lines.append(f"Helpers: {_count_funcs(HELPERS)} 个函数")
        if SKILL_DIR and SKILL_DIR.is_dir():
            skills = [d.name for d in SKILL_DIR.iterdir() if d.is_dir()]
            lines.append(f"Domain skills: {len(skills)} 个")
        if INTERACTION_SKILLS_DIR and INTERACTION_SKILLS_DIR.is_dir():
            lines.append("Interaction skills: ✅")
    else:
        lines.append("browser-harness: ❌ 未安装")

    # Add Evolution Loop reminder to status
    lines.append("\n🧠 EVOLUTION LOOP PROTOCOL:")
    lines.append("1. Check `browser_helpers_list` and `browser_skill_list` for existing solutions.")
    lines.append("2. If complex UI (iframes/shadow-dom), check `browser_interaction_skills_list`.")
    lines.append("3. After success, YOU MUST call `browser_helpers_add` and `browser_skill_save`.")

    return "\n".join(lines)

@mcp.tool()
def browser_exec(code: str) -> str:
    """在 browser-harness 中执行 Python 代码 (安全沙箱)。

    Args:
        code: Python 代码 (helpers 中函数预置)
    """
    if not HARNESS:
        return "❌ browser-harness 未安装"
    try:
        _check_safe(code)
    except ValueError as e:
        return f"❌ {e}"
    try:
        r = subprocess.run(
            [sys.executable, str(HARNESS / "run.py"), "-c", code],
            capture_output=True, text=True,
            timeout=60, cwd=HARNESS,
        )
        out = r.stdout.strip()
        if r.returncode != 0 and r.stderr.strip():
            out += "\n[stderr]\n" + "\n".join(r.stderr.strip().splitlines()[-10:])
        return out or "✅ 完成"
    except subprocess.TimeoutExpired:
        return "❌ 超时 (60s)"
    except Exception as e:
        return f"❌ {e}"

@mcp.tool()
def browser_goto(url: str) -> str:
    """在浏览器中打开指定 URL。

    Args:
        url: 完整 URL
    """
    safe = json.dumps(url, ensure_ascii=False)
    return browser_exec(f"goto_url({safe})\nwait_for_load()\nprint(page_info())")

@mcp.tool()
def browser_helpers_list() -> str:
    """列出 helpers.py 中所有函数。
    
    ⚠️ CRITICAL: Before writing new code or calling `browser_helpers_add`, YOU MUST check this list to see if a helper already exists.
    """
    if not HELPERS or not HELPERS.is_file():
        return "❌ helpers.py 未找到"
    content = HELPERS.read_text()
    lines = content.splitlines()
    funcs = []
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("def "):
            name = s.split("(")[0].replace("def ", "")
            doc = _docstring(lines, i)
            funcs.append(f"  {name}(...)" + (f"  # {doc[:60]}" if doc else ""))
    return f"helpers.py — {len(funcs)} 个函数:\n\n" + "\n".join(funcs)

@mcp.tool()
def browser_helpers_add(name: str, code: str) -> str:
    """向 helpers.py 追加新函数 (AST 安全校验)。

    Args:
        name: 函数名
        code: 完整函数定义
    """
    if not HELPERS or not HELPERS.is_file():
        return "❌ helpers.py 未找到"
    existing = HELPERS.read_text()
    if f"def {name}(" in existing:
        return f"⚠️ {name} 已存在"
    code = code.strip()
    if not code.lstrip().startswith("def "):
        code = f"def {name}():\n    " + "\n    ".join(code.split("\n"))
    try:
        _validate_ast(code)
    except ValueError as e:
        return f"❌ {e}"
    try:
        with open(HELPERS, "a") as f:
            f.write(f"\n\n\n{code}\n")
        return f"✅ 已追加 {name}"
    except PermissionError:
        return "❌ 权限不足"
    except OSError as e:
        return f"❌ 文件错误: {e}"
    except Exception as e:
        return f"❌ 写入失败: {e}"

@mcp.tool()
def browser_skill_save(name: str, description: str, code: str = "",
                      selectors: str = "", notes: str = "") -> str:
    """保存流程为 domain skill。

    Args:
        name: skill 名称
        description: 描述
        code: 示例 Python 代码
        selectors: CSS 选择器
        notes: 注意事项
    """
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    if not name:
        return "❌ 无效的 skill 名称"
    desc = re.sub(r'[\n\r]', ' ', description)
    selectors = re.sub(r'[\n\r]', ' ', selectors)
    notes = re.sub(r'[\n\r]', ' ', notes)
    if not SKILL_DIR:
        return "❌ domain-skills 未配置"
    d = SKILL_DIR / name
    
    # 检查覆盖风险
    if (d / "SKILL.md").exists():
        return f"❌ 技能 '{name}' 已存在，请更换名称"

    d.mkdir(parents=True, exist_ok=True)
    
    # 代码安全检查
    if code.strip():
        try:
            _validate_ast(code)
        except ValueError as e:
            return f"❌ 代码校验失败: {e}"

    date = datetime.now().strftime("%Y-%m-%d")
    skill = f"""---
name: {name}
description: {json.dumps(desc)}
created: {date}
source: browser-harness
---

# {name}

> {desc}

## 示例代码

```python
{code or "# 待补充"}
```

## 关键选择器

```
{selectors or "# 待补充"}
```

## 注意事项

{notes or "# 无"}
"""
    (d / "SKILL.md").write_text(skill, encoding="utf-8")
    if code.strip():
        (d / "helpers.py").write_text(code, encoding="utf-8")
    return f"✅ domain-skills/{name}/"

@mcp.tool()
def browser_interaction_skills_list() -> str:
    """列出所有可用的官方交互指南 (interaction-skills)。
    
    💡 TIP: Use this tool to find guides for complex UI tasks (iframes, shadow-dom, downloads, etc.).
    Read the specific guide using `browser_interaction_skill`.
    """
    if not INTERACTION_SKILLS_DIR or not INTERACTION_SKILLS_DIR.is_dir():
        return "❌ 官方交互技能目录未找到"
    files = [f.stem for f in INTERACTION_SKILLS_DIR.iterdir() if f.is_file() and f.suffix == '.md']
    if not files:
        return "无官方交互技能文件"
    return "可用交互技能:\n" + "\n".join(f"- {f}" for f in sorted(files))

@mcp.tool()
def browser_interaction_skill(name: str) -> str:
    """获取特定交互技能的详细指南 (例如 cookies, iframes, uploads)。

    Args:
        name: 技能名称 (不带 .md 后缀)
    """
    if not INTERACTION_SKILLS_DIR or not INTERACTION_SKILLS_DIR.is_dir():
        return "❌ 官方交互技能目录未找到"
    
    file_path = INTERACTION_SKILLS_DIR / f"{name}.md"
    # 兼容用户输入完整文件名的情况
    if not file_path.exists():
        file_path = INTERACTION_SKILLS_DIR / name
    
    if not file_path.exists():
        available = [f.stem for f in INTERACTION_SKILLS_DIR.iterdir() if f.is_file() and f.suffix == '.md']
        return f"❌ 技能 '{name}' 未找到。可用: {', '.join(sorted(available))}"
    
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"❌ 读取失败: {e}"

@mcp.tool()
def browser_skill_list() -> str:
    """列出 domain skills。"""
    if not SKILL_DIR or not SKILL_DIR.is_dir():
        return "无 domain skills"
    items = []
    for d in sorted(SKILL_DIR.iterdir()):
        if not d.is_dir():
            continue
        sk = d / "SKILL.md"
        desc = ""
        if sk.exists():
            for line in sk.read_text().splitlines():
                if line.startswith("description:"):
                    desc = line.replace("description:", "").strip()
                    break
        items.append(f"  ◇ {d.name}  — {desc or '无描述'}")
    return f"Domain skills ({len(items)}):\n" + "\n".join(items) if items else "无 domain skills"

# ── 启动 ─────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
