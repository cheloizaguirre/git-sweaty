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
    "progressMetricEntryValue",
    "computeSeasonalityProfile",
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
class SeasonalityProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        cls.profile_source = "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_profile(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        metric_key: str,
    ) -> list[dict]:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.profile_source}\n"
            "const result = computeSeasonalityProfile(\n"
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

    @staticmethod
    def _entry(count=1, distance=1000.0):
        return {
            "count": count,
            "distance": distance,
            "moving_time": 600.0,
            "elevation_gain": 10.0,
            "activity_ids": [],
        }

    def test_average_is_over_active_years_only(self) -> None:
        aggregates = {
            "2024": {"Ride": {"2024-06-10": self._entry(distance=1000.0)}},
            "2025": {"Ride": {"2025-06-05": self._entry(distance=3000.0)}},
            # 2026 has no June activity: must not drag the average down.
            "2026": {"Ride": {"2026-01-01": self._entry(distance=500.0)}},
        }
        result = self._run_profile(
            aggregates, ["Ride"], [2024, 2025, 2026], "distance"
        )
        june = result[5]
        self.assertEqual(june["activeYearCount"], 2)
        self.assertAlmostEqual(june["average"], 2000.0)
        self.assertAlmostEqual(june["total"], 4000.0)

    def test_month_instance_sums_days_and_types(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-03-01": self._entry(distance=1000.0),
                    "2026-03-15": self._entry(distance=2000.0),
                },
                "VirtualRide": {"2026-03-02": self._entry(distance=4000.0)},
            },
        }
        result = self._run_profile(
            aggregates, ["Ride", "VirtualRide"], [2026], "distance"
        )
        march = result[2]
        self.assertEqual(march["activeYearCount"], 1)
        self.assertAlmostEqual(march["average"], 7000.0)

    def test_per_year_breakdown_sorted_newest_first(self) -> None:
        aggregates = {
            "2024": {"Ride": {"2024-05-01": self._entry(distance=100.0)}},
            "2026": {"Ride": {"2026-05-01": self._entry(distance=300.0)}},
        }
        result = self._run_profile(aggregates, ["Ride"], [2024, 2026], "distance")
        may = result[4]
        self.assertEqual([entry["year"] for entry in may["perYear"]], [2026, 2024])

    def test_zero_count_months_are_not_active(self) -> None:
        aggregates = {
            "2026": {"Ride": {"2026-04-01": self._entry(count=0, distance=0.0)}},
        }
        result = self._run_profile(aggregates, ["Ride"], [2026], "distance")
        april = result[3]
        self.assertEqual(april["activeYearCount"], 0)
        self.assertEqual(april["average"], 0)

    def test_year_filter_excludes_other_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-07-01": self._entry(distance=999.0)}},
            "2026": {"Ride": {"2026-07-01": self._entry(distance=1000.0)}},
        }
        result = self._run_profile(aggregates, ["Ride"], [2026], "distance")
        july = result[6]
        self.assertEqual(july["activeYearCount"], 1)
        self.assertAlmostEqual(july["average"], 1000.0)

    def test_returns_twelve_months(self) -> None:
        result = self._run_profile({}, ["Ride"], [2026], "distance")
        self.assertEqual(len(result), 12)
        self.assertEqual([month["monthIndex"] for month in result], list(range(12)))


class SeasonalityLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_seasonality_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":seasonality`"), 2)
        self.assertEqual(self.app_js.count('"Seasonality",'), 2)

    def test_seasonality_pairs_with_streaks(self) -> None:
        self.assertEqual(
            self.app_js.count('statsPairRow.className = "labeled-card-row-pair";'), 2
        )

    def test_seasonality_defaults(self) -> None:
        self.assertIn(
            'const SEASONALITY_DEFAULT_METRIC_KEY = "distance";', self.app_js
        )

    def test_seasonality_pair_fits_content_rail(self) -> None:
        # Seasonality svg (left + 12*barWidth + 11*barGap + right) plus card
        # chrome must leave room for the Streaks card inside the 1250px rail.
        layout = re.search(
            r"const SEASONALITY_CHART_LAYOUT = Object\.freeze\(\{[\s\S]*?\}\);",
            self.app_js,
        ).group(0)
        values = {
            key: int(value)
            for key, value in re.findall(r"(\w+): (\d+)", layout)
        }
        svg_width = (
            values["left"] + 12 * values["barWidth"] + 11 * values["barGap"]
            + values["right"]
        )
        self.assertLessEqual(svg_width, 620)

    def test_seasonality_state_participates_in_reset_all(self) -> None:
        reset_handler = self.app_js.split("resetAllButton.addEventListener", 1)[1]
        reset_handler = reset_handler.split("update({", 1)[0]
        self.assertIn(
            "selectedSeasonalityMetricKey = SEASONALITY_DEFAULT_METRIC_KEY;",
            reset_handler,
        )
        self.assertIn("isDefaultSeasonalityState()", self.app_js)

    def test_seasonality_styles_present(self) -> None:
        for selector in (
            ".seasonality-card",
            ".seasonality-chart-area",
            ".seasonality-bar",
            ".labeled-card-row-seasonality > .card",
        ):
            self.assertIn(selector, self.index_html)

    def test_seasonality_chips_reuse_metric_chip_styling(self) -> None:
        self.assertIn("seasonality-metric-chips", self.app_js)


if __name__ == "__main__":
    unittest.main()
