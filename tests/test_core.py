import json
import queue
import struct
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

import numpy as np

from voice_changer.assets import extract_checked, verify_file
from voice_changer.audio import AudioEngine, offer_latest, validate_route
from voice_changer.beatrice import make_preset, validate_model
from voice_changer.config import load_settings, save_settings


class CoreTests(unittest.TestCase):
    def test_queue_drops_oldest(self):
        q = queue.Queue(2)
        self.assertFalse(offer_latest(q, 1))
        offer_latest(q, 2)
        self.assertTrue(offer_latest(q, 3))
        self.assertEqual([q.get(), q.get()], [2, 3])

    def test_route_rejects_feedback_and_speaker_output(self):
        mic = {"name": "USB Microphone"}
        cable = {"name": "CABLE Input (VB-Audio Virtual Cable)"}
        validate_route(mic, cable)
        for inp, out, mon in [(cable, cable, None), (mic, mic, None), (mic, cable, cable)]:
            with self.assertRaises(ValueError):
                validate_route(inp, out, mon)

    def test_failure_never_outputs_raw_audio(self):
        def broken(data):
            raise RuntimeError("model failed")
        engine = AudioEngine(broken)
        engine.running.set()
        engine.inputs.put((time.monotonic(), 0, np.ones(960, dtype="float32")))
        engine._worker()
        output = np.ones((960, 2), dtype="float32")
        engine._output(engine.outputs, output)
        self.assertFalse(output.any())
        self.assertIn("model failed", engine.error)

    def test_stale_output_is_silent(self):
        engine = AudioEngine(lambda data: data)
        engine.running.set()
        engine.outputs.put((time.monotonic() - 1, 0, np.ones(960)))
        output = np.ones((960, 2))
        engine._output(engine.outputs, output)
        self.assertFalse(output.any())
        self.assertEqual(engine.drops, 1)

    def test_mute_discards_inflight_audio(self):
        engine = AudioEngine(lambda data: data)
        engine.running.set()
        engine.set_muted(True)
        engine.set_muted(False)
        engine.outputs.put((time.monotonic(), 0, np.ones(960)))
        output = np.ones((960, 2))
        engine._output(engine.outputs, output)
        self.assertFalse(output.any())

    def test_processor_nan_is_failure(self):
        engine = AudioEngine(lambda data: np.full(960, np.nan))
        engine.running.set()
        engine.inputs.put((time.monotonic(), 0, np.ones(960)))
        engine._worker()
        self.assertTrue(engine.error)
        self.assertTrue(engine.outputs.empty())

    def test_config_roundtrip_and_corrupt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            save_settings({"input": "中文麦克风"}, path)
            self.assertEqual(load_settings(path)["input"], "中文麦克风")
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_settings(path), {})

    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape.txt", "no")
            with self.assertRaises(ValueError):
                extract_checked(archive, Path(temp) / "assets")

    def test_bad_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "download"
            file.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                verify_file(file, "0" * 64)

    def test_preset_chunk_table_and_unicode(self):
        preset = make_preset("测试/model.toml")
        self.assertEqual(preset[:4], b"VST3")
        offset = struct.unpack_from("<q", preset, 40)[0]
        self.assertEqual(preset[offset:offset + 4], b"List")
        comp_offset, comp_len = struct.unpack_from("<qq", preset, offset + 12)
        self.assertEqual(comp_offset, 48)
        self.assertEqual(comp_offset + comp_len, offset)
        self.assertIn("测试".encode(), preset)

    def test_incomplete_model_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.toml"
            path.write_text('[model]\nversion="2.0.0-rc.0"', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "phone_extractor"):
                validate_model(path)


if __name__ == "__main__":
    unittest.main()
