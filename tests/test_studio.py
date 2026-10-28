import json
from pathlib import Path
import tempfile
import os
import socket
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np

from voice_changer.jobs import Job, Cancelled
from voice_changer.studio import analyze_wav, dataset_report, new_project, train, list_voices
from voice_changer.setup import fetch, prepare_driver
from voice_changer.engine_worker import offline


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch("voice_changer.studio.projects_root", return_value=self.root)
        self.patch.start()
        self.disk_patch = patch("voice_changer.studio.shutil.disk_usage", return_value=SimpleNamespace(free=10 * 1024**3))
        self.disk_patch.start()

    def tearDown(self):
        self.disk_patch.stop()
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

    def test_failed_child_process_is_not_reported_as_success(self):
        with self.assertRaises(RuntimeError):
            Job().run([sys.executable, "-c", "raise SystemExit(9)"], self.root,
                      lambda _: None, self.root / "job.log")

    def test_child_unicode_progress_is_preserved(self):
        messages = []
        Job().run([sys.executable, "-c", "print('训练完成 🎵')"], self.root,
                  messages.append, self.root / "unicode.log")
        self.assertEqual(messages, ["训练完成 🎵"])

    def test_offline_inference_rejects_network_connections(self):
        with patch("socket.socket.connect"), patch("socket.socket.connect_ex"), \
             patch("socket.create_connection"), patch.dict(os.environ):
            offline()
            with self.assertRaises(RuntimeError):
                socket.create_connection(("example.org", 443))
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")

    def test_retraining_does_not_remove_existing_ready_voice(self):
        project = new_project("可用音色")
        metadata = project / "project.json"
        metadata.write_text(json.dumps({"name": "可用音色", "state": "ready"}), encoding="utf-8")
        (project / "model.pth").write_bytes(b"fixture")
        (project / "model.index").write_bytes(b"fixture")
        with patch("voice_changer.studio.engine_ready", return_value=True), \
             patch("voice_changer.studio.dataset_report", return_value={"ready": True}):
            with self.assertRaises(ValueError):
                train(project, 100, lambda _: None, Job())
        self.assertEqual(len(list_voices()), 1)

    def test_driver_check_does_not_inherit_powershell_7_modules(self):
        with patch.dict(os.environ, {"PSMODULEPATH": "incompatible-powershell-7-modules"}), \
             patch("voice_changer.setup.data_dir", return_value=self.root), \
             patch("voice_changer.setup.fetch", return_value=self.root / "driver.zip"), \
             patch("voice_changer.setup.extract_checked"), \
             patch("voice_changer.setup.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Valid\n", "")) as run:
            prepare_driver(lambda _: None, Job())
            self.assertFalse(any(key.upper() == "PSMODULEPATH" for key in run.call_args.kwargs["env"]))


if __name__ == "__main__":
    unittest.main()
