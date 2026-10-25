import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

from voice_changer.jobs import Job, Cancelled
from voice_changer.studio import analyze_wav, dataset_report, new_project, train, list_voices
from voice_changer.setup import fetch


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch("voice_changer.studio.projects_root", return_value=self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def wav(self, name, value, seconds=1):
        path = self.root / name
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(np.full(16000 * seconds, value, dtype="<i2").tobytes())
        return path

    def test_silence_and_clipping_are_distinguished(self):
        silent = analyze_wav(self.wav("silence.wav", 0))
        clipped = analyze_wav(self.wav("clip.wav", 32767))
        self.assertEqual(silent["active_seconds"], 0)
        self.assertEqual(clipped["clipping"], 1)

    def test_display_name_cannot_escape_private_project_root(self):
        project = new_project("../../outside")
        self.assertEqual(project.parent, self.root)
        self.assertTrue(project.name.startswith("voice_"))

    def test_empty_project_cannot_train(self):
        project = new_project("测试")
        with patch("voice_changer.studio.engine_ready", return_value=True):
            with self.assertRaises(ValueError):
                train(project, 100, lambda _: None, Job())
        self.assertEqual(list_voices(), [])

    def test_exit_zero_without_export_is_not_success(self):
        project = new_project("测试")
        job = Job()
        with patch("voice_changer.studio.engine_ready", return_value=True), \
             patch("voice_changer.studio.dataset_report", return_value={"ready": True}), \
             patch.object(job, "run", return_value=None):
            with self.assertRaises(RuntimeError):
                train(project, 100, lambda _: None, job)
        state = json.loads((project / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "failed")
        self.assertEqual(list_voices(), [])

    def test_cancelled_training_preserves_material_and_not_listed(self):
        project = new_project("测试")
        job = Job()
        job.cancel()
        with patch("voice_changer.studio.engine_ready", return_value=True), \
             patch("voice_changer.studio.dataset_report", return_value={"ready": True}):
            with self.assertRaises(Cancelled):
                train(project, 100, lambda _: None, job)
        self.assertTrue((project / "recordings").is_dir())
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["state"], "interrupted")
        self.assertEqual(list_voices(), [])

    def test_corrupt_cached_download_is_never_accepted(self):
        path = self.root / "component.zip"
        path.write_bytes(b"corrupt")
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                fetch(("https://example.org/file", "0" * 64), path, lambda _: None, Job())


if __name__ == "__main__":
    unittest.main()
