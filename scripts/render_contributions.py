#!/usr/bin/env python3
"""Render GitHub's contribution calendar as dependency-free, accessible SVGs."""

import argparse
import datetime as dt
import html
import json
import math
from pathlib import Path
import re
import sys


PALETTES = {
    "light": {
        "background": "#f7faf9", "border": "#dce9e3", "text": "#173b30",
        "muted": "#668176", "empty": "#e2ece6", "empty_side": "#cbdcd1",
        "low": "#a6dfc5", "high": "#20ab7c", "ground": "#eaf2ed",
    },
    "dark": {
        "background": "#0d1916", "border": "#284138", "text": "#e3f4ea",
        "muted": "#8ca99a", "empty": "#21392e", "empty_side": "#172b23",
        "low": "#32785a", "high": "#69e5ac", "ground": "#14261e",
    },
}


def parse_calendar(payload):
    """Validate dates and totals; never fill absent dates with invented zeros."""
    if payload.get("errors"):
        raise ValueError("GitHub returned GraphQL errors; refusing incomplete data")
    try:
        calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        total = calendar["totalContributions"]
        weeks = calendar["weeks"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Missing GitHub contributionCalendar") from exc
    if type(total) is not int or total < 0 or not isinstance(weeks, list):
        raise ValueError("Calendar total must be a nonnegative integer and weeks a list")
    days = []
    for week in weeks:
        if not isinstance(week, dict) or not isinstance(week.get("contributionDays"), list):
            raise ValueError("Every week must contain contributionDays")
        for day in week["contributionDays"]:
            if not isinstance(day, dict):
                raise ValueError("Invalid contribution day")
            raw_date, count = day.get("date"), day.get("contributionCount")
            if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
                raise ValueError("Every contribution day requires an ISO date (YYYY-MM-DD)")
            try:
                date = dt.date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValueError(f"Invalid contribution date: {raw_date}") from exc
            if type(count) is not int or count < 0:
                raise ValueError(f"Invalid contributionCount for {raw_date}")
            days.append((date, count))
    days.sort()
    for previous, current in zip(days, days[1:]):
        if (current[0] - previous[0]).days != 1:
            raise ValueError(f"Missing or duplicate contribution date between {previous[0]} and {current[0]}")
    if sum(count for _, count in days) != total:
        raise ValueError("totalContributions does not match the supplied daily counts")
    if days and (days[-1][0] - days[0][0]).days > 370:
        raise ValueError("Expected at most one year of contribution dates")
    return days, total


def blend(first, second, amount):
    a = tuple(int(first[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(second[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def points(vertices):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in vertices)


def render_svg(days, total, login, theme):
    p = PALETTES[theme]
    active = sum(count > 0 for _, count in days)
    maximum = max((count for _, count in days), default=0)
    date_range = f"{days[0][0].isoformat()} — {days[-1][0].isoformat()}" if days else "No contribution dates in input"
    title = f"{login}'s GitHub contributions"
    description = (
        f"{total:,} contributions across {active} active days. {date_range}. "
        "Each column is one day; column height uses a logarithmic scale. "
        "These are GitHub contributions, not only commits."
    )
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="430" viewBox="0 0 1000 430" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(title)}</title>',
        f'<desc id="desc">{html.escape(description)}</desc>',
        f'<rect x="0.5" y="0.5" width="999" height="429" rx="18" fill="{p["background"]}" stroke="{p["border"]}"/>',
        '<g font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">',
        f'<text x="32" y="38" fill="{p["text"]}" font-size="20" font-weight="650">GitHub contributions</text>',
        f'<text x="32" y="63" fill="{p["muted"]}" font-size="12">{html.escape(login)} · {date_range}</text>',
        f'<text x="968" y="38" fill="{p["text"]}" font-size="20" font-weight="650" text-anchor="end">{total:,} contributions</text>',
        f'<text x="968" y="63" fill="{p["muted"]}" font-size="12" text-anchor="end">{active} active days</text>',
    ]
    if days:
        sunday = days[0][0] - dt.timedelta(days=(days[0][0].weekday() + 1) % 7)
        columns = max(53, (days[-1][0] - sunday).days // 7 + 1)
        wx, wy, dx, dy = 816 / columns, 2.45, -8.0, 6.2
        origin_x, origin_y = 117, 170
        # A subtle platform grounds the chart without making empty days look active.
        platform = [(origin_x - 5, origin_y - 6),
                    (origin_x + columns * wx + 5, origin_y + columns * wy - 6),
                    (origin_x + columns * wx + 7 * dx + 5, origin_y + columns * wy + 7 * dy + 6),
                    (origin_x + 7 * dx - 5, origin_y + 7 * dy + 6)]
        out.append(f'<polygon points="{points(platform)}" fill="{p["ground"]}"/>')
        bars = []
        months = []
        previous_month = None
        for date, count in days:
            week, weekday = divmod((date - sunday).days, 7)
            x, y = origin_x + week * wx + weekday * dx, origin_y + week * wy + weekday * dy
            ratio = math.log1p(count) / math.log1p(maximum) if count and maximum else 0
            height = 3 + 97 * ratio if count else 1.8
            color = blend(p["low"], p["high"], ratio) if count else p["empty"]
            a = (x, y)
            b = (x + wx * .88, y + wy * .88)
            c = (b[0] + dx * .86, b[1] + dy * .86)
            d = (x + dx * .86, y + dy * .86)
            top = [(vx, vy - height) for vx, vy in (a, b, c, d)]
            front = blend(color, p["background"], .22) if count else p["empty_side"]
            side = blend(color, "#061c13", .32) if count else p["empty_side"]
            label = f"{date.isoformat()}: {count:,} contribution{'s' if count != 1 else ''}"
            bar = [f'<g class="day" data-date="{date.isoformat()}" data-count="{count}"><title>{label}</title>',
                   f'<polygon points="{points([top[3], top[2], c, d])}" fill="{front}"/>',
                   f'<polygon points="{points([top[1], top[2], c, b])}" fill="{side}"/>',
                   f'<polygon points="{points(top)}" fill="{color}"/>', '</g>']
            bars.append((y, x, "".join(bar)))
            month_key = (date.year, date.month)
            if month_key != previous_month:
                months.append((week, date.strftime("%b")))
                previous_month = month_key
        out.extend(bar for _, _, bar in sorted(bars))
        # Label the near edge, avoiding duplicate labels for tiny partial end months.
        last_label_week = -10
        for week, name in months:
            if week - last_label_week < 3 or week > columns - 2:
                continue
            x = origin_x + week * wx + 7 * dx
            y = origin_y + week * wy + 7 * dy + 22
            out.append(f'<text x="{x:.2f}" y="{y:.2f}" fill="{p["muted"]}" font-size="11">{name}</text>')
            last_label_week = week
    else:
        out.append(f'<text x="500" y="226" fill="{p["muted"]}" font-size="16" text-anchor="middle">No contribution data to display</text>')
    out.append(f'<text x="32" y="402" fill="{p["muted"]}" font-size="11">Height uses log scale · {len(days)} days</text>')
    out.append(f'<text x="769" y="402" fill="{p["muted"]}" font-size="11" text-anchor="end">Less</text>')
    for index, ratio in enumerate((None, 0, .33, .67, 1)):
        color = p["empty"] if ratio is None else blend(p["low"], p["high"], ratio)
        out.append(f'<rect x="{779 + index * 22}" y="390" width="15" height="15" rx="3" fill="{color}"/>')
    out.append(f'<text x="895" y="402" fill="{p["muted"]}" font-size="11">More</text>')
    out.extend(['</g>', '</svg>'])
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="GitHub GraphQL response JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("assets"))
    parser.add_argument("--login", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        days, total = parse_calendar(payload)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(1, f"Contribution rendering failed: {exc}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for theme in PALETTES:
        destination = args.output_dir / f"contribution-3d-{theme}.svg"
        destination.write_text(render_svg(days, total, args.login, theme), encoding="utf-8")
        print(f"Rendered {destination}: {total} contributions, {len(days)} days")


if __name__ == "__main__":
    main()
