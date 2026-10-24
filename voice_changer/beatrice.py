"""Standard VST3 hosting; no private Beatrice inference-library calls.

The preset's component state follows Beatrice's published parameter serialization.
This adapter is version-pinned to the official 2.0.0-rc.3 plugin.
"""
import struct
import tempfile
import tomllib
from pathlib import Path

import numpy as np
from pedalboard import load_plugin

from .audio import SAMPLE_RATE, BLOCK

COMPONENT_ID = b"B0EABF53EAA94CC08F52C9959D91057B"
MODEL_FILES = ("phone_extractor.bin", "pitch_estimator.bin", "waveform_generator.bin",
               "embedding_setter.bin", "speaker_embeddings.bin")


def validate_model(model_path):
    path = Path(model_path).resolve()
    with path.open("rb") as file:
        info = tomllib.load(file)
    if info.get("model", {}).get("version") != "2.0.0-rc.0":
        raise ValueError("初版仅支持 Beatrice 2.0.0-rc.0 模型。")
    for filename in MODEL_FILES:
        candidate = path.parent / filename
        if not candidate.is_file() or candidate.stat().st_size < 16:
            raise ValueError(f"模型不完整：缺少 {filename}")
    if not info.get("voice"):
        raise ValueError("模型缺少音色列表。")
    return info


def make_preset(model_path, voice=1, pitch=8.0, formant=0.0):
    path = str(Path(model_path).resolve()).encode("utf-8")
    # Parameter IDs int16; type tags int32 (0=int32, 1=double, 2=UTF-8 string).
    state = struct.pack("<hii", 1, 2, len(path)) + path
    state += struct.pack("<hii", 2, 0, int(voice))
    state += struct.pack("<hid", 3, 1, float(formant))
    state += struct.pack("<hid", 4, 1, float(pitch))
    component = struct.pack("<i", len(state)) + state
    offset = 48 + len(component)
    header = b"VST3" + struct.pack("<i", 1) + COMPONENT_ID + struct.pack("<q", offset)
    chunks = b"List" + struct.pack("<i", 1) + b"Comp" + struct.pack("<qq", 48, len(component))
    return header + component + chunks


class BeatriceProcessor:
    def __init__(self, plugin_path, model_path, voice=1, pitch=8.0, formant=0.0):
        info = validate_model(model_path)
        if str(voice) not in info["voice"]:
            raise ValueError("所选音色不在模型中。")
        if not -24 <= pitch <= 24 or not -2 <= formant <= 2:
            raise ValueError("音调或共振峰参数越界。")
        plugin = Path(plugin_path).resolve()
        if plugin.is_dir():
            plugin = plugin / "Contents" / "x86_64-win" / "beatrice_2.0.0-rc.3.vst3"
        if not plugin.is_file() or plugin.name != "beatrice_2.0.0-rc.3.vst3":
            raise ValueError("请选择官方 Beatrice 2.0.0-rc.3 Windows VST3 插件。")
        self.plugin = load_plugin(str(plugin))
        with tempfile.TemporaryDirectory(prefix="voice-changer-") as temp:
            preset = Path(temp) / "voice.vstpreset"
            preset.write_bytes(make_preset(model_path, voice, pitch, formant))
            self.plugin.load_preset(str(preset))
        # Probe before opening microphone. A missing/failed model must not become passthrough.
        signal = (0.04 * np.sin(2 * np.pi * 180 * np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE)).astype("float32")
        result = self.plugin(signal, SAMPLE_RATE, buffer_size=BLOCK, reset=True)
        if not np.isfinite(result).all() or np.max(np.abs(result)) < 1e-7 or np.allclose(signal, result):
            raise RuntimeError("AI 自检未通过：模型可能未加载。已阻止启动麦克风。")
        self.plugin.reset()

    def __call__(self, audio):
        return self.plugin(audio, SAMPLE_RATE, buffer_size=BLOCK, reset=False)
