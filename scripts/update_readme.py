# scripts/update_readme_dual.py
from github import Github
import os
import re
from datetime import datetime, timedelta, timezone

# 获取 GitHub Token
token = os.getenv("GITHUB_TOKEN")
if not token:
    raise RuntimeError("未检测到 GITHUB_TOKEN 环境变量，请在 workflow 中传入。")

g = Github(token)
username = "ZSPSTRIVE"
user = g.get_user(username)

# 获取全部非 fork 仓库
repos = [repo for repo in user.get_repos() if not repo.fork]

# 最新更新项目（按 pushed_at 排序，取前6个）
latest_repos = sorted(
    repos,
    key=lambda r: r.pushed_at or datetime.min.replace(tzinfo=timezone.utc),
    reverse=True
)[:6]

# 最多 Star 项目（按 stargazers_count 排序，取前6个）
top_star_repos = sorted(repos, key=lambda r: r.stargazers_count, reverse=True)[:6]

 

def build_table(repos, title):
    """根据仓库列表构造 Markdown 表格"""
    table = f"### {title}\n\n"
    table += "| 项目名 | 简介 | 技术栈 | Stars |\n"
    table += "|:--------|:------|:--------|:------|\n"
    for r in repos:
        icon = project_icons.get(r.name, "🚀")
        desc = (r.description or "暂无描述").replace("|", "｜")
        if len(desc) > 50:
            desc = desc[:47] + "..."
        tech_stack = r.language or "Mixed"
        table += f"| {icon} [{r.name}]({r.html_url}) | {desc} | {tech_stack} | ⭐ {r.stargazers_count} |\n"
    return table

# 构造两个表格
latest_table = build_table(latest_repos, "🆕 最新更新项目")
star_table = build_table(top_star_repos, "🔥 最受欢迎项目")

# 北京时间
beijing_time = datetime.now(timezone.utc) + timedelta(hours=8)
footer = f"\n> 🕒 最后更新: {beijing_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)\n"

# 写回 README
readme_path = "README.md"
if not os.path.exists(readme_path):
    raise FileNotFoundError("未找到 README.md 文件")

with open(readme_path, "r", encoding="utf-8") as f:
    readme = f.read()

# 使用稳健正则匹配更新标记区块
pattern = r"(<\!-- PROJECTS-LIST:START -->)(.*?)(<\!-- PROJECTS-LIST:END -->)"
replacement = r"\1\n{}\n{}\n{}\n\3".format(latest_table, star_table, footer)

updated = re.sub(pattern, replacement, readme, flags=re.S)

with open(readme_path, "w", encoding="utf-8") as f:
    f.write(updated)

print(f"✅ README 已刷新，同时显示最新更新项目和 Star 数最多项目")
