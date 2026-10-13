import unittest

from app.main import (
    ProjectIn,
    generate_template_package,
    parse_json_response,
    validate_package,
)


class ProductionQualityTests(unittest.TestCase):
    def project(self, duration=60):
        return {
            "title": "Test Short",
            "genre": "Drama",
            "duration_seconds": duration,
            "visual_style": "Realistic cinematic",
            "workflow": "automatic",
            "aspect_ratio": "16:9",
            "language": "Burmese",
            "culture": "Myanmar",
            "generation_mode": "template",
            "sound_mode": "dialogue",
            "story_idea": "A young woman finds an old letter and decides to return home.",
            "character_bible": "Mya — အသက် ၂၅၊ ဆံပင်အနက်",
            "location_bible": "LOC-A — old family house",
            "continuity_notes": "Keep the letter in her right hand.",
        }

    def test_template_timeline_is_exact_and_clips_are_at_most_eight_seconds(self):
        project = self.project(60)
        package = generate_template_package(project)
        report = validate_package(package, 60)
        self.assertEqual(len(package["scenes"]), 8)
        self.assertEqual(sum(s["duration_seconds"] for s in package["scenes"]), 60)
        self.assertTrue(all(1 <= s["duration_seconds"] <= 8 for s in package["scenes"]))
        self.assertTrue(report["passed"], report["issues"])

    def test_rejects_invalid_character_and_location_references(self):
        package = {
            "characters": [{"id": "CHAR-001"}],
            "locations": [{"id": "LOC-A"}],
            "scenes": [{
                "scene_id": "SC-001", "start_seconds": 0, "duration_seconds": 8,
                "location_id": "LOC-MISSING", "character_ids": ["CHAR-MISSING"],
                "action": "Walks", "dramatic_purpose": "Reveal a clue",
                "continuity": ["Prior scene clue", "Next scene consequence"],
                "shot_size": "wide", "lighting": "daylight",
            }],
        }
        report = validate_package(package, 8)
        self.assertFalse(report["passed"])
        self.assertTrue(any("Location ID" in issue for issue in report["issues"]))
        self.assertTrue(any("CHAR-MISSING" in issue for issue in report["issues"]))

    def test_rejects_duplicate_asset_ids_and_discontinuous_timeline(self):
        package = {
            "characters": [{"id": "CHAR-001"}, {"id": "CHAR-001"}],
            "locations": [{"id": "LOC-A"}],
            "scenes": [
                {"scene_id": "SC-001", "start_seconds": 0, "duration_seconds": 8,
                 "location_id": "LOC-A", "character_ids": ["CHAR-001"]},
                {"scene_id": "SC-002", "start_seconds": 12, "duration_seconds": 8,
                 "location_id": "LOC-A", "character_ids": ["CHAR-001"]},
            ],
        }
        report = validate_package(package, 16)
        self.assertFalse(report["passed"])
        self.assertTrue(any("Character ID ထပ်နေ" in issue for issue in report["issues"]))
        self.assertTrue(any("timeline မဆက်စပ်" in issue for issue in report["issues"]))

    def test_parses_json_wrapped_in_markdown_fence(self):
        self.assertEqual(parse_json_response(' ```json\n{"ok": true}\n``` '), {"ok": True})

    def test_project_input_has_reasonable_duration_bounds(self):
        with self.assertRaises(Exception):
            ProjectIn(title="Too short", story_idea="A story", duration_seconds=4)


if __name__ == "__main__":
    unittest.main()
