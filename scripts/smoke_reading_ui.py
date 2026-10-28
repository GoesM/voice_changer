"""Exercise real Tk controls with simulated audio; never opens an audio device."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
import wave
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice_changer.studio_ui import Studio
from voice_changer.studio import new_project, analyze_wav
from voice_changer import reading


class FakeRecorder:
    def __init__(self, project, device, directory=None):
        directory.mkdir(exist_ok=True)
        self.path = directory / "simulated.wav"
        self.frames = 48000 * 30
        self.error = ""

    def start(self):
        samples = (np.sin(np.arange(16000) * 2 * np.pi * 180 / 16000) * 3000).astype("<i2")
        with wave.open(str(self.path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(samples.tobytes() * 30)

    def stop(self):
        return analyze_wav(self.path)


def main():
    with tempfile.TemporaryDirectory() as directory, \
         patch("voice_changer.studio.projects_root", return_value=Path(directory)), \
         patch("voice_changer.materials.projects_root", return_value=Path(directory)), \
         patch("voice_changer.reading_ui.Recorder", FakeRecorder), \
         patch("sounddevice.stop"), patch("sounddevice.play") as playback:
        root = tk.Tk()
        root.withdraw()
        devices = [{"name": "Test microphone", "inputs": 1, "outputs": 0, "index": 0},
                   {"name": "Test headphones", "inputs": 0, "outputs": 2, "index": 1}]
        app = SimpleNamespace(root=root, device_list=devices,
            input_box=SimpleNamespace(get=lambda: "Test microphone"),
            monitor_box=SimpleNamespace(get=lambda: "Test headphones"),
            find_device=lambda name, direction: next((d for d in devices if d["name"] == name and d[direction]), None),
            refresh_voices=lambda: None)
        studio = Studio(app)
        studio.project = new_project("UI test")
        studio.report()
        studio.open_guide()
        guide = studio.guide
        root.update()
        assert guide.text.get("1.0", "end").strip() == guide.segment["text"]
        guide.record()
        guide.stop()
        assert not reading.completed(studio.project)
        guide.play()
        playback.assert_called_once()
        guide.accept()
        assert guide.index == 1 and len(reading.completed(studio.project)) == 1
        guide.close()
        assert len(studio.clips) == 1
        studio.open_guide()
        root.update()
        assert studio.guide.index == 1
        studio.guide.close()
        studio.close()
        root.update()
        root.destroy()
    print("PASS: Tk guided record/review/accept/resume/library flow; simulated audio, no hardware capture")


if __name__ == "__main__":
    main()
