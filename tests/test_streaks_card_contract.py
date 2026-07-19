import datetime
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
    "loadEpochDay",
    "streakWeekStartEpochDay",
    "computeStreakStats",
]


def _extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)\s*{{[\s\S]*?\n}}\n",
        source,
    )
    if not match:
        raise AssertionError(f"Could not find {name} in site/app.js")
    return match.group(0)


def _epoch_day(date_str: str) -> int:
    year, month, day = (int(part) for part in date_str.split("-"))
    return (datetime.date(year, month, day) - datetime.date(1970, 1, 1)).days


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class StreakStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        preamble = "const MS_PER_DAY = 1000 * 60 * 60 * 24;\n"
        cls.stats_source = preamble + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_stats(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        week_start: str = "sunday",
        reference_date: str | None = None,
    ) -> dict | None:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.stats_source}\n"
            "const result = computeStreakStats(\n"
            "  payload.aggregates, payload.types, payload.years,\n"
            "  payload.weekStart, payload.referenceEpochDay,\n"
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
                        "referenceEpochDay": (
                            _epoch_day(reference_date) if reference_date else None
                        ),
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

    def test_longest_streak_counts_consecutive_weeks(self) -> None:
        # Sundays: 2026-01-04, 11, 18 start consecutive weeks; gap; 2026-02-08.
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-05": self._entry(),
                    "2026-01-14": self._entry(),
                    "2026-01-24": self._entry(),
                    "2026-02-10": self._entry(),
                },
            },
        }
        result = self._run_stats(aggregates, ["Ride"], [2026])
        streak = result["longestStreak"]
        self.assertEqual(streak["weeks"], 3)
        self.assertEqual(streak["startWeekDay"], _epoch_day("2026-01-04"))
        self.assertEqual(streak["endWeekDay"], _epoch_day("2026-01-18"))

    def test_streak_spans_year_boundary(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-12-29": self._entry()}},
            "2026": {"Ride": {"2026-01-07": self._entry()}},
        }
        # Weeks (sunday start): 2025-12-28 and 2026-01-04 are consecutive.
        result = self._run_stats(aggregates, ["Ride"], [2025, 2026])
        self.assertEqual(result["longestStreak"]["weeks"], 2)

    def test_week_start_monday_changes_bucketing(self) -> None:
        # Sunday 2026-01-11 and Monday 2026-01-12: same week with sunday
        # start, different weeks with monday start.
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-11": self._entry(),
                    "2026-01-12": self._entry(),
                },
            },
        }
        sunday = self._run_stats(aggregates, ["Ride"], [2026], week_start="sunday")
        monday = self._run_stats(aggregates, ["Ride"], [2026], week_start="monday")
        self.assertEqual(sunday["activeWeekCount"], 1)
        self.assertEqual(monday["activeWeekCount"], 2)
        self.assertEqual(monday["longestStreak"]["weeks"], 2)

    def test_ties_keep_earliest_run_and_gap(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    # Two 1-week runs separated by inactive weeks; earliest kept.
                    "2026-01-05": self._entry(),
                    "2026-02-02": self._entry(),
                    # Equal 8-day gaps: Jan 6..Jan 13 minus... gaps below.
                },
            },
        }
        result = self._run_stats(aggregates, ["Ride"], [2026])
        self.assertEqual(result["longestStreak"]["weeks"], 1)
        self.assertEqual(
            result["longestStreak"]["startWeekDay"], _epoch_day("2026-01-04")
        )

    def test_longest_break_days_and_range(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(),
                    "2026-01-05": self._entry(),
                    "2026-01-31": self._entry(),
                },
            },
        }
        result = self._run_stats(aggregates, ["Ride"], [2026])
        gap = result["longestBreak"]
        self.assertEqual(gap["days"], 25)
        self.assertEqual(gap["fromDay"], _epoch_day("2026-01-06"))
        self.assertEqual(gap["toDay"], _epoch_day("2026-01-30"))

    def test_current_streak_with_grace_for_in_progress_week(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-06-29": self._entry(),
                    "2026-07-08": self._entry(),
                    "2026-07-15": self._entry(),
                },
            },
        }
        # Reference Sunday 2026-07-19 starts a new week with no activity yet;
        # the run ending the prior week (Jul 12..18) still counts.
        result = self._run_stats(
            aggregates, ["Ride"], [2026], reference_date="2026-07-19"
        )
        streak = result["currentStreak"]
        self.assertEqual(streak["weeks"], 3)
        self.assertFalse(streak["includesReferenceWeek"])
        # Two weeks later the streak is broken.
        stale = self._run_stats(
            aggregates, ["Ride"], [2026], reference_date="2026-08-02"
        )
        self.assertIsNone(stale["currentStreak"])

    def test_current_break_days_since_last_activity(self) -> None:
        aggregates = {
            "2026": {"Ride": {"2026-07-10": self._entry()}},
        }
        result = self._run_stats(
            aggregates, ["Ride"], [2026], reference_date="2026-07-19"
        )
        self.assertEqual(result["currentBreakDays"], 9)
        same_day = self._run_stats(
            aggregates, ["Ride"], [2026], reference_date="2026-07-10"
        )
        self.assertEqual(same_day["currentBreakDays"], 0)

    def test_merges_types_filters_years_and_ignores_zero_counts(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-01": self._entry()}},
            "2026": {
                "Ride": {"2026-06-01": self._entry()},
                "VirtualRide": {
                    "2026-06-02": self._entry(),
                    "2026-06-03": self._entry(count=0),
                },
            },
        }
        result = self._run_stats(
            aggregates, ["Ride", "VirtualRide"], [2026]
        )
        self.assertEqual(result["activeDayCount"], 2)
        self.assertEqual(result["firstActiveDay"], _epoch_day("2026-06-01"))

    def test_empty_selection_returns_null(self) -> None:
        self.assertIsNone(self._run_stats({}, ["Ride"], [2026]))


class StreaksLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_streaks_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":streaks`"), 2)
        self.assertEqual(self.app_js.count('"Streaks & Gaps",'), 2)

    def test_streaks_card_is_stateless(self) -> None:
        # No chips or persisted state: the card must not appear in the Reset
        # All handler or in isDefaultFilterState.
        self.assertNotIn("selectedStreaks", self.app_js)
        self.assertNotIn("isDefaultStreaksState", self.app_js)
        build = self.app_js.split("function buildStreaksCard", 1)[1]
        build = build.split("\nfunction renderLoadError", 1)[0]
        self.assertNotIn("trends-chip", build)
        self.assertNotIn("onStateChange", build)

    def test_streaks_card_reuses_records_styles(self) -> None:
        build = self.app_js.split("function buildStreaksCard", 1)[1]
        build = build.split("\nfunction renderLoadError", 1)[0]
        for class_name in (
            "records-card",
            "records-groups",
            "record-group",
            "record-row",
            "record-metric",
            "record-value",
            "record-when",
        ):
            self.assertIn(class_name, build)

    def test_streaks_styles_present(self) -> None:
        for selector in (
            ".labeled-card-row-streaks > .card",
            ".streaks-card .record-row",
        ):
            self.assertIn(selector, self.index_html)


if __name__ == "__main__":
    unittest.main()
