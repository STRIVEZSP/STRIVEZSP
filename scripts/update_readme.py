# scripts/update_readme_dual.py
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import request

from github import Github, Auth
from github.Repository import Repository


# ===============================
# 0. 配置
# ===============================
USERNAME = "ZSPSTRIVE"
README_PATH = "README.md"
STAR_HISTORY_ASSET_PATH = "assets/total-stars-history.svg"
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

STAR_HISTORY_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    stargazers(first: 100, after: $cursor) {
      edges {
        starredAt
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


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


def _run_graphql(query: str, variables: Dict[str, Optional[str]]) -> Dict[str, object]:
    """使用 GraphQL 拉取 star 时间线，避免引入额外依赖。"""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = request.Request(
        "https://api.github.com/graphql",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{USERNAME}-readme-updater",
        },
    )

    with request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if body.get("errors"):
        raise RuntimeError(f"GraphQL 请求失败: {body['errors']}")

    return body["data"]


def _fetch_repo_star_dates(repo: Repository) -> List[date]:
    """获取单个仓库所有 star 的日期（转为 UTC+8，便于与 README 时间一致）。"""
    if repo.stargazers_count <= 0:
        return []

    cursor: Optional[str] = None
    dates: List[date] = []

    while True:
        data = _run_graphql(
            STAR_HISTORY_QUERY,
            {"owner": repo.owner.login, "name": repo.name, "cursor": cursor},
        )
        repository_data = data.get("repository")
        if not repository_data:
            break

        stargazers = repository_data["stargazers"]
        for edge in stargazers["edges"]:
            starred_at = edge.get("starredAt")
            if not starred_at:
                continue
            dt = datetime.fromisoformat(starred_at.replace("Z", "+00:00")).astimezone(TZ_CN)
            dates.append(dt.date())

        page_info = stargazers["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return dates


def _build_total_stars_series(
    repos: List[Repository],
    total_stars: int,
) -> List[Tuple[date, int]]:
    """按日期聚合所有仓库 star，并构造累计曲线。"""
    daily_counts: Dict[date, int] = {}

    for repo in repos:
        for star_date in _fetch_repo_star_dates(repo):
            daily_counts[star_date] = daily_counts.get(star_date, 0) + 1

    if not daily_counts:
        return [(datetime.now(TZ_CN).date(), total_stars)]

    series: List[Tuple[date, int]] = []
    running_total = 0
    for star_date in sorted(daily_counts):
        running_total += daily_counts[star_date]
        series.append((star_date, running_total))

    # 理论上两者应一致；若 GitHub 返回边界数据导致不一致，则补齐最后一个点，确保图表展示当前总数。
    if series[-1][1] != total_stars:
        series.append((datetime.now(TZ_CN).date(), total_stars))

    return series


def _build_total_stars_history_svg(
    series: List[Tuple[date, int]],
    total_stars: int,
    repo_count: int,
    subtitle: str,
) -> str:
    """生成所有项目总星数的累计趋势图 SVG。"""
    width = 960
    height = 360
    left = 72
    right = 32
    top = 72
    bottom = 52
    plot_width = width - left - right
    plot_height = height - top - bottom

    dates = [item[0] for item in series]
    start_date = dates[0]
    end_date = dates[-1]
    span_days = max((end_date - start_date).days, 1)

    y_max = max(total_stars, 1)
    y_ceiling = max(5, int(math.ceil(y_max * 1.15)))
    if y_ceiling >= 10:
        magnitude = 10 ** (len(str(y_ceiling)) - 1)
        y_ceiling = int(math.ceil(y_ceiling / magnitude) * magnitude)

    def x_scale(date_value: date) -> float:
        if len(series) == 1:
            return left + plot_width / 2
        return left + ((date_value - start_date).days / span_days) * plot_width

    def y_scale(value: int) -> float:
        return top + plot_height - (value / y_ceiling) * plot_height

    points = [(x_scale(date_value), y_scale(value)) for date_value, value in series]
    line_path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
    area_path = (
        f"M {points[0][0]:.2f} {top + plot_height:.2f} "
        + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
        + f" L {points[-1][0]:.2f} {top + plot_height:.2f} Z"
    )

    y_ticks: List[int] = []
    for idx in range(5):
        tick = int(round((y_ceiling / 4) * idx))
        if tick not in y_ticks:
            y_ticks.append(tick)

    mid_date = start_date + timedelta(days=span_days // 2)
    x_labels = [
        (start_date, start_date.strftime("%Y-%m")),
        (mid_date, mid_date.strftime("%Y-%m")),
        (end_date, end_date.strftime("%Y-%m")),
    ]

    grid_lines: List[str] = []
    for tick in y_ticks:
        y = y_scale(tick)
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" '
            'stroke="#dbe3ea" stroke-width="1" />'
        )
        grid_lines.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" '
            'font-size="12" fill="#6b7280" font-family="Segoe UI, Arial, sans-serif">'
            f"{tick}</text>"
        )

    x_axis_labels: List[str] = []
    seen_x: List[str] = []
    for label_date, label_text in x_labels:
        x = f"{x_scale(label_date):.2f}"
        if x in seen_x:
            continue
        seen_x.append(x)
        x_axis_labels.append(
            f'<text x="{x}" y="{top + plot_height + 28:.2f}" text-anchor="middle" '
            'font-size="12" fill="#6b7280" font-family="Segoe UI, Arial, sans-serif">'
            f"{escape(label_text)}</text>"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Total Stars History</title>
  <desc id="desc">Cumulative stars across all public non-fork repositories.</desc>
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f8fbff" />
      <stop offset="100%" stop-color="#eef4f8" />
    </linearGradient>
    <linearGradient id="area" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#1f6feb" stop-opacity="0.24" />
      <stop offset="100%" stop-color="#1f6feb" stop-opacity="0.02" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="20" fill="url(#bg)" />
  <text x="{left}" y="38" font-size="22" font-weight="700" fill="#111827" font-family="Segoe UI, Arial, sans-serif">Total Stars History</text>
  <text x="{left}" y="58" font-size="13" fill="#4b5563" font-family="Segoe UI, Arial, sans-serif">{escape(subtitle)}</text>
  <text x="{width - right}" y="42" text-anchor="end" font-size="34" font-weight="700" fill="#111827" font-family="Segoe UI, Arial, sans-serif">{total_stars}</text>
  <text x="{width - right}" y="60" text-anchor="end" font-size="13" fill="#4b5563" font-family="Segoe UI, Arial, sans-serif">{repo_count} repos combined</text>
  {''.join(grid_lines)}
  <line x1="{left}" y1="{top + plot_height:.2f}" x2="{left + plot_width}" y2="{top + plot_height:.2f}" stroke="#9aa4b2" stroke-width="1.2" />
  <path d="{area_path}" fill="url(#area)" />
  <path d="{line_path}" fill="none" stroke="#1f6feb" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{points[-1][0]:.2f}" cy="{points[-1][1]:.2f}" r="6" fill="#1f6feb" />
  <circle cx="{points[-1][0]:.2f}" cy="{points[-1][1]:.2f}" r="11" fill="#1f6feb" opacity="0.12" />
  {''.join(x_axis_labels)}
</svg>
"""


def _build_total_stars_history_block() -> str:
    return "\n".join(
        [
            "<!-- TOTAL-STARS-HISTORY:START -->",
            "## Total Stars History",
            "",
            '<p align="center">',
            '  <img src="./assets/total-stars-history.svg" alt="Total Stars History for all repositories" width="100%" />',
            "</p>",
            "<!-- TOTAL-STARS-HISTORY:END -->",
        ]
    )


def _replace_total_stars_history_block(readme: str, new_block: str) -> str:
    """替换顶部总星数历史图区域；兼容旧的单仓库 Star History 段落。"""
    marker_pattern = re.compile(
        r"(<!--\s*TOTAL-STARS-HISTORY:START\s*-->)([\s\S]*?)(<!--\s*TOTAL-STARS-HISTORY:END\s*-->)",
        re.MULTILINE,
    )
    if marker_pattern.search(readme):
        return re.sub(marker_pattern, new_block, readme, count=1).rstrip() + "\n"

    legacy_pattern = re.compile(
        r"^##\s*Star History[\s\S]*?(?=^---|^## |\Z)",
        re.MULTILINE,
    )
    if legacy_pattern.search(readme):
        return re.sub(legacy_pattern, new_block + "\n\n", readme, count=1)

    return readme.rstrip() + "\n\n" + new_block + "\n"


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


def _build_achievements_block(followers: int, stars: int) -> str:
    """构造 成就 & 活动 模块，使用硬编码的数值（避免 Shield 缓存问题）。"""
    # 构造带数值的 static badge URL
    # format: label=Followers&message=<count>&color=lightgrey&style=social&logo=github
    followers_url = f"https://img.shields.io/static/v1?label=Followers&message={followers}&color=lightgrey&style=social&logo=github"
    stars_url = f"https://img.shields.io/static/v1?label=Stars&message={stars}&color=lightgrey&style=social&logo=github"
    # Profile Views 只能动态，komarev 不支持 static
    views_url = "https://komarev.com/ghpvc/?username=ZSPSTRIVE&color=brightgreen"

    lines = [
        "## 成就 & 活动",
        "",
        f"![Followers]({followers_url})",
        f"![Stars]({stars_url})",
        f"![Profile Views]({views_url})",
    ]
    return "\n".join(lines)


def _replace_achievements_block(readme: str, new_block: str) -> str:
    """
    替换 '## 成就 & 活动' 区域。
    匹配规则：从 '## 成就 & 活动' 开始，直到下一个 '---' 或 '## ' 或文件结束。
    """
    # 这里的正则要小心，确保只匹配到下一个分隔符
    # (?=...) 是 lookahead assertion
    pattern = re.compile(
        r"^## 成就 & 活动[\s\S]*?(?=^---|^## |\Z)",
        re.MULTILINE
    )

    if pattern.search(readme):
        return re.sub(pattern, new_block + "\n\n", readme, count=1)
    
    # 未找到则追加
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

total_stars = sum(r.stargazers_count for r in repos)
followers = user.followers

try:
    total_stars_series = _build_total_stars_series(repos, total_stars)
    total_stars_subtitle = "Cumulative stars across all public non-fork repositories"
except Exception as exc:
    print(f"⚠️ 总星数历史图生成失败，回退为当前总数展示: {exc}")
    total_stars_series = [(datetime.now(TZ_CN).date(), total_stars)]
    total_stars_subtitle = "Current total stars; full history will refresh on the next successful workflow run"

star_history_svg = _build_total_stars_history_svg(
    total_stars_series,
    total_stars,
    len(repos),
    total_stars_subtitle,
)
asset_path = Path(STAR_HISTORY_ASSET_PATH)
asset_path.parent.mkdir(parents=True, exist_ok=True)
asset_path.write_text(star_history_svg, encoding="utf-8")

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
updated = _replace_total_stars_history_block(updated, _build_total_stars_history_block())

# ===============================
# 5. 生成并替换 成就 & 活动 模块
# ===============================
print(f"统计数据: Followers={followers}, Total Stars={total_stars}")

achievements_block = _build_achievements_block(followers, total_stars)
updated = _replace_achievements_block(updated, achievements_block)

with open(README_PATH, "w", encoding="utf-8") as f:
    f.write(updated)

print("✅ README 已成功更新：项目列表块已刷新，成就模块已更新（Followers/Stars）")
