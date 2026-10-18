"""Static caption edit descriptors remain pinned to the Kachinco producer."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CaptionStyleCatalogTests(unittest.TestCase):
    def test_both_existing_catalogs_match_the_complete_producer_edit_schema(self):
        fixture = json.loads((ROOT / "tests/fixtures/kachinco-clip-tools.json").read_text())
        producer = next(t for t in fixture if t["name"] == "edit_batch")
        for name in ("_kachinco-clips.example.yaml", "_kachinco-titles.example.yaml"):
            text = (ROOT / "config/mcps" / name).read_text()
            catalog = json.loads(text[text.index("{"):])
            edit = next(t for t in catalog["tools"] if t["name"] == "edit_batch")
            self.assertNotIn("inputSchema", edit)
            self.assertEqual(edit["input_schema"], producer["inputSchema"])
            schema = edit["input_schema"]
            self.assertEqual(schema["required"], ["input", "guard"])
            self.assertIn("expectedRevision", schema["properties"]["guard"]["required"])
            commands = schema["properties"]["input"]["properties"]["commands"]["items"]["oneOf"]
            commands = {c["properties"]["type"]["const"]: c for c in commands}
            expected = {
                "PatchCaptionStyles", "SetCaptionStyle", "SetClipSpeed",
                "ReserveTitleFrame", "ApplyCrossfade",
            }
            self.assertTrue(expected <= commands.keys())
            patch = commands["PatchCaptionStyles"]["properties"]
            self.assertEqual(patch["captionIds"]["maxItems"], 4096)
            self.assertEqual(patch["patch"]["required"], [])
            self.assertFalse(patch["patch"]["additionalProperties"])
            self.assertEqual(len(patch["patch"]["properties"]), 14)
            self.assertIn({"type": "null"}, patch["patch"]["properties"]["fontFamily"]["anyOf"])
            reset = commands["SetCaptionStyle"]["properties"]["style"]["anyOf"]
            self.assertIn({"type": "null"}, reset)


if __name__ == "__main__":
    unittest.main()
