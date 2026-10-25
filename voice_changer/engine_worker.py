"""Executed only by the managed Applio Python, not imported by the desktop app."""
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import sys


def offline():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    def blocked(*args, **kwargs):
        raise RuntimeError("离线推理缺少本地资源，请先修复训练环境。")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked


def training(project, epochs):
    import core
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("本地训练需要 CUDA NVIDIA 显卡。")
    # Upstream CLI may print failure with exit 0; enforce subprocess exit codes.
    original = core.run_quiet
    def checked(*args, **kwargs):
        result = original(*args, **kwargs)
        result.check_returncode()
        return result
    core.run_quiet = checked
    name = project.name
    cpus = max(1, min(8, (os.cpu_count() or 2) // 2))
    print("阶段 1/4：切分、标准化素材", flush=True)
    core.run_preprocess_script(name, str(project / "recordings"), 40000, cpus, "Automatic", True, 3., .3, "none")
    print("阶段 2/4：提取音高和声音特征", flush=True)
    core.run_extract_script(name, "rmvpe", cpus, 0, 40000, "contentvec")
    print("阶段 3/4：在本机训练音色", flush=True)
    core.run_train_script(name, 10, True, True, epochs, 40000, 2, "0", True, False)
    logs = Path(core.logs_path) / name
    candidates = sorted((p for p in logs.rglob("*.pth") if not p.name.startswith(("G_", "D_"))),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    indices = sorted(logs.glob("*.index"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates or not indices:
        raise RuntimeError("没有找到导出的推理模型与索引。")
    # Locally generated checkpoints only. Never accept arbitrary downloaded pickle files.
    checkpoint = torch.load(candidates[0], map_location="cpu", weights_only=True)
    if not {"weight", "config", "f0", "version"}.issubset(checkpoint):
        raise RuntimeError("导出模型结构不完整。")
    print("阶段 4/4：离线加载与推理自检", flush=True)
    offline()
    import numpy as np
    from rvc.realtime.core import VoiceChanger
    model = VoiceChanger(4800, .04, 1., str(candidates[0]), str(indices[0]),
                         embedder_model="contentvec", silent_threshold=-60, device="cuda")
    model.warmup()
    sample = (.05 * np.sin(np.arange(4800) * 2 * np.pi * 220 / 48000)).astype(np.float32)
    peaks = []
    for _ in range(10):
        converted, _, _ = model.on_request(sample)
        if len(converted) != len(sample) or not np.isfinite(converted).all():
            raise RuntimeError("音色推理自检失败。")
        peaks.append(float(np.max(np.abs(converted))))
    if max(peaks) < 1e-6 or np.allclose(converted, sample):
        raise RuntimeError("音色推理只有静音或未转换信号，未加入可用音色。")
    shutil.copyfile(candidates[0], project / "model.pth")
    shutil.copyfile(indices[0], project / "model.index")
    print("训练完成，音色已通过加载自检。自然度需要试听确认。", flush=True)


def read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.read(size - len(result))
        if not chunk:
            raise EOFError()
        result.extend(chunk)
    return bytes(result)


def realtime(project, mode, pitch):
    import numpy as np
    channel = sys.stdout.buffer
    sys.stdout = sys.stderr  # keep upstream logging away from framed audio
    offline()
    from rvc.realtime.core import VoiceChanger
    block, overlap, context, index = (4800, .02, .5, .3) if mode == "game" else (9600, .04, 2., .75)
    model = VoiceChanger(block, overlap, context, str(project / "model.pth"), str(project / "model.index"),
                         embedder_model="contentvec", silent_threshold=-60, device="cuda")
    model.warmup(f0_up_key=pitch, index_rate=index)
    channel.write(b"READY\n")
    channel.flush()
    while True:
        try:
            raw = read_exact(sys.stdin.buffer, block * 4)
        except EOFError:
            return
        result, _, _ = model.on_request(np.frombuffer(raw, dtype="<f4").copy(), f0_up_key=pitch, index_rate=index)
        result = np.asarray(result, dtype="<f4").reshape(-1)
        if len(result) != block or not np.isfinite(result).all():
            raise RuntimeError("推理返回无效数据，已停止输出。")
        channel.write(result.tobytes())
        channel.flush()


if __name__ == "__main__":
    sys.path.insert(0, os.getcwd())
    if sys.argv[1] == "train":
        training(Path(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1] == "realtime":
        realtime(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]))
