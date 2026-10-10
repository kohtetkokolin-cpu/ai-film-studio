import unittest
from unittest.mock import patch

from app.main import compile_scene_prompts, generate_production_package, generate_template_package, validate_package


class TemplateProductionTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "title": "အိမ်ပြန်လာသောည",
            "genre": "Drama",
            "duration_seconds": 60,
            "visual_style": "Realistic cinematic",
            "aspect_ratio": "9:16",
            "language": "Burmese",
            "culture": "Myanmar",
            "generation_mode": "template",
            "sound_mode": "dialogue",
            "story_idea": "မောင်မောင် အိမ်ပြန်လာပြီး အမေနှင့် စကားများသည်။ သူ့လက်ထဲမှာ စာအိတ်တစ်အိတ်ရှိသည်။",
            "character_bible": "မောင်မောင် — အသက် ၂၅ နှစ်၊ ဆံပင်အနက်။\nအမေ — အသက် ၅၂ နှစ်၊ ဆံပင်တို။",
            "location_bible": "LOC-A — အိမ်အပြင်ဘက်။\nLOC-B — အိမ်အတွင်း။",
            "continuity_notes": "စာအိတ်ကို တစ်သမတ်တည်းထားရန်",
        }

    def test_one_minute_has_exactly_eight_clips(self):
        package = generate_template_package(self.project)
        self.assertEqual(len(package["scenes"]), 8)
        self.assertEqual(sum(s["duration_seconds"] for s in package["scenes"]), 60)
        self.assertEqual(package["scenes"][-1]["duration_seconds"], 4)
        self.assertTrue(package["quality_report"]["passed"])

    def test_template_mode_never_calls_gemini(self):
        with patch("app.main.generate_gemini_package", side_effect=AssertionError("Gemini must not run")):
            package = generate_production_package(self.project)
        self.assertEqual(package["generation_source"], "template")

    def test_prompt_output_contains_reference_ids_and_both_prompt_types(self):
        package = generate_template_package(self.project)
        clips = compile_scene_prompts(self.project, package)
        self.assertEqual(len(clips), 8)
        self.assertIn("CHAR-001", clips[0]["visual_prompt"])
        self.assertIn("LOC-A", clips[0]["visual_prompt"])
        self.assertTrue(clips[0]["image_prompt"])
        self.assertTrue(clips[0]["negative_prompt"])

    def test_auto_mode_falls_back_on_temporary_failure(self):
        project = {**self.project, "generation_mode": "auto"}
        with patch("app.main.generate_gemini_package", side_effect=RuntimeError("503 UNAVAILABLE")):
            package = generate_production_package(project)
        self.assertEqual(package["generation_source"], "template_fallback")
        self.assertEqual(len(package["scenes"]), 8)

    def test_three_minutes_has_23_scenes_and_valid_timeline(self):
        project = {**self.project, "duration_seconds": 180}
        package = generate_template_package(project)
        report = validate_package(package, 180)
        self.assertEqual(len(package["scenes"]), 23)
        self.assertEqual(package["scenes"][-1]["duration_seconds"], 4)
        self.assertTrue(report["passed"], report["issues"])


if __name__ == "__main__":
    unittest.main()
