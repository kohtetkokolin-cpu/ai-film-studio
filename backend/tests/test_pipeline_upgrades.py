import unittest

from app.main import (
    FLOW_CREDIT_COST,
    _compact_prompt,
    _expand_template_novel,
    compile_scene_prompts,
    format_screenplay,
    generate_template_package,
)


class PipelineUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "title": "Test Film",
            "genre": "Drama",
            "duration_seconds": 60,
            "visual_style": "Realistic cinematic",
            "aspect_ratio": "16:9",
            "language": "Burmese",
            "culture": "Myanmar",
            "generation_mode": "template",
            "sound_mode": "dialogue",
            "story_idea": "Mother waits for her son. He returns late at night.",
            "character_bible": "Mother - age 52",
            "location_bible": "Village house",
            "continuity_notes": "",
        }

    def test_novel_expansion_covers_full_arc(self):
        beats = [(f"Beat{i}", f"rule{i}") for i in range(8)]
        novel = _expand_template_novel("A short story.", beats, ["A short story."], "Drama")
        for arc in ["အစ", "အရှိန်မြှင့်ခြင်း", "အလှည့်အပြောင်း", "အကျိုးဆက်", "အဆုံး"]:
            self.assertIn(arc, novel)

    def test_compact_prompt_respects_limit(self):
        long_text = "Create a cinematic shot. " * 100
        self.assertLessEqual(len(_compact_prompt(long_text, 800)), 800)
        self.assertEqual(_compact_prompt("short", 800), "short")

    def test_clips_have_per_tool_prompts(self):
        package = generate_template_package(self.project)
        clips = compile_scene_prompts(self.project, package)
        self.assertEqual(len(clips), 8)
        for clip in clips:
            self.assertEqual(clip["flow_prompt"], clip["visual_prompt"])
            self.assertLessEqual(len(clip["youtube_prompt"]), 800)
            self.assertGreater(len(clip["youtube_prompt"]), 50)

    def test_screenplay_renders_scenes(self):
        package = generate_template_package(self.project)
        text = format_screenplay(self.project, package)
        self.assertIn("SCREENPLAY", text)
        self.assertIn("Location:", text)

    def test_flow_credit_costs(self):
        self.assertEqual(FLOW_CREDIT_COST, {"lite": 10, "fast": 20, "quality": 100})


if __name__ == "__main__":
    unittest.main()
