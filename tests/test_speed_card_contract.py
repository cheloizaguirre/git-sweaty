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
    "computeSpeedSeries",
    "formatSpeedValue",
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
class SpeedSeriesTests(unittest.TestCase):
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
            "computeSpeedSeries(payload.aggregates, payload.types, payload.years)",
            {"aggregates": aggregates, "types": types, "years": years},
        )

    @staticmethod
    def _entry(count=1, distance=10000.0, moving_time=1800.0):
        return {
            "count": count,
            "distance": distance,
            "moving_time": moving_time,
            "elevation_gain": 10.0,
            "activity_ids": [],
        }

    def test_speed_is_distance_over_moving_time_per_month(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-03-01": self._entry(distance=10000.0, moving_time=1000.0),
                    "2026-03-20": self._entry(distance=20000.0, moving_time=2000.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026])
        self.assertEqual(len(result), 1)
        point = result[0]
        self.assertEqual((point["year"], point["monthIndex"]), (2026, 2))
        self.assertAlmostEqual(point["speed"], 30000.0 / 3000.0)

    def test_merges_types_and_month_keys_are_continuous(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-11-01": self._entry()}},
            "2026": {
                "Ride": {"2026-01-05": self._entry(distance=10000.0, moving_time=1000.0)},
                "VirtualRide": {"2026-01-06": self._entry(distance=10000.0, moving_time=3000.0)},
            },
        }
        result = self._run_series(aggregates, ["Ride", "VirtualRide"], [2025, 2026])
        self.assertEqual(
            [(p["year"], p["monthIndex"]) for p in result], [(2025, 10), (2026, 0)]
        )
        # Nov 2025 -> Jan 2026 is a 2-month step on the continuous index.
        self.assertEqual(result[1]["monthKey"] - result[0]["monthKey"], 2)
        self.assertAlmostEqual(result[1]["speed"], 20000.0 / 4000.0)

    def test_months_without_moving_time_or_distance_are_excluded(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(moving_time=0.0),
                    "2026-02-01": self._entry(distance=0.0),
                    "2026-03-01": self._entry(count=0),
                    "2026-04-01": self._entry(),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026])
        self.assertEqual([p["monthIndex"] for p in result], [3])

    def test_year_filter(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-01": self._entry()}},
            "2026": {"Ride": {"2026-06-01": self._entry()}},
        }
        result = self._run_series(aggregates, ["Ride"], [2025])
        self.assertEqual([p["year"] for p in result], [2025])

    def test_empty_selection_returns_empty_list(self) -> None:
        self.assertEqual(self._run_series({}, ["Ride"], [2026]), [])

    def test_format_uses_unit_system(self) -> None:
        # 5 m/s = 18.0 km/h = 11.2 mph.
        metric = self._run(
            "formatSpeedValue(payload.speed, payload.units)",
            {"speed": 5.0, "units": {"distance": "km", "elevation": "m"}},
        )
        imperial = self._run(
            "formatSpeedValue(payload.speed, payload.units)",
            {"speed": 5.0, "units": {"distance": "mi", "elevation": "ft"}},
        )
        self.assertEqual(metric, "18.0 km/h")
        self.assertEqual(imperial, "11.2 mph")


class SpeedLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_speed_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":speed`"), 2)
        self.assertEqual(self.app_js.count('"Average Speed",'), 2)

    def test_speed_pairs_with_hilliness(self) -> None:
        self.assertEqual(
            self.app_js.count('ratioPairRow.className = "labeled-card-row-pair";'), 2
        )

    def test_speed_card_is_stateless(self) -> None:
        self.assertNotIn("selectedSpeed", self.app_js)
        self.assertNotIn("isDefaultSpeedState", self.app_js)
        build = self.app_js.split("function buildSpeedCard", 1)[1]
        build = build.split("\nfunction buildSeasonalityCard", 1)[0]
        self.assertNotIn("trends-chip", build)
        self.assertNotIn("onStateChange", build)

    def test_pair_of_ratio_charts_fits_content_rail(self) -> None:
        # Both svgs (hilliness + speed) plus ~66px chrome each and the pair
        # gap must fit the 1250px rail.
        widths = []
        for name in ("HILLINESS_CHART_LAYOUT", "SPEED_CHART_LAYOUT"):
            layout = re.search(
                rf"const {name} = Object\.freeze\(\{{[\s\S]*?\}}\);", self.app_js
            ).group(0)
            values = {
                key: int(value)
                for key, value in re.findall(r"(\w+): (\d+)", layout)
            }
            widths.append(values["left"] + values["innerWidth"] + values["right"])
        self.assertLessEqual(widths[0] + 66 + widths[1] + 66 + 14, 1250)

    def test_speed_styles_present(self) -> None:
        for selector in (
            ".speed-card",
            ".speed-chart-area",
            ".speed-line",
            ".labeled-card-row-speed > .card",
        ):
            self.assertIn(selector, self.index_html)


if __name__ == "__main__":
    unittest.main()
