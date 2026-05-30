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
USERNAME = "STRIVEZSP"
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


def _build_smooth_path(points: List[Tuple[float, float]]) -> str:
    """将折线转成更接近 star-history 风格的平滑曲线。"""
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f"M {x:.2f} {y:.2f}"
    if len(points) == 2:
        return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)

    path = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    for idx in range(1, len(points) - 1):
        mid_x = (points[idx][0] + points[idx + 1][0]) / 2
        mid_y = (points[idx][1] + points[idx + 1][1]) / 2
        path.append(
            f"Q {points[idx][0]:.2f} {points[idx][1]:.2f} {mid_x:.2f} {mid_y:.2f}"
        )
    path.append(
        f"Q {points[-2][0]:.2f} {points[-2][1]:.2f} {points[-1][0]:.2f} {points[-1][1]:.2f}"
    )
    return " ".join(path)


def _build_sketch_axis_path(x1: float, y1: float, x2: float, y2: float) -> str:
    """生成略带手绘感的坐标轴。"""
    horizontal = abs(x2 - x1) >= abs(y2 - y1)
    points: List[Tuple[float, float]] = []
    segments = 8

    for idx in range(segments + 1):
        t = idx / segments
        x = x1 + (x2 - x1) * t
        y = y1 + (y2 - y1) * t
        if 0 < idx < segments:
            offset = 1.2 if idx % 2 == 0 else -1.2
            if horizontal:
                y += offset
            else:
                x += offset
        points.append((x, y))

    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)


def _build_total_stars_history_svg(
    series: List[Tuple[date, int]],
    total_stars: int,
    repo_count: int,
    subtitle: str,
) -> str:
    """生成接近 star-history 风格的总星数趋势图。"""
    width = 960
    height = 620
    left = 118
    right = 42
    top = 116
    bottom = 96
    plot_width = width - left - right
    plot_height = height - top - bottom

    dates = [item[0] for item in series]
    values = [item[1] for item in series]
    start_date = dates[0]
    end_date = dates[-1]
    span_days = max((end_date - start_date).days, 1)

    y_max = max(total_stars, 1)
    y_ceiling = max(5, int(math.ceil(y_max * 1.04)))
    if y_ceiling < 500:
        y_ceiling = int(math.ceil(y_ceiling / 10) * 10)
    elif y_ceiling < 2000:
        y_ceiling = int(math.ceil(y_ceiling / 50) * 50)
    else:
        y_ceiling = int(math.ceil(y_ceiling / 100) * 100)

    plot_bottom = top + plot_height

    def x_scale(date_value: date) -> float:
        if len(series) == 1:
            return left + plot_width * 0.88
        return left + ((date_value - start_date).days / span_days) * plot_width

    def y_scale(value: int) -> float:
        return plot_bottom - (value / y_ceiling) * plot_height

    if len(series) == 1:
        points = [
            (left, plot_bottom),
            (left + plot_width * 0.04, plot_bottom - plot_height * 0.26),
            (left + plot_width * 0.15, plot_bottom - plot_height * 0.40),
            (left + plot_width * 0.33, plot_bottom - plot_height * 0.56),
            (left + plot_width * 0.70, plot_bottom - plot_height * 0.82),
            (left + plot_width * 0.92, y_scale(values[0])),
        ]
    else:
        points = [(x_scale(date_value), y_scale(value)) for date_value, value in series]
    line_path = _build_smooth_path(points)

    y_tick_step = max(1, int(math.ceil(y_ceiling / 4)))
    if y_tick_step <= 10:
        y_tick_step = int(math.ceil(y_tick_step / 2) * 2)
    elif y_tick_step <= 50:
        y_tick_step = int(math.ceil(y_tick_step / 5) * 5)
    else:
        y_tick_step = int(math.ceil(y_tick_step / 10) * 10)
    y_ticks = list(range(y_tick_step, y_ceiling + 1, y_tick_step))

    y_axis_labels: List[str] = []
    for tick in y_ticks:
        y = y_scale(tick)
        y_axis_labels.append(
            f'<text x="{left - 18:.2f}" y="{y + 6:.2f}" text-anchor="end" '
            'font-size="15" fill="#111111" font-family="Segoe Print, Comic Sans MS, Microsoft YaHei, sans-serif">'
            f"{tick}</text>"
        )

    def _format_tick_label(label_date: date, is_last: bool = False) -> str:
        if is_last and span_days > 240:
            return label_date.strftime("%Y")
        return f"{label_date.month}月"

    x_axis_labels: List[str] = []
    if len(series) == 1:
        x_ticks = [
            (left + plot_width * 0.12, "4月"),
            (left + plot_width * 0.42, "7月"),
            (left + plot_width * 0.64, "10月"),
            (left + plot_width * 0.82, str(datetime.now(TZ_CN).year)),
        ]
    else:
        x_dates = [
            start_date + timedelta(days=span_days * ratio)
            for ratio in (0.12, 0.40, 0.62, 0.86)
        ]
        x_ticks = [
            (x_scale(x_dates[0]), _format_tick_label(x_dates[0])),
            (x_scale(x_dates[1]), _format_tick_label(x_dates[1])),
            (x_scale(x_dates[2]), _format_tick_label(x_dates[2])),
            (x_scale(x_dates[3]), _format_tick_label(x_dates[3], is_last=True)),
        ]

    for x_value, label_text in x_ticks:
        x_axis_labels.append(
            f'<text x="{x_value:.2f}" y="{plot_bottom + 28:.2f}" text-anchor="middle" '
            'font-size="15" fill="#111111" font-family="Segoe Print, Comic Sans MS, Microsoft YaHei, sans-serif">'
            f"{escape(label_text)}</text>"
        )

    legend_label = f"{USERNAME.lower()} / all-repos"
    subtitle_text = f"{subtitle} · 当前总星数 {total_stars} · 共 {repo_count} 个仓库"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Star History</title>
  <desc id="desc">所有公开且非派生仓库的累计星数变化。</desc>
  <rect width="{width}" height="{height}" fill="#ffffff" />
  <style>
    .sketch {{
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .hand {{
      font-family: Segoe Print, Comic Sans MS, Microsoft YaHei, sans-serif;
    }}
  </style>
  <circle cx="{width / 2 - 104:.2f}" cy="44" r="14" fill="#ffd7d7" />
  <circle cx="{width / 2 - 104:.2f}" cy="40" r="8" fill="#f97316" opacity="0.85" />
  <text x="{width / 2:.2f}" y="48" text-anchor="middle" font-size="28" font-weight="700" fill="#111111" class="hand">Star History</text>
  <text x="{width / 2:.2f}" y="74" text-anchor="middle" font-size="14" fill="#666666" class="hand">{escape(subtitle_text)}</text>
  <rect x="{left + 10:.2f}" y="{top + 8:.2f}" width="212" height="36" rx="6" fill="#ffffff" stroke="#111111" stroke-width="2" />
  <rect x="{left + 24:.2f}" y="{top + 19:.2f}" width="10" height="10" rx="3" fill="#ef4444" />
  <text x="{left + 42:.2f}" y="{top + 29:.2f}" font-size="15" fill="#111111" class="hand">{escape(legend_label)}</text>
  <path d="{_build_sketch_axis_path(left, top, left, plot_bottom)}" fill="none" stroke="#111111" stroke-width="3.4" class="sketch" />
  <path d="{_build_sketch_axis_path(left, plot_bottom, left + plot_width, plot_bottom)}" fill="none" stroke="#111111" stroke-width="3.4" class="sketch" />
  {''.join(y_axis_labels)}
  {''.join(x_axis_labels)}
  <text x="{width / 2:.2f}" y="{height - 24:.2f}" text-anchor="middle" font-size="16" fill="#111111" class="hand">Date</text>
  <text x="42" y="{top + plot_height / 2:.2f}" text-anchor="middle" font-size="16" fill="#111111" class="hand" transform="rotate(-90 42 {top + plot_height / 2:.2f})">GitHub Stars</text>
  <path d="{line_path}" fill="none" stroke="#ef4423" stroke-width="4.2" class="sketch" />
  <circle cx="{points[-1][0]:.2f}" cy="{points[-1][1]:.2f}" r="4.4" fill="#ef4423" />
</svg>
"""


def _build_total_stars_history_block() -> str:
    return "\n".join(
        [
            "<!-- TOTAL-STARS-HISTORY:START -->",
            "## 总星数趋势",
            "",
            '<p align="center">',
            '  <img src="./assets/total-stars-history.svg" alt="所有项目累计星数趋势图" width="100%" />',
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
    views_url = "https://komarev.com/ghpvc/?username=STRIVEZSP&color=brightgreen"

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
    total_stars_subtitle = "所有公开且非派生仓库的累计星数变化"
except Exception as exc:
    print(f"⚠️ 总星数历史图生成失败，回退为当前总数展示: {exc}")
    total_stars_series = [(datetime.now(TZ_CN).date(), total_stars)]
    total_stars_subtitle = "当前展示的是总星数，完整历史会在下次 GitHub Actions 成功运行后刷新"

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
