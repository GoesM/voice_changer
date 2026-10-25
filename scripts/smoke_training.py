"""Opt-in synthetic integration test. Never records a microphone or judges voice quality."""
import argparse
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from voice_changer import setup
from voice_changer.jobs import Job
from voice_changer.rvc import RvcProcessor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    engine = args.engine_root.resolve()
    project = args.project.resolve()
    setup.engine_root = lambda: engine
    python, source = setup.engine_paths()
    if project.exists():
        raise SystemExit("Choose a new test project directory; existing projects are not overwritten.")
    recordings = project / "recordings"
    recordings.mkdir(parents=True)
    for number in range(8):
        rate = 40000
        t = np.arange(rate * 4) / rate
        phase = 2 * np.pi * ((110 + number * 12) * t + 15 * np.sin(2 * np.pi * .7 * t))
        signal = sum(np.sin(k * phase) / k for k in range(1, 8)) * .08
        signal *= np.minimum(1, t * 5) * np.minimum(1, (4 - t) * 5)
        with wave.open(str(recordings / f"synthetic_{number}.wav"), "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(rate)
            file.writeframes((signal * 32767).astype("<i2").tobytes())
    # One epoch only exercises infrastructure; deliberately bypasses the UI's
    # ten-minute material gate. Never lists this non-speech model as a user voice.
    worker = Path(__file__).resolve().parents[1] / "voice_changer/engine_worker.py"
    Job().run([python, worker, "train", project, "1"], source, print, project / "training.log")
    report = {"scope": "32 seconds synthetic non-speech, one training epoch; no microphone, quality or target-app test",
              "modes": {}}
    for mode in ("game", "meeting"):
        processor = RvcProcessor(project, mode, 8)
        try:
            signal = (.08 * np.sin(np.arange(processor.block) * 2 * np.pi * 145 / 48000)).astype("float32")
            times, peaks = [], []
            for _ in range(50):
                started = time.perf_counter()
                output = processor(signal)
                times.append((time.perf_counter() - started) * 1000)
                assert output.shape == signal.shape and np.isfinite(output).all()
                peaks.append(float(np.max(np.abs(output))))
            assert max(peaks) > 1e-6
            report["modes"][mode] = {"blocks": 50, "processing_p95_ms": float(np.percentile(times, 95)),
                                      "processing_max_ms": max(times), "peak": max(peaks)}
        finally:
            processor.close()
    (project / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
