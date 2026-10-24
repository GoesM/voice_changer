"""Synthetic-signal integration test, not an audio-quality or end-to-end latency claim."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from voice_changer.beatrice import BeatriceProcessor


def run(plugin, model):
    processor = BeatriceProcessor(plugin, model)
    block = (0.08 * np.sin(2 * np.pi * 145 * np.arange(960) / 48000)).astype("float32")
    times, peaks = [], []
    for _ in range(500):
        start = time.perf_counter()
        result = processor(block)
        times.append((time.perf_counter() - start) * 1000)
        assert result.shape == block.shape and np.isfinite(result).all()
        peaks.append(float(np.max(np.abs(result))))
    assert max(peaks) > 1e-5
    return {"test": "synthetic VST3 streaming, 500 x 20ms blocks", "blocks": 500,
            "processing_p50_ms": float(np.percentile(times, 50)),
            "processing_p95_ms": float(np.percentile(times, 95)),
            "processing_max_ms": max(times), "peak": max(peaks),
            "scope": "No microphone capture; not end-to-end latency or perceptual quality."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin")
    parser.add_argument("model")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = json.dumps(run(args.plugin, args.model), indent=2)
    print(report)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
