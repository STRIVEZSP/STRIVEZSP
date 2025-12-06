# scripts/update_readme_dual.py
from github import Github, Auth
import os
import re
from datetime import datetime, timedelta, timezone

# ===============================
# 1. GitHub Token
# ===============================
token = os.getenv("GITHUB_TOKEN")
if not token:
    raise RuntimeError("未检测到 GITHUB_TOKEN 环境变量，请在 workflow 中传入。")

g = Github(auth=Auth.Token(token))
username = "ZSPSTRIVE"
user = g.get_user(username)

# ===============================
# 2. 项目图标配置
# ===============================
project_icons = {
    "AI_Movie": "🎬",
    "SpringAI-langchain-StudyBot": "🤖",
    "AI-tiku": "🧠",
    "AIMovie": "🎞️",
  
}

DEFAULT_ICON = "🚀"

# ===============================
# 3. 拉取所有非 fork 仓库
# ===============================
repos = [repo for repo in user.get_repos() if not repo.fork]

# 最新更新项目（按 pushed_at 排序）
latest_repos = sorted(
    repos,
    key=lambda r: r.pushed_at or datetime.min.replace(tzinfo=timezone.utc),
    reverse=True
)[:6]

# Star 数最多项目
top_star_repos = sorted(
    repos,
    key=lambda r: r.stargazers_count,
    reverse=True
)[:6]

# ===============================
# 4. Markdown 表格构造器
# ===============================
def build_table(repos, title):
    table = f"### {title}\n\n"
    table += "| 项目名 | 简介 | 技术栈 | Stars |\n"
    table += "|:--------|:------|:--------|:------|\n"

    for r in repos:
        icon = project_icons.get(r.name, DEFAULT_ICON)
        desc = (r.description or "暂无描述").replace("|", "｜")
        if len(desc) > 45:
            desc = desc[:42] + "..."

        tech_stack = r.language or "Mixed"
        table += (
            f"| {icon} [{r.name}]({r.html_url}) | {desc} | {tech_stack} | ⭐ {r.stargazers_count} |\n"
        )

    return table

# 构造两个表格
latest_table = build_table(latest_repos, "🆕 最新更新项目")
star_table = build_table(top_star_repos, "🌟 Star 最多项目")

# 更新时间（北京时间）
beijing_time = datetime.now(timezone.utc) + timedelta(hours=8)
footer = f"> 🕒 最后更新: {beijing_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)"

# ===============================
# 5. 更新 README
# ===============================
readme_path = "README.md"

with open(readme_path, "r", encoding="utf-8") as f:
    readme = f.read()

# 使用更稳健的正则
pattern = r"(<!-- PROJECTS-LIST:START -->)([\s\S]*?)(<!-- PROJECTS-LIST:END -->)"

replacement_content = (
    f"<!-- PROJECTS-LIST:START -->\n\n"
    f"{latest_table}\n\n"
    f"{star_table}\n\n"
    f"{footer}\n\n"
    f"<!-- PROJECTS-LIST:END -->"
)

updated_readme = re.sub(pattern, replacement_content, readme)

with open(readme_path, "w", encoding="utf-8") as f:
    f.write(updated_readme)

print("✅ README 已成功更新（最新项目 + Star 最多项目）")
