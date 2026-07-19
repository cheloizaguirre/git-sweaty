import json
import os
import re
import shutil
import subprocess
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_JS_PATH = os.path.join(ROOT_DIR, "site", "app.js")
INDEX_HTML_PATH = os.path.join(ROOT_DIR, "site", "index.html")
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")

HELPER_FUNCTION_NAMES = [
    "activityMetricValue",
    "activitiesHaveMetrics",
    "computeActivityRecords",
    "computeDistanceHistogram",
]


def _extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)\s*{{[\s\S]*?\n}}\n",
        source,
    )
    if not match:
        raise AssertionError(f"Could not find {name} in site/app.js")
    return match.group(0)


class PipelineActivityFieldsTests(unittest.TestCase):
    def test_load_activities_includes_per_activity_metrics(self) -> None:
        import sys

        sys.path.insert(0, SCRIPTS_DIR)
        try:
            import importlib

            module = importlib.import_module("generate_heatmaps")
            activity_items = [
                {
                    "date": "2026-07-16",
                    "year": 2026,
                    "type": "VirtualRide",
                    "raw_type": "VirtualRide",
                    "start_date_local": "2026-07-16T20:20:51Z",
                    "distance": 16899.14,
                    "moving_time": 3624.0,
                    "elevation_gain": 317.0,
                },
                {
                    "date": "2026-07-17",
                    "year": 2026,
                    "type": "Ride",
                    "raw_type": "Ride",
                    "start_date_local": "2026-07-17T08:00:00Z",
                    "distance": None,
                    "moving_time": "bogus",
                    "elevation_gain": -5.0,
                },
            ]
            import unittest.mock as mock

            with mock.patch.object(module.os.path, "exists", return_value=True), \
                    mock.patch.object(module, "read_json", return_value=activity_items):
                activities = module._load_activities(source="strava")
        finally:
            sys.path.remove(SCRIPTS_DIR)

        self.assertEqual(len(activities), 2)
        first, second = activities
        self.assertAlmostEqual(first["distance"], 16899.1)
        self.assertAlmostEqual(first["moving_time"], 3624.0)
        self.assertAlmostEqual(first["elevation_gain"], 317.0)
        # Missing/invalid/negative values coerce to 0.0 rather than crashing.
        self.assertEqual(second["distance"], 0.0)
        self.assertEqual(second["moving_time"], 0.0)
        self.assertEqual(second["elevation_gain"], 0.0)


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class ActivityComputationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        preamble = (
            'const ACTIVITY_RECORD_METRIC_KEYS = ["distance", "moving_time", "elevation_gain"];\n'
            "const HISTOGRAM_TARGET_BINS = 12;\n"
            "const HISTOGRAM_NICE_STEPS = [1, 2, 5, 10, 15, 20, 25, 50, 100, 200];\n"
        )
        cls.source = preamble + "".join(
            _extract_function(cls.app_js, name) for name in HELPER_FUNCTION_NAMES
        )

    def _run(self, snippet: str, payload: dict):
        script = (
            "const payload = JSON.parse(process.argv[1]);\n"
            f"{self.source}\n"
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

    @staticmethod
    def _activity(date, distance=0.0, moving_time=0.0, elevation_gain=0.0, type_="Ride"):
        return {
            "date": date,
            "year": int(date[:4]),
            "type": type_,
            "distance": distance,
            "moving_time": moving_time,
            "elevation_gain": elevation_gain,
        }

    def test_records_pick_max_per_metric_with_earliest_tie(self) -> None:
        activities = [
            self._activity("2026-02-01", distance=50000.0, moving_time=7000.0),
            self._activity("2026-01-01", distance=50000.0, moving_time=6000.0),
            self._activity("2026-03-01", distance=20000.0, elevation_gain=900.0),
        ]
        result = self._run(
            "computeActivityRecords(payload.activities)", {"activities": activities}
        )
        self.assertEqual(result["distance"]["activity"]["date"], "2026-01-01")
        self.assertEqual(result["moving_time"]["activity"]["date"], "2026-02-01")
        self.assertEqual(result["elevation_gain"]["activity"]["date"], "2026-03-01")

    def test_records_omit_metrics_with_no_positive_values(self) -> None:
        activities = [self._activity("2026-01-01", distance=1000.0)]
        result = self._run(
            "computeActivityRecords(payload.activities)", {"activities": activities}
        )
        self.assertIn("distance", result)
        self.assertNotIn("moving_time", result)
        self.assertNotIn("elevation_gain", result)

    def test_activities_have_metrics_detects_old_payloads(self) -> None:
        without_fields = [{"date": "2026-01-01", "year": 2026, "type": "Ride"}]
        with_fields = [self._activity("2026-01-01", distance=1000.0)]
        self.assertFalse(
            self._run("activitiesHaveMetrics(payload.a)", {"a": without_fields})
        )
        self.assertTrue(
            self._run("activitiesHaveMetrics(payload.a)", {"a": with_fields})
        )

    def test_histogram_bins_use_nice_steps_and_clamp_max(self) -> None:
        # Max 32.06 mi -> 5 mi bins (32.06 / 5 <= 12), 7 bins.
        activities = [
            self._activity("2026-01-01", distance=32.06 * 1609.344),
            self._activity("2026-01-02", distance=12.0 * 1609.344),
            self._activity("2026-01-03", distance=14.9 * 1609.344),
            self._activity("2026-01-04", distance=5.0 * 1609.344),
        ]
        result = self._run(
            "computeDistanceHistogram(payload.activities, 1609.344, 12)",
            {"activities": activities},
        )
        self.assertEqual(result["binSize"], 5)
        self.assertEqual(len(result["bins"]), 7)
        self.assertEqual(result["total"], 4)
        counts = {bin_["from"]: bin_["count"] for bin_ in result["bins"]}
        self.assertEqual(counts[10], 2)  # 12.0 and 14.9 in the 10–15 bin
        self.assertEqual(counts[5], 1)   # exactly 5.0 lands in the 5–10 bin
        self.assertEqual(counts[30], 1)  # max value in the last bin

    def test_histogram_ignores_zero_distance_and_empty(self) -> None:
        self.assertIsNone(
            self._run("computeDistanceHistogram(payload.a, 1609.344, 12)", {"a": []})
        )
        activities = [self._activity("2026-01-01", distance=0.0, moving_time=100.0)]
        self.assertIsNone(
            self._run(
                "computeDistanceHistogram(payload.a, 1609.344, 12)",
                {"a": activities},
            )
        )


class UniformCardWidthContractTests(unittest.TestCase):
    """Single-card rows span the content rail; pairs split it 50/50 with
    equal heights; viewBox SVG charts scale to fill their cards."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def _block(self, selector: str) -> str:
        index = self.index_html.index(selector)
        return self.index_html[index:self.index_html.index("}", index)]

    def test_pair_rows_split_evenly_and_stretch(self) -> None:
        pair = self._block(".labeled-card-row-pair {")
        self.assertIn("align-items: stretch;", pair)
        child = self._block(".labeled-card-row-pair > .labeled-card-row {")
        self.assertIn("flex: 1 1 320px;", child)
        card = self._block(".labeled-card-row-pair > .labeled-card-row > .card {")
        self.assertIn("width: 100%;", card)
        self.assertIn("flex: 1 1 auto;", card)

    def test_single_card_rows_span_full_width(self) -> None:
        block = self._block(".labeled-card-row-records > .card")
        self.assertIn("width: 100%;", block)
        self.assertNotIn("max-content", block)

    def test_svg_charts_scale_to_card_width(self) -> None:
        block = self._block(".progress-svg {")
        self.assertIn("width: 100%;", block)
        self.assertIn("height: auto;", block)

    def test_no_card_rows_shrink_wrap_anymore(self) -> None:
        for selector in (
            ".labeled-card-row-load > .card",
            ".labeled-card-row-streaks > .card",
            ".labeled-card-row-seasonality > .card",
            ".labeled-card-row-hilliness > .card",
            ".labeled-card-row-speed > .card",
            ".labeled-card-row-histogram > .card",
            ".labeled-card-row-scatter > .card",
        ):
            self.assertIn(selector, self.index_html)
            index = self.index_html.index(selector)
            block = self.index_html[index:self.index_html.index("}", index)]
            self.assertNotIn("max-content", block)


class ActivityCardsLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
            cls.index_html = handle.read()

    def test_cards_are_wired_into_both_render_branches(self) -> None:
        self.assertEqual(self.app_js.count(":histogram`"), 2)
        self.assertEqual(self.app_js.count(":scatter`"), 2)
        for label in ('"Distance Distribution",', '"Distance vs Elevation",'):
            self.assertEqual(self.app_js.count(label), 2)

    def test_best_activity_group_merged_into_records_card(self) -> None:
        # The per-activity records render as a leading group inside the
        # Records card instead of a separate card.
        build = self.app_js.split("function buildRecordsCard", 1)[1]
        build = build.split("\nfunction renderLoadError", 1)[0]
        self.assertIn('"Best Activity"', build)
        self.assertIn("computeActivityRecords(", build)
        self.assertEqual(self.app_js.count("activities: activityList,"), 2)

    def test_cards_hide_on_payloads_without_metrics(self) -> None:
        # Two wiring guards (histogram/scatter pair) plus the guard inside
        # buildRecordsCard for the Best Activity group.
        self.assertEqual(
            self.app_js.count("if (activitiesHaveMetrics(activityList)) {"), 3
        )

    def test_cards_are_stateless(self) -> None:
        self.assertNotIn("selectedActivity", self.app_js)
        self.assertNotIn("selectedHistogram", self.app_js)
        self.assertNotIn("selectedScatter", self.app_js)

    def test_histogram_and_scatter_share_a_pair_row(self) -> None:
        self.assertEqual(
            self.app_js.count('activityPairRow.className = "labeled-card-row-pair";'),
            2,
        )

    def test_styles_present(self) -> None:
        for selector in (
            ".histogram-card",
            ".histogram-bar",
            ".scatter-card",
            ".scatter-dot",
            ".labeled-card-row-scatter > .card",
        ):
            self.assertIn(selector, self.index_html)
        self.assertNotIn(".labeled-card-row-activity-records", self.index_html)


if __name__ == "__main__":
    unittest.main()
