import json
import os
import re
import shutil
import subprocess
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_JS_PATH = os.path.join(ROOT_DIR, "site", "app.js")


@unittest.skipUnless(shutil.which("node"), "node is required for JS unit tests")
class FilterMenuSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(APP_JS_PATH, "r", encoding="utf-8") as handle:
            app_js = handle.read()
        reduce_menu_selection_match = re.search(
            r"function reduceMenuSelection\(\{[\s\S]*?\n}\n",
            app_js,
        )
        if not reduce_menu_selection_match:
            raise AssertionError("Could not find reduceMenuSelection in site/app.js")
        cls.reduce_menu_selection_source = reduce_menu_selection_match.group(0)
        reduce_top_button_match = re.search(
            r"function reduceTopButtonSelection\(\{[\s\S]*?\n}\n",
            app_js,
        )
        if not reduce_top_button_match:
            raise AssertionError(
                "Could not find reduceTopButtonSelection in site/app.js"
            )
        cls.reduce_top_button_source = reduce_top_button_match.group(0)

    def _reduce_menu_selection(self, payload: dict) -> dict:
        script = (
            f"{self.reduce_menu_selection_source}\n"
            "const payload = JSON.parse(process.argv[1]);\n"
            "const args = {\n"
            "  ...payload,\n"
            "  selectedValues: new Set(payload.selectedValues || []),\n"
            "};\n"
            "const result = reduceMenuSelection(args);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  allMode: result.allMode,\n"
            "  selectedValues: Array.from(result.selectedValues || []),\n"
            "}));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script, json.dumps(payload)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_click_all_toggles_off_explicit_all_selection(self) -> None:
        result = self._reduce_menu_selection(
            {
                "rawValue": "all",
                "allMode": False,
                "selectedValues": ["Run", "Ride"],
                "allValues": ["Run", "Ride"],
                "allowToggleOffAll": True,
            }
        )
        self.assertFalse(result["allMode"])
        self.assertEqual(result["selectedValues"], [])

    def test_click_all_from_partial_selection_switches_to_all_mode(self) -> None:
        result = self._reduce_menu_selection(
            {
                "rawValue": "all",
                "allMode": False,
                "selectedValues": ["Run"],
                "allValues": ["Run", "Ride"],
                "allowToggleOffAll": True,
            }
        )
        self.assertTrue(result["allMode"])
        self.assertEqual(result["selectedValues"], [])

    def test_click_all_from_all_mode_toggles_off_when_enabled(self) -> None:
        result = self._reduce_menu_selection(
            {
                "rawValue": "all",
                "allMode": True,
                "selectedValues": [],
                "allValues": ["Run", "Ride"],
                "allowToggleOffAll": True,
            }
        )
        self.assertFalse(result["allMode"])
        self.assertEqual(result["selectedValues"], [])

    # ---- Top-row chip buttons (reduceTopButtonSelection) ----

    def _reduce_top_button(self, payload: dict) -> dict:
        script = (
            f"{self.reduce_top_button_source}\n"
            "const payload = JSON.parse(process.argv[1]);\n"
            "const args = {\n"
            "  ...payload,\n"
            "  selectedValues: new Set(payload.selectedValues || []),\n"
            "};\n"
            "const result = reduceTopButtonSelection(args);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  allMode: result.allMode,\n"
            "  selectedValues: Array.from(result.selectedValues || []),\n"
            "}));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script, json.dumps(payload)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_top_button_all_always_resets_to_all_mode(self) -> None:
        for state in (
            {"allMode": True, "selectedValues": []},
            {"allMode": False, "selectedValues": [2024]},
            {"allMode": False, "selectedValues": [2024, 2025]},
        ):
            result = self._reduce_top_button(
                {
                    "rawValue": "all",
                    "allValues": [2024, 2025],
                    **state,
                }
            )
            self.assertTrue(result["allMode"], state)
            self.assertEqual(result["selectedValues"], [], state)

    def test_top_button_value_from_all_mode_selects_only_that_value(self) -> None:
        result = self._reduce_top_button(
            {
                "rawValue": 2025,
                "allMode": True,
                "selectedValues": [],
                "allValues": [2024, 2025, 2026],
            }
        )
        self.assertFalse(result["allMode"])
        self.assertEqual(result["selectedValues"], [2025])

    def test_top_button_value_from_explicit_all_selects_only_that_value(self) -> None:
        result = self._reduce_top_button(
            {
                "rawValue": 2025,
                "allMode": False,
                "selectedValues": [2024, 2025, 2026],
                "allValues": [2024, 2025, 2026],
            }
        )
        self.assertFalse(result["allMode"])
        self.assertEqual(result["selectedValues"], [2025])

    def test_top_button_later_clicks_toggle_membership(self) -> None:
        added = self._reduce_top_button(
            {
                "rawValue": 2026,
                "allMode": False,
                "selectedValues": [2025],
                "allValues": [2024, 2025, 2026],
            }
        )
        self.assertFalse(added["allMode"])
        self.assertEqual(sorted(added["selectedValues"]), [2025, 2026])
        removed = self._reduce_top_button(
            {
                "rawValue": 2026,
                "allMode": False,
                "selectedValues": [2025, 2026],
                "allValues": [2024, 2025, 2026],
            }
        )
        self.assertEqual(removed["selectedValues"], [2025])

    def test_top_button_removing_last_value_returns_to_all_mode(self) -> None:
        result = self._reduce_top_button(
            {
                "rawValue": 2025,
                "allMode": False,
                "selectedValues": [2025],
                "allValues": [2024, 2025, 2026],
            }
        )
        self.assertTrue(result["allMode"])
        self.assertEqual(result["selectedValues"], [])


if __name__ == "__main__":
    unittest.main()
