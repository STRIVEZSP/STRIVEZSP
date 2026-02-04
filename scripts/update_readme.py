# scripts/update_readme_dual.py
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from github import Github, Auth
from github.Repository import Repository


# ===============================
# 0. 配置
# ===============================
USERNAME = "ZSPSTRIVE"
README_PATH = "README.md"
LATEST_N = 6
TOP_STAR_N = 6

# 项目图标配置（没有就走 DEFAULT_ICON）
# 使用 Phosphor Icons (Bold) via Iconify
ICON_BASE = "https://api.iconify.design/ph:{name}.svg?color=%23000000"

def _get_icon_img(name: str) -> str:
    url = ICON_BASE.format(name=name)
    return f'<img src="{url}" width="20" height="20" style="vertical-align:middle; margin-right:4px;" />'

PROJECT_ICONS: Dict[str, str] = {
    "AI_Movie": _get_icon_img("film-strip-bold"),
    "SpringAI-langchain-StudyBot": _get_icon_img("robot-bold"),
    "AI-tiku": _get_icon_img("brain-bold"),
    "AIMovie": _get_icon_img("film-slate-bold"),
}
DEFAULT_ICON = _get_icon_img("rocket-launch-bold")

# 时区：UTC+8
TZ_CN = timezone(timedelta(hours=8))


# ===============================
# 1. GitHub Token
# ===============================
token = os.getenv("GITHUB_TOKEN")
if not token:
    raise RuntimeError("未检测到 GITHUB_TOKEN 环境变量，请在 workflow 中传入。")

gh = Github(auth=Auth.Token(token))


# ===============================
# 2. 工具函数
# ===============================
def _tz_aware(dt: Optional[datetime]) -> datetime:
    """PyGithub 返回的 datetime 有时是 naive，有时是 aware；统一成 aware。"""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sanitize_md(text: str, max_len: int = 45) -> str:
    """清理 Markdown 表格中的描述：去掉换行、替换竖线、截断。"""
    t = (text or "暂无描述").strip()
    t = t.replace("|", "｜").replace("\r", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    if len(t) > max_len:
        t = t[: max_len - 3] + "..."
    return t


def _build_table(repos: List[Repository], title: str) -> str:
    """构造与你当前 README 一致的表格块（标题+表格）。"""
    lines: List[str] = []
    lines.append(f"### {title}")
    lines.append("")
    lines.append("| 项目名 | 简介 | 技术栈 | Stars |")
    lines.append("|:--------|:------|:--------|:------|")

    for r in repos:
        icon = PROJECT_ICONS.get(r.name, DEFAULT_ICON)
        desc = _sanitize_md(r.description or "暂无描述", max_len=45)
        tech_stack = (r.language or "Mixed").replace("|", "｜")
        lines.append(
            f"| {icon} [{r.name}]({r.html_url}) | {desc} | {tech_stack} | ⭐ {r.stargazers_count} |"
        )

    return "\n".join(lines)


def _remove_represent_block(readme: str) -> str:
    """
    删除旧的“🎊代表项目”区域（如果存在）。
    用更严格的锚点：从 '### 🎊代表项目' 开始，删到下一个 '### 🆕 最新更新项目' 或 PROJECTS-LIST 起始标记之前。
    """
    pattern = re.compile(
        r"^###\s*🎊代表项目[\s\S]*?(?=^###\s*🆕\s*最新更新项目|^<!--\s*PROJECTS-LIST:START\s*-->)",
        re.MULTILINE,
    )
    return re.sub(pattern, "", readme).strip() + "\n"


def _replace_projects_block(readme: str, new_block: str) -> str:
    """
    只替换 PROJECTS-LIST 标记之间的内容；若不存在标记，则追加到文件末尾。
    """
    pattern = re.compile(
        r"(<!--\s*PROJECTS-LIST:START\s*-->)([\s\S]*?)(<!--\s*PROJECTS-LIST:END\s*-->)",
        re.MULTILINE,
    )

    if pattern.search(readme):
        return re.sub(pattern, new_block, readme, count=1).rstrip() + "\n"

    # 如果 README 没有标记，直接在末尾追加一个项目块（不影响你顶部横幅与介绍）
    return (readme.rstrip() + "\n\n" + new_block + "\n").rstrip() + "\n"


# ===============================
# 3. 拉取所有非 fork 仓库（可选过滤 archived）
# ===============================
user = gh.get_user(USERNAME)

repos: List[Repository] = [
    repo for repo in user.get_repos()
    if not repo.fork and not getattr(repo, "archived", False)
]

# 最新更新项目：按 pushed_at 倒序，稳定排序加 name 作为 tie-breaker
latest_repos = sorted(
    repos,
    key=lambda r: (_tz_aware(r.pushed_at), r.name.lower()),
    reverse=True,
)[:LATEST_N]

# Star 数最多项目：按 stars 倒序，稳定排序加 name
top_star_repos = sorted(
    repos,
    key=lambda r: (r.stargazers_count, r.name.lower()),
    reverse=True,
)[:TOP_STAR_N]

latest_table = _build_table(latest_repos, "🆕 最新更新项目")
star_table = _build_table(top_star_repos, "🌟 Star 最多项目")

now_cn = datetime.now(timezone.utc).astimezone(TZ_CN)
footer = f"> 🕒 最后更新: {now_cn.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)"

# 生成完整替换块（保持你 README 原有结构：只更新这个区域）
replacement_block = "\n".join(
    [
        "<!-- PROJECTS-LIST:START -->",
        "",
        latest_table,
        "",
        "",
        star_table,
        "",
        "",
        footer,
        "",
        "<!-- PROJECTS-LIST:END -->",
    ]
)

# ===============================
# 4. 更新 README
# ===============================
with open(README_PATH, "r", encoding="utf-8") as f:
    readme = f.read()

readme = _remove_represent_block(readme)
updated = _replace_projects_block(readme, replacement_block)

with open(README_PATH, "w", encoding="utf-8") as f:
    f.write(updated)

print("✅ README 已成功更新：项目列表块已刷新（最新项目 + Star 项目），并移除 🎊代表项目（如存在）")
