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
]


def _extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)\s*{{[\s\S]*?\n}}\n",
        source,
    )
    if not match:
        raise AssertionError(f"Could not find {name} in site/app.js")
    return match.group(0)


class TrendsBucketingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        preamble = (
            'const WEEK_START_SUNDAY = "sunday";\n'
            'const WEEK_START_MONDAY = "monday";\n'
            "const MS_PER_DAY = 1000 * 60 * 60 * 24;\n"
        )
        cls.bucketing_source = preamble + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_bucketing(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        granularity: str,
        week_start: str,
    ) -> list[dict]:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.bucketing_source}\n"
            "const result = bucketAggregatesByPeriod(\n"
            "  payload.aggregates, payload.types, payload.years,\n"
            "  payload.granularity, payload.weekStart,\n"
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
                        "granularity": granularity,
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


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class TrendsBucketingBehaviorTests(TrendsBucketingTests):
    def test_monthly_bucketing_sums_days_within_month(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-03-02": self._entry(distance=1000.0),
                    "2026-03-30": self._entry(distance=2000.0),
                    "2026-04-01": self._entry(distance=4000.0),
                },
            },
        }
        result = self._run_bucketing(aggregates, ["Ride"], [2026], "monthly", "sunday")
        self.assertEqual([bucket["key"] for bucket in result], ["2026-03", "2026-04"])
        march = result[0]
        self.assertEqual(march["count"], 2)
        self.assertAlmostEqual(march["distance"], 3000.0)
        self.assertEqual(march["index"], 2)
        self.assertEqual(march["year"], 2026)

    def test_yearly_bucketing_merges_types_and_tracks_per_type(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {"2026-05-01": self._entry(distance=1000.0, elevation_gain=5.0)},
                "VirtualRide": {"2026-06-01": self._entry(distance=3000.0, elevation_gain=7.0)},
            },
        }
        result = self._run_bucketing(
            aggregates, ["Ride", "VirtualRide"], [2026], "yearly", "sunday"
        )
        self.assertEqual(len(result), 1)
        bucket = result[0]
        self.assertEqual(bucket["key"], "2026")
        self.assertEqual(bucket["count"], 2)
        self.assertAlmostEqual(bucket["distance"], 4000.0)
        self.assertAlmostEqual(bucket["elevation_gain"], 12.0)
        self.assertAlmostEqual(bucket["perType"]["Ride"]["distance"], 1000.0)
        self.assertAlmostEqual(bucket["perType"]["VirtualRide"]["distance"], 3000.0)

    def test_weekly_bucketing_respects_week_start(self) -> None:
        # 2026-07-13 is a Monday. With Sunday week start it shares a week with
        # 2026-07-18 (Saturday); with Monday week start 2026-07-12 (Sunday)
        # belongs to the previous week.
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-07-12": self._entry(),
                    "2026-07-13": self._entry(),
                    "2026-07-18": self._entry(),
                },
            },
        }
        sunday_result = self._run_bucketing(aggregates, ["Ride"], [2026], "weekly", "sunday")
        self.assertEqual(len(sunday_result), 1)
        self.assertEqual(sunday_result[0]["count"], 3)

        monday_result = self._run_bucketing(aggregates, ["Ride"], [2026], "weekly", "monday")
        self.assertEqual(len(monday_result), 2)
        self.assertEqual(monday_result[0]["count"], 1)
        self.assertEqual(monday_result[1]["count"], 2)

    def test_bucketing_filters_unselected_types_and_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-01-05": self._entry()}},
            "2026": {
                "Ride": {"2026-01-05": self._entry()},
                "Run": {"2026-01-06": self._entry()},
            },
        }
        result = self._run_bucketing(aggregates, ["Ride"], [2026], "yearly", "sunday")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], "2026")
        self.assertEqual(result[0]["count"], 1)

    def test_buckets_are_sorted_chronologically(self) -> None:
        aggregates = {
            "2026": {"Ride": {"2026-02-01": self._entry()}},
            "2024": {"Ride": {"2024-11-01": self._entry()}},
        }
        result = self._run_bucketing(
            aggregates, ["Ride"], [2026, 2024], "monthly", "sunday"
        )
        self.assertEqual([bucket["key"] for bucket in result], ["2024-11", "2026-02"])


class TrendsLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_trends_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":trends`"), 2)
        self.assertEqual(self.app_js.count('"Trends",'), 2)

    def test_trends_defaults(self) -> None:
        self.assertIn('const TRENDS_DEFAULT_GRANULARITY = "monthly";', self.app_js)
        self.assertIn('const TRENDS_DEFAULT_METRIC_KEY = "distance";', self.app_js)

    def test_trends_granularity_options(self) -> None:
        for key in ("weekly", "monthly", "yearly"):
            self.assertIn(f'key: "{key}"', self.app_js)

    def test_trends_metric_options_include_activities_count(self) -> None:
        self.assertIn('{ key: "count", label: "Activities" }', self.app_js)

    def test_trends_state_participates_in_reset_all(self) -> None:
        reset_handler = self.app_js.split("resetAllButton.addEventListener", 1)[1]
        reset_handler = reset_handler.split("update({", 1)[0]
        self.assertIn("selectedTrendsGranularity = TRENDS_DEFAULT_GRANULARITY;", reset_handler)
        self.assertIn("selectedTrendsMetricKey = TRENDS_DEFAULT_METRIC_KEY;", reset_handler)
        self.assertIn("isDefaultTrendsState()", self.app_js)

    def test_trends_styles_present(self) -> None:
        for selector in (
            ".trends-card",
            ".trends-controls",
            ".trends-chart-area",
            ".trends-bar-slot",
            ".trends-bar-segment",
        ):
            self.assertIn(selector, self.index_html)

    def test_trends_chips_reuse_metric_chip_styling(self) -> None:
        self.assertIn('"more-stats-metric-chip trends-chip"', self.app_js)


if __name__ == "__main__":
    unittest.main()
