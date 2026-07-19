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
    "loadEpochDay",
    "loadDateFromEpochDay",
    "computeRollingLoadSeries",
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
class RollingLoadSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        preamble = (
            "const MS_PER_DAY = 1000 * 60 * 60 * 24;\n"
            "const LOAD_SHORT_WINDOW_DAYS = 7;\n"
            "const LOAD_LONG_WINDOW_DAYS = 28;\n"
        )
        cls.series_source = preamble + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run_series(
        self,
        aggregates: dict,
        types: list[str],
        years: list[int],
        metric_key: str,
        options: dict | None = None,
    ) -> dict | None:
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.series_source}\n"
            "const result = computeRollingLoadSeries(\n"
            "  payload.aggregates, payload.types, payload.years,\n"
            "  payload.metricKey, payload.options || {},\n"
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
                        "options": options,
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

    @staticmethod
    def _point_by_date(result: dict, date_str: str) -> dict:
        year, month, day = (int(part) for part in date_str.split("-"))
        import datetime

        epoch_day = (datetime.date(year, month, day) - datetime.date(1970, 1, 1)).days
        offset = epoch_day - result["firstDay"]
        return result["points"][offset]

    def test_rolling_windows_sum_and_slide_out(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(distance=1000.0),
                    "2026-01-03": self._entry(distance=2000.0),
                    "2026-01-10": self._entry(distance=4000.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026], "distance")
        self.assertEqual(len(result["points"]), 10)
        # Jan 3: both Jan 1 and Jan 3 within 7 days.
        self.assertAlmostEqual(self._point_by_date(result, "2026-01-03")["short"], 3000.0)
        # Jan 8: Jan 1 has slid out of the 7-day window (Jan 2..Jan 8).
        self.assertAlmostEqual(self._point_by_date(result, "2026-01-08")["short"], 2000.0)
        # Jan 10: the 7-day window (Jan 4..Jan 10) holds only Jan 10;
        # all three days are inside the 28-day window.
        end = self._point_by_date(result, "2026-01-10")
        self.assertAlmostEqual(end["short"], 4000.0)
        self.assertAlmostEqual(end["long"], 7000.0)

    def test_gaps_produce_continuous_days_with_decaying_load(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-02-01": self._entry(distance=5000.0),
                    "2026-03-01": self._entry(distance=1000.0),
                },
            },
        }
        result = self._run_series(aggregates, ["Ride"], [2026], "distance")
        self.assertEqual(len(result["points"]), 29)
        # Mid-gap: outside the 7-day window, still inside the 28-day window.
        mid = self._point_by_date(result, "2026-02-15")
        self.assertAlmostEqual(mid["short"], 0.0)
        self.assertAlmostEqual(mid["long"], 5000.0)
        # Mar 1: Feb 1 has slid out of the 28-day window (Feb 2..Mar 1).
        end = self._point_by_date(result, "2026-03-01")
        self.assertAlmostEqual(end["short"], 1000.0)
        self.assertAlmostEqual(end["long"], 1000.0)

    def test_timeline_is_continuous_across_year_boundary(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-12-30": self._entry(distance=1000.0)}},
            "2026": {"Ride": {"2026-01-02": self._entry(distance=2000.0)}},
        }
        result = self._run_series(aggregates, ["Ride"], [2025, 2026], "distance")
        self.assertEqual(len(result["points"]), 4)
        end = self._point_by_date(result, "2026-01-02")
        self.assertAlmostEqual(end["short"], 3000.0)

    def test_merges_types_and_filters_years(self) -> None:
        aggregates = {
            "2025": {"Ride": {"2025-06-01": self._entry(distance=999.0)}},
            "2026": {
                "Ride": {"2026-06-01": self._entry(distance=1000.0)},
                "VirtualRide": {"2026-06-01": self._entry(distance=2000.0)},
            },
        }
        result = self._run_series(
            aggregates, ["Ride", "VirtualRide"], [2026], "distance"
        )
        self.assertEqual(len(result["points"]), 1)
        self.assertAlmostEqual(result["points"][0]["short"], 3000.0)

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
        self.assertEqual(result["points"][-1]["short"], 3)

    def test_custom_windows_are_respected(self) -> None:
        aggregates = {
            "2026": {
                "Ride": {
                    "2026-01-01": self._entry(distance=1000.0),
                    "2026-01-04": self._entry(distance=2000.0),
                },
            },
        }
        result = self._run_series(
            aggregates,
            ["Ride"],
            [2026],
            "distance",
            options={"shortWindow": 2, "longWindow": 3},
        )
        self.assertEqual(result["shortWindow"], 2)
        self.assertEqual(result["longWindow"], 3)
        end = self._point_by_date(result, "2026-01-04")
        self.assertAlmostEqual(end["short"], 2000.0)
        self.assertAlmostEqual(end["long"], 2000.0)

    def test_empty_selection_returns_null(self) -> None:
        self.assertIsNone(self._run_series({}, ["Ride"], [2026], "distance"))
        aggregates = {
            "2026": {"Ride": {"2026-01-01": self._entry(distance=0.0, count=0)}},
        }
        self.assertIsNone(
            self._run_series(aggregates, ["Ride"], [2026], "distance")
        )


class LoadLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_load_card_is_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":load`"), 2)
        self.assertEqual(self.app_js.count('"Training Load",'), 2)

    def test_load_defaults(self) -> None:
        self.assertIn('const LOAD_DEFAULT_METRIC_KEY = "distance";', self.app_js)
        self.assertIn("const LOAD_SHORT_WINDOW_DAYS = 7;", self.app_js)
        self.assertIn("const LOAD_LONG_WINDOW_DAYS = 28;", self.app_js)

    def test_load_chart_width_fits_content_rail(self) -> None:
        # left + innerWidth + right + ~66px card chrome must fit the 1250px
        # content rail since the card renders as its own full-width row.
        layout = re.search(
            r"const LOAD_CHART_LAYOUT = Object\.freeze\(\{[\s\S]*?\}\);",
            self.app_js,
        ).group(0)
        values = {
            key: int(value)
            for key, value in re.findall(r"(\w+): (\d+)", layout)
        }
        svg_width = values["left"] + values["innerWidth"] + values["right"]
        self.assertLessEqual(svg_width, 1184)

    def test_load_state_participates_in_reset_all(self) -> None:
        reset_handler = self.app_js.split("resetAllButton.addEventListener", 1)[1]
        reset_handler = reset_handler.split("update({", 1)[0]
        self.assertIn(
            "selectedLoadMetricKey = LOAD_DEFAULT_METRIC_KEY;", reset_handler
        )
        self.assertIn("isDefaultLoadState()", self.app_js)

    def test_load_styles_present(self) -> None:
        for selector in (
            ".load-card",
            ".load-chart-area",
            ".load-line",
            ".load-line-short",
            ".load-line-long",
            ".labeled-card-row-load > .card",
        ):
            self.assertIn(selector, self.index_html)

    def test_load_chart_reuses_shared_progress_chart_styles(self) -> None:
        # Gridlines, axis labels, hover strips, and the legend reuse the
        # shared progress chart classes instead of duplicating CSS.
        build_load = self.app_js.split("function buildLoadCard", 1)[1]
        build_load = build_load.split("function buildRecordsCard", 1)[0]
        for class_name in (
            "progress-gridline",
            "progress-axis-label",
            "progress-hover-strip",
            "progress-legend",
        ):
            self.assertIn(class_name, build_load)

    def test_load_chips_reuse_metric_chip_styling(self) -> None:
        self.assertIn("load-metric-chips", self.app_js)


if __name__ == "__main__":
    unittest.main()
