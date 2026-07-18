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
    "normalizeWeekStart",
    "weekdayRowFromStart",
    "weekStartOnOrBeforeLocal",
    "localDayNumber",
    "weekIndexFromSundayStart",
    "weekOfYear",
    "trendsPeriodForDate",
    "bucketAggregatesByPeriod",
    "trendsMetricValue",
    "computeDailyTotalsByDate",
    "computeRecords",
]

PREAMBLE = (
    'const WEEK_START_SUNDAY = "sunday";\n'
    'const WEEK_START_MONDAY = "monday";\n'
    "const MS_PER_DAY = 1000 * 60 * 60 * 24;\n"
    'const RECORDS_METRIC_ORDER = ["distance", "moving_time", "elevation_gain", "count"];\n'
)


def _extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)\s*{{[\s\S]*?\n}}\n",
        source,
    )
    if not match:
        raise AssertionError(f"Could not find {name} in site/app.js")
    return match.group(0)


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class RecordsComputationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        cls.records_source = PREAMBLE + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_records(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        week_start: str = "sunday",
    ) -> dict:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.records_source}\n"
            "const result = computeRecords(\n"
            "  payload.aggregates, payload.types, payload.years, payload.weekStart,\n"
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
                        "weekStart": week_start,
                    }
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)["result"]

    @staticmethod
    def _entry(count=1, distance=1000.0, moving_time=600.0, elevation_gain=10.0):
        return {
            "count": count,
            "distance": distance,
            "moving_time": moving_time,
            "elevation_gain": elevation_gain,
            "activity_ids": [],
        }

    def test_best_day_sums_types_and_picks_max(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-03-01": self._entry(distance=5000.0),
                    "2026-03-02": self._entry(distance=3000.0),
                },
                "VirtualRide": {
                    "2026-03-02": self._entry(distance=4000.0),
                },
            },
        }
        records = self._run_records(aggregates, ["Ride", "VirtualRide"], [2026])
        best_day = records["day"]["distance"]
        self.assertEqual(best_day["dateKey"], "2026-03-02")
        self.assertAlmostEqual(best_day["value"], 7000.0)
        self.assertEqual(records["day"]["count"]["dateKey"], "2026-03-02")
        self.assertEqual(records["day"]["count"]["value"], 2)

    def test_best_week_respects_week_start(self) -> None:
        # 2026-07-12 is a Sunday, 2026-07-13 a Monday. With Sunday week start
        # they share a week (total 3); with Monday start they split (2 vs 1).
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-07-12": self._entry(distance=1000.0),
                    "2026-07-13": self._entry(distance=1000.0),
                    "2026-07-18": self._entry(distance=1000.0),
                },
            },
        }
        sunday = self._run_records(aggregates, ["Ride"], [2026], "sunday")
        self.assertAlmostEqual(sunday["week"]["distance"]["value"], 3000.0)
        monday = self._run_records(aggregates, ["Ride"], [2026], "monday")
        self.assertAlmostEqual(monday["week"]["distance"]["value"], 2000.0)

    def test_best_month_across_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-10": self._entry(elevation_gain=900.0)}},
            "2026": {
                "Ride": {
                    "2026-01-05": self._entry(elevation_gain=400.0),
                    "2026-01-20": self._entry(elevation_gain=450.0),
                },
            },
        }
        records = self._run_records(aggregates, ["Ride"], [2025, 2026])
        best_month = records["month"]["elevation_gain"]
        self.assertEqual(best_month["year"], 2025)
        self.assertEqual(best_month["index"], 5)
        self.assertAlmostEqual(best_month["value"], 900.0)

    def test_ties_keep_earliest_period(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-02-01": self._entry(distance=5000.0),
                    "2026-04-01": self._entry(distance=5000.0),
                },
            },
        }
        records = self._run_records(aggregates, ["Ride"], [2026])
        self.assertEqual(records["day"]["distance"]["dateKey"], "2026-02-01")
        self.assertEqual(records["month"]["distance"]["index"], 1)

    def test_zero_metrics_produce_no_record(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {"2026-05-01": self._entry(distance=1000.0, elevation_gain=0.0)},
            },
        }
        records = self._run_records(aggregates, ["Ride"], [2026])
        self.assertNotIn("elevation_gain", records["day"])
        self.assertNotIn("elevation_gain", records["week"])
        self.assertIn("distance", records["day"])

    def test_filters_unselected_types_and_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-01-01": self._entry(distance=9999.0)}},
            "2026": {
                "Ride": {"2026-01-01": self._entry(distance=1000.0)},
                "Run": {"2026-01-02": self._entry(distance=8888.0)},
            },
        }
        records = self._run_records(aggregates, ["Ride"], [2026])
        self.assertAlmostEqual(records["day"]["distance"]["value"], 1000.0)


class RecordsLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_records_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":records`"), 2)
        self.assertEqual(self.app_js.count('"Records",'), 2)

    def test_records_period_groups(self) -> None:
        for label in ("Best Day", "Best Week", "Best Month"):
            self.assertIn(f'label: "{label}"', self.app_js)

    def test_records_metric_order(self) -> None:
        self.assertIn(
            'const RECORDS_METRIC_ORDER = ["distance", "moving_time", "elevation_gain", "count"];',
            self.app_js,
        )

    def test_records_styles_present(self) -> None:
        for selector in (
            ".records-card",
            ".records-groups",
            ".record-group-title",
            ".record-row",
            ".record-value",
            ".record-when",
        ):
            self.assertIn(selector, self.index_html)


if __name__ == "__main__":
    unittest.main()
