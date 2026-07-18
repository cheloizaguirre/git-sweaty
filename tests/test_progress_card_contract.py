import json
import os
import re
import shutil
import subprocess
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_JS_PATH = os.path.join(ROOT_DIR, "site", "app.js")
INDEX_HTML_PATH = os.path.join(ROOT_DIR, "site", "index.html")

HELPER_FUNCTION_NAMES = [
    "progressDayOfYear",
    "progressMetricEntryValue",
    "buildCumulativeSeriesByYear",
    "cumulativeValueAtDay",
]


def _extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)\s*{{[\s\S]*?\n}}\n",
        source,
    )
    if not match:
        raise AssertionError(f"Could not find {name} in site/app.js")
    return match.group(0)


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class ProgressSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        preamble = "const MS_PER_DAY = 1000 * 60 * 60 * 24;\n"
        cls.series_source = preamble + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_series(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        metric_key: str,
    ) -> list[dict]:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.series_source}\n"
            "const result = buildCumulativeSeriesByYear(\n"
            "  payload.aggregates, payload.types, payload.years, payload.metricKey,\n"
            ");\n"
            "process.stdout.write(JSON.stringify({ result }));\n"
        )
        completed = subprocess.run(
            [
                "node",
                "-e",
                script,
                json.dumps(
                    {
                        "aggregates": aggregates,
                        "types": types,
                        "years": years,
                        "metricKey": metric_key,
                    }
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)["result"]

    def _run_value_at_day(self, points: list[dict], day: int) -> float:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.series_source}\n"
            "const result = cumulativeValueAtDay(payload.points, payload.day);\n"
            "process.stdout.write(JSON.stringify({ result }));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script, json.dumps({"points": points, "day": day})],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(json.loads(completed.stdout)["result"])

    @staticmethod
    def _entry(count=1, distance=1000.0, moving_time=600.0, elevation_gain=10.0):
        return {
            "count": count,
            "distance": distance,
            "moving_time": moving_time,
            "elevation_gain": elevation_gain,
            "activity_ids": [],
        }

    def test_cumulative_series_accumulates_in_date_order(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(distance=1000.0),
                    "2026-03-01": self._entry(distance=2000.0),
                    "2026-02-01": self._entry(distance=500.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026], "distance")
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["year"], 2026)
        self.assertAlmostEqual(entry["total"], 3500.0)
        self.assertEqual(entry["points"][0], {"day": 0, "value": 0})
        days = [point["day"] for point in entry["points"][1:]]
        self.assertEqual(days, [1, 32, 60])
        values = [point["value"] for point in entry["points"][1:]]
        self.assertEqual(values, [1000.0, 1500.0, 3500.0])

    def test_day_of_year_handles_leap_years(self) -> None:
        aggregates = {
            "2024": {"Ride": {"2024-12-31": self._entry(distance=100.0)}},
            "2025": {"Ride": {"2025-12-31": self._entry(distance=100.0)}},
        }
        result = self._run_series(aggregates, ["Ride"], [2024, 2025], "distance")
        by_year = {entry["year"]: entry for entry in result}
        self.assertEqual(by_year[2024]["points"][-1]["day"], 366)
        self.assertEqual(by_year[2025]["points"][-1]["day"], 365)

    def test_series_merges_types_and_filters_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-01": self._entry(distance=999.0)}},
            "2026": {
                "Ride": {"2026-06-01": self._entry(distance=1000.0)},
                "VirtualRide": {"2026-06-01": self._entry(distance=2000.0)},
            },
        }
        result = self._run_series(aggregates, ["Ride", "VirtualRide"], [2026], "distance")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["total"], 3000.0)

    def test_count_metric_uses_activity_counts(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-05": self._entry(count=2),
                    "2026-01-06": self._entry(count=1),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026], "count")
        self.assertEqual(result[0]["total"], 3)

    def test_cumulative_value_at_day_returns_last_value_on_or_before(self) -> None:
        points = [
            {"day": 0, "value": 0},
            {"day": 10, "value": 5.0},
            {"day": 20, "value": 9.0},
        ]
        self.assertEqual(self._run_value_at_day(points, 9), 0)
        self.assertEqual(self._run_value_at_day(points, 10), 5.0)
        self.assertEqual(self._run_value_at_day(points, 15), 5.0)
        self.assertEqual(self._run_value_at_day(points, 400), 9.0)


class ProgressLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_progress_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":progress`"), 2)
        self.assertEqual(self.app_js.count('"Cumulative Progress",'), 2)

    def test_trends_and_progress_share_a_pair_row(self) -> None:
        # Both render branches wrap the Trends and Cumulative Progress rows in
        # a shared side-by-side pair container.
        self.assertEqual(
            self.app_js.count('pairRow.className = "labeled-card-row-pair";'), 2
        )
        self.assertIn(".labeled-card-row-pair", self.index_html)

    def test_progress_defaults(self) -> None:
        self.assertIn('const PROGRESS_DEFAULT_METRIC_KEY = "distance";', self.app_js)

    def test_progress_chart_width_keeps_pair_within_rail(self) -> None:
        # left + innerWidth + right must stay small enough that the weekly
        # Trends view (~640px card) + the Cumulative Progress card (svg +
        # ~66px card chrome) + the pair gap fit the 1250px content rail.
        layout = re.search(
            r"const PROGRESS_CHART_LAYOUT = Object\.freeze\(\{[\s\S]*?\}\);",
            self.app_js,
        ).group(0)
        values = {
            key: int(value)
            for key, value in re.findall(r"(\w+): (\d+)", layout)
        }
        svg_width = values["left"] + values["innerWidth"] + values["right"]
        self.assertLessEqual(svg_width, 520)

    def test_rail_width_covers_side_by_side_pair(self) -> None:
        self.assertIn("1250px", self.index_html)

    def test_progress_state_participates_in_reset_all(self) -> None:
        reset_handler = self.app_js.split("resetAllButton.addEventListener", 1)[1]
        reset_handler = reset_handler.split("update({", 1)[0]
        self.assertIn(
            "selectedProgressMetricKey = PROGRESS_DEFAULT_METRIC_KEY;", reset_handler
        )
        self.assertIn("isDefaultProgressState()", self.app_js)

    def test_progress_styles_present(self) -> None:
        for selector in (
            ".progress-card",
            ".progress-chart-area",
            ".progress-line",
            ".progress-hover-strip",
            ".progress-legend-item",
        ):
            self.assertIn(selector, self.index_html)

    def test_progress_chips_reuse_metric_chip_styling(self) -> None:
        self.assertIn("progress-metric-chips", self.app_js)


if __name__ == "__main__":
    unittest.main()
