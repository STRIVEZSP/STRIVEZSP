# scripts/update_readme.py
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

# 获取全部非 fork 仓库，根据 pushed_at 排序
repos = sorted(
    [repo for repo in user.get_repos() if not repo.fork],
    key=lambda r: r.pushed_at or datetime.min.replace(tzinfo=timezone.utc),
    reverse=True
)

latest_repos = repos[:6]

project_icons = {
    'AI-tiku': '🧠',
    'CloudPix': '☁️',
    'LangChain4j-study-java': '🧩',
    'CARDON-AI-predict': '📈',
    'profile': '👤',
    'ZSPSTRIVE': '👤'
}

# 构造表格
table = "### 🆕 最新更新项目\n\n"
table += "| 项目名 | 简介 | 技术栈 | Stars |\n"
table += "|:--------|:------|:--------|:------|\n"

for r in latest_repos:
    icon = project_icons.get(r.name, "🚀")
    desc = (r.description or "暂无描述").replace("|", "｜")
    if len(desc) > 50:
        desc = desc[:47] + "..."
    tech_stack = r.language or "Mixed"

    table += f"| {icon} [{r.name}]({r.html_url}) | {desc} | {tech_stack} | ⭐ {r.stargazers_count} |\n"

# 北京时间
beijing_time = datetime.now(timezone.utc) + timedelta(hours=8)
table += f"\n> 🕒 最后更新: {beijing_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)\n"

# 写回 README
readme_path = "README.md"
if not os.path.exists(readme_path):
    raise FileNotFoundError("未找到 README.md 文件")

with open(readme_path, "r", encoding="utf-8") as f:
    readme = f.read()

# 更稳健的正则匹配
pattern = r"(<\!-- PROJECTS-LIST:START -->)(.*?)(<\!-- PROJECTS-LIST:END -->)"
replacement = r"\1\n{}\n\3".format(table)

updated = re.sub(pattern, replacement, readme, flags=re.S)

with open(readme_path, "w", encoding="utf-8") as f:
    f.write(updated)

print(f"✅ README 已刷新，最新项目数量: {len(latest_repos)}")
