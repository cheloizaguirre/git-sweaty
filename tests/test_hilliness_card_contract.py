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
    "computeHillinessSeries",
    "formatHillinessValue",
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
class HillinessSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        cls.series_source = "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run(self, snippet: str, payload: dict):
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.series_source}\n"
            f"const result = {snippet};\n"
            "process.stdout.write(JSON.stringify({ result }));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script, json.dumps(payload)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)["result"]

    def _run_series(self, aggregates, types, years):
        return self._run(
            "computeHillinessSeries(payload.aggregates, payload.types, payload.years)",
            {"aggregates": aggregates, "types": types, "years": years},
        )

    @staticmethod
    def _entry(count=1, distance=1000.0, elevation_gain=10.0):
        return {
            "count": count,
            "distance": distance,
            "moving_time": 600.0,
            "elevation_gain": elevation_gain,
            "activity_ids": [],
        }

    def test_ratio_is_elevation_over_distance_per_month(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-03-01": self._entry(distance=10000.0, elevation_gain=100.0),
                    "2026-03-20": self._entry(distance=30000.0, elevation_gain=500.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026])
        self.assertEqual(len(result), 1)
        point = result[0]
        self.assertEqual(point["year"], 2026)
        self.assertEqual(point["monthIndex"], 2)
        self.assertAlmostEqual(point["ratio"], 600.0 / 40000.0)

    def test_merges_types_and_sorts_by_month_key(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-12-01": self._entry(distance=1000.0)}},
            "2026": {
                "Ride": {"2026-02-01": self._entry(distance=1000.0)},
                "VirtualRide": {"2026-02-02": self._entry(distance=1000.0)},
            },
        }
        result = self._run_series(aggregates, ["Ride", "VirtualRide"], [2025, 2026])
        self.assertEqual(
            [(p["year"], p["monthIndex"]) for p in result], [(2025, 11), (2026, 1)]
        )
        self.assertAlmostEqual(result[1]["distance"], 2000.0)
        # Month keys are continuous across the year boundary: Dec -> Feb gap of 2.
        self.assertEqual(result[1]["monthKey"] - result[0]["monthKey"], 2)

    def test_months_without_distance_are_excluded(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(distance=0.0, elevation_gain=0.0),
                    "2026-02-01": self._entry(count=0, distance=0.0),
                    "2026-03-01": self._entry(distance=5000.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026])
        self.assertEqual([p["monthIndex"] for p in result], [2])

    def test_year_filter(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-01": self._entry()}},
            "2026": {"Ride": {"2026-06-01": self._entry()}},
        }
        result = self._run_series(aggregates, ["Ride"], [2026])
        self.assertEqual([p["year"] for p in result], [2026])

    def test_empty_selection_returns_empty_list(self) -> None:
        self.assertEqual(self._run_series({}, ["Ride"], [2026]), [])

    def test_format_uses_unit_system(self) -> None:
        ratio = 0.01  # 10 m/km; 52.8 ft/mi
        metric = self._run(
            "formatHillinessValue(payload.ratio, payload.units)",
            {"ratio": ratio, "units": {"distance": "km", "elevation": "m"}},
        )
        imperial = self._run(
            "formatHillinessValue(payload.ratio, payload.units)",
            {"ratio": ratio, "units": {"distance": "mi", "elevation": "ft"}},
        )
        self.assertEqual(metric, "10 m/km")
        self.assertEqual(imperial, "53 ft/mi")


class HillinessLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_hilliness_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":hilliness`"), 2)
        self.assertEqual(self.app_js.count('"Hilliness",'), 2)

    def test_hilliness_card_is_stateless(self) -> None:
        self.assertNotIn("selectedHilliness", self.app_js)
        self.assertNotIn("isDefaultHillinessState", self.app_js)
        build = self.app_js.split("function buildHillinessCard", 1)[1]
        build = build.split("\nfunction buildSeasonalityCard", 1)[0]
        self.assertNotIn("trends-chip", build)
        self.assertNotIn("onStateChange", build)

    def test_hilliness_chart_width_allows_future_pairing(self) -> None:
        # Same cap as the progress card so the Average Speed trend can pair
        # beside it inside the 1250px rail.
        layout = re.search(
            r"const HILLINESS_CHART_LAYOUT = Object\.freeze\(\{[\s\S]*?\}\);",
            self.app_js,
        ).group(0)
        values = {
            key: int(value)
            for key, value in re.findall(r"(\w+): (\d+)", layout)
        }
        svg_width = values["left"] + values["innerWidth"] + values["right"]
        self.assertLessEqual(svg_width, 520)

    def test_hilliness_reuses_shared_progress_chart_styles(self) -> None:
        build = self.app_js.split("function buildHillinessCard", 1)[1]
        build = build.split("\nfunction buildSeasonalityCard", 1)[0]
        for class_name in (
            "progress-gridline",
            "progress-axis-label",
            "progress-hover-strip",
        ):
            self.assertIn(class_name, build)

    def test_hilliness_styles_present(self) -> None:
        for selector in (
            ".hilliness-card",
            ".hilliness-chart-area",
            ".hilliness-line",
            ".labeled-card-row-hilliness > .card",
        ):
            self.assertIn(selector, self.index_html)


if __name__ == "__main__":
    unittest.main()
