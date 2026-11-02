"""Contract tests for accurate, bounded contribution rendering."""

import datetime as dt
import importlib.util
import math
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_contributions.py"
SPEC = importlib.util.spec_from_file_location("contributions", SCRIPT)
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)
SVG = "{http://www.w3.org/2000/svg}"


def response(days, total=None):
    return {"data": {"user": {"contributionsCollection": {"contributionCalendar": {
        "totalContributions": sum(day["contributionCount"] for day in days) if total is None else total,
        "weeks": [{"contributionDays": days}],
    }}}}}


class ContributionRenderingTests(unittest.TestCase):
    def test_full_year_preserves_every_day_and_accurate_statistics(self):
        start = dt.date(2025, 11, 2)
        source = [{"date": (start + dt.timedelta(days=i)).isoformat(),
                   "contributionCount": 12 if i in (0, 100, 365) else 0}
                  for i in range(366)]
        days, total = renderer.parse_calendar(response(source))
        for theme in renderer.PALETTES:
            root = ET.fromstring(renderer.render_svg(days, total, "test-user", theme))
            bars = [node for node in root.iter(f"{SVG}g") if node.get("class") == "day"]
            self.assertEqual(len(bars), 366)
            self.assertEqual({bar.get("data-date") for bar in bars}, {day["date"] for day in source})
            self.assertEqual(sum(int(bar.get("data-count")) for bar in bars), 36)
            self.assertIn("36 contributions across 3 active days", root.find(f"{SVG}desc").text)
            self.assertIn("2025-11-02 — 2026-11-02", root.find(f"{SVG}desc").text)

    def test_empty_and_all_zero_calendars_do_not_invent_activity(self):
        for source in ([], [{"date": "2026-11-02", "contributionCount": 0}]):
            days, total = renderer.parse_calendar(response(source))
            root = ET.fromstring(renderer.render_svg(days, total, "empty", "light"))
            bars = [node for node in root.iter(f"{SVG}g") if node.get("class") == "day"]
            self.assertEqual(len(bars), len(source))
            self.assertIn("0 contributions across 0 active days", root.find(f"{SVG}desc").text)

    def test_missing_duplicate_and_invalid_dates_fail(self):
        for source in (
            [{"contributionCount": 1}],
            [{"date": "2026-02-30", "contributionCount": 1}],
            [{"date": "2026-11-01", "contributionCount": 1},
             {"date": "2026-11-03", "contributionCount": 1}],
            [{"date": "2026-11-01", "contributionCount": 1},
             {"date": "2026-11-01", "contributionCount": 1}],
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                renderer.parse_calendar(response(source))

    def test_incomplete_graphql_and_mismatched_totals_fail(self):
        for payload in ({"errors": [{"message": "permission denied"}]},
                        {"data": {"user": None}},
                        response([{"date": "2026-11-02", "contributionCount": 5}], total=6)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                renderer.parse_calendar(payload)

    def test_extreme_peak_stays_within_canvas_and_svg_is_self_contained(self):
        days, total = renderer.parse_calendar(response([
            {"date": "2026-11-01", "contributionCount": 1_000_000_000},
            {"date": "2026-11-02", "contributionCount": 1},
        ]))
        svg = renderer.render_svg(days, total, '<user & "name">', "dark")
        root = ET.fromstring(svg)
        self.assertEqual(root.find(f"{SVG}title").text, '<user & "name">\'s GitHub contributions')
        self.assertIn("Height uses log scale", svg)
        for polygon in root.iter(f"{SVG}polygon"):
            for pair in polygon.get("points").split():
                x, y = map(float, pair.split(","))
                self.assertTrue(math.isfinite(x) and math.isfinite(y))
                self.assertTrue(0 <= x <= 1000 and 0 <= y <= 430)
        self.assertNotIn("foreignObject", svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("href=", svg)


if __name__ == "__main__":
    unittest.main()
