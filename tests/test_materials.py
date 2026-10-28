import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

import numpy as np

from voice_changer import materials, reading, studio


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch("voice_changer.studio.projects_root", return_value=self.root),
                        patch("voice_changer.materials.projects_root", return_value=self.root)]
        for item in self.patches:
            item.start()
        self.project = studio.new_project("同一说话人")
        self.segment = reading.script()["segments"][0]

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def wav(self, name="take.wav", seconds=30, value=None, folder=".takes"):
        directory = self.project / folder
        directory.mkdir(exist_ok=True)
        path = directory / name
        samples = (np.sin(np.arange(16000) * 2 * np.pi * 180 / 16000) * 3000).astype("<i2")
        if value is not None:
            samples.fill(value)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            for _ in range(seconds):
                audio.writeframes(samples.tobytes())
        return path

    def test_script_has_sufficient_original_text_and_stable_ids(self):
        content = reading.script()
        self.assertEqual(len(content["segments"]), 40)
        self.assertGreaterEqual(content["characters"], 4500)
        self.assertEqual(len({s["id"] for s in content["segments"]}), 40)
        source = Path(reading.__file__).parent / "resources/reading_zh.txt"
        for segment in content["segments"]:
            self.assertIn(segment["text"], source.read_text(encoding="utf-8"))

    def test_pending_take_never_counts_toward_training(self):
        path = self.wav()
        reading.save_pending(self.project, self.segment["id"], path)
        self.assertEqual(studio.dataset_report(self.project)["seconds"], 0)
        self.assertEqual(reading.completed(self.project), set())
        self.assertTrue(reading.pending_take(self.project, self.segment["id"]).samefile(path))

    def test_accept_resume_and_remove_update_progress(self):
        path = self.wav()
        reading.save_pending(self.project, self.segment["id"], path)
        reading.accept_take(self.project, self.segment)
        reading.save_position(self.project, 7)
        self.assertEqual(reading.state(self.project)["current"], 7)
        self.assertIn(self.segment["id"], reading.completed(self.project))
        self.assertEqual(studio.dataset_report(self.project)["seconds"], 30)
        self.assertFalse(path.exists())
        self.assertEqual(materials.list_clips(self.project)[0]["source"], "引导朗读")
        materials.remove_clip(self.project, path.name)
        self.assertEqual(reading.completed(self.project), set())
        self.assertEqual(len(list((self.project / ".trash").glob("*.wav"))), 1)
        self.assertEqual(studio.dataset_report(self.project)["seconds"], 0)

    def test_failed_retake_preserves_previous_accepted_audio(self):
        good = self.wav("good.wav")
        reading.save_pending(self.project, self.segment["id"], good)
        reading.accept_take(self.project, self.segment)
        for name, seconds, value in [("short.wav", 3, None), ("quiet.wav", 30, 0), ("clipped.wav", 30, 32767)]:
            path = self.wav(name, seconds, value)
            reading.save_pending(self.project, self.segment["id"], path)
            with self.assertRaises(ValueError):
                reading.accept_take(self.project, self.segment)
            self.assertTrue((self.project / "recordings/good.wav").is_file())
            self.assertIn(self.segment["id"], reading.completed(self.project))

    def test_accepted_retake_replaces_training_material_without_duplicate_duration(self):
        for name in ("first.wav", "second.wav"):
            path = self.wav(name)
            reading.save_pending(self.project, self.segment["id"], path)
            reading.accept_take(self.project, self.segment)
        self.assertEqual(studio.dataset_report(self.project)["seconds"], 30)
        self.assertEqual(len(list((self.project / ".trash").glob("*.wav"))), 1)

    def test_rename_changes_label_not_audio_path(self):
        path = self.wav(folder="recordings")
        materials.rename_clip(self.project, path.name, "早晨录音")
        self.assertEqual(materials.list_clips(self.project)[0]["label"], "早晨录音")
        self.assertTrue(path.is_file())
        materials.rename_collection(self.project, "新的素材集名称")
        self.assertIn("新的素材集名称", materials.collections()[0][0])

    def test_copy_collection_excludes_models_and_pending_audio(self):
        self.wav(folder="recordings")
        self.wav("pending.wav")
        (self.project / "model.pth").write_bytes(b"not a real model")
        target = materials.copy_collection(self.project, "新训练项目")
        self.assertEqual(len(materials.list_clips(target)), 1)
        self.assertFalse((target / "model.pth").exists())
        self.assertFalse((target / ".takes").exists())
        self.assertEqual(json.loads((target / "project.json").read_text(encoding="utf-8"))["state"], "collecting")

    def test_manifest_paths_cannot_escape_collection(self):
        outside = self.root / "outside.wav"
        outside.write_bytes(b"keep")
        studio.write_json(self.project / "reading.json", {"accepted": {"bad": "../../outside.wav"}})
        with self.assertRaises(ValueError):
            reading.completed(self.project)
        with self.assertRaises(ValueError):
            materials.remove_clip(self.project, "../../outside.wav")
        self.assertEqual(outside.read_bytes(), b"keep")

    def test_companion_archive_is_text_only(self):
        from scripts import package_reading
        # Build into an isolated fake repository root, never inspect private audio.
        resource = self.root / "voice_changer/resources"
        resource.mkdir(parents=True)
        (resource / "LICENSE-reading.txt").write_text("CC0-1.0", encoding="utf-8")
        with patch.object(package_reading, "ROOT", self.root):
            path = package_reading.build()
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {"READING.md", "reading_zh.json", "LICENSE-reading.txt"})
            self.assertEqual(len(json.loads(archive.read("reading_zh.json"))["segments"]), 40)


if __name__ == "__main__":
    unittest.main()
