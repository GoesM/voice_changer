"""Private local recording projects and training lifecycle."""
import json
import os
import queue
import shutil
import threading
import uuid
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from .config import data_dir
from .setup import engine_paths, engine_ready


def projects_root():
    root = data_dir() / "voices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def new_project(name):
    name = name.strip()
    if not name or len(name) > 60:
        raise ValueError("请填写 1–60 字的音色名称。")
    root = projects_root() / ("voice_" + uuid.uuid4().hex)
    (root / "recordings").mkdir(parents=True)
    write_json(root / "project.json", {"name": name, "state": "collecting", "consent": True})
    return root


def analyze_wav(path):
    with wave.open(str(path), "rb") as audio:
        rate, channels = audio.getframerate(), audio.getnchannels()
        if audio.getsampwidth() != 2 or channels not in (1, 2) or not 16000 <= rate <= 96000:
            raise ValueError("请使用 16 位 PCM WAV、单声道或双声道、16–96 kHz 的录音。")
        count = clipped = active = 0
        while raw := audio.readframes(rate // 10):
            samples = np.frombuffer(raw, dtype="<i2").reshape(-1, channels).astype(np.float32) / 32768
            count += len(samples)
            clipped += int(np.count_nonzero(np.max(np.abs(samples), axis=1) >= .999))
            if np.sqrt(np.mean(samples ** 2)) > .01:
                active += len(samples)
        return {"seconds": count / rate, "active_seconds": active / rate,
                "clipping": clipped / max(count, 1)}


def dataset_report(project):
    items = [analyze_wav(p) for p in sorted((project / "recordings").glob("*.wav"))]
    seconds = sum(x["seconds"] for x in items)
    active = sum(x["active_seconds"] for x in items)
    bad = sum(x["clipping"] > .005 for x in items)
    return {"files": len(items), "seconds": seconds, "active_seconds": active,
            "clipped_files": bad, "ready": seconds >= 600 and active >= 300 and bad == 0}


def import_wav(project, path):
    report = analyze_wav(path)
    if report["seconds"] < 3 or report["seconds"] > 1800:
        raise ValueError("单个素材请控制在 3 秒至 30 分钟。")
    if report["clipping"] > .005:
        raise ValueError("素材存在明显削波，请降低麦克风音量重新录制。")
    target = project / "recordings" / (uuid.uuid4().hex + ".wav")
    shutil.copyfile(path, target)
    return target


class Recorder:
    def __init__(self, project, device):
        self.path = project / "recordings" / (uuid.uuid4().hex + ".wav")
        self.queue = queue.Queue(maxsize=100)
        self.finished = threading.Event()
        self.error = ""
        self.frames = 0
        self.stream = sd.InputStream(device=device, samplerate=48000, channels=1,
                                     dtype="int16", blocksize=4800, callback=self.callback)
        self.thread = threading.Thread(target=self.write, daemon=True)

    def callback(self, audio, frames, timing, status):
        if status:
            self.error = "录音设备出现丢帧，请重新录制此段。"
        if self.frames >= 48000 * 1200:
            return
        try:
            self.queue.put_nowait(audio.copy().tobytes())
            self.frames += frames
        except queue.Full:
            self.error = "磁盘写入过慢，请重新录制此段。"

    def write(self):
        try:
            with wave.open(str(self.path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                while not self.finished.is_set() or not self.queue.empty():
                    try:
                        audio.writeframes(self.queue.get(timeout=.1))
                    except queue.Empty:
                        pass
        except Exception as exc:
            self.error = str(exc)

    def start(self):
        self.thread.start()
        try:
            self.stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.stream.close()
        self.finished.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("录音文件仍在写入，请稍后再试。")
        if self.error or self.frames < 48000 * 3:
            self.path.unlink(missing_ok=True)
            raise RuntimeError(self.error or "录音不足 3 秒，未保存。")
        return analyze_wav(self.path)


def train(project, epochs, progress, job):
    if not engine_ready():
        raise RuntimeError("请先安装本地训练环境。")
    if shutil.disk_usage(project).free < 5 * 1024**3:
        raise RuntimeError("训练前请至少预留 5 GB 可用空间，用于切片、特征和检查点。")
    report = dataset_report(project)
    if not report["ready"]:
        raise ValueError("需要至少 10 分钟素材，其中有效声音至少 5 分钟，且没有明显削波。")
    if not 10 <= epochs <= 1000:
        raise ValueError("训练轮数必须介于 10–1000。")
    python, source = engine_paths()
    metadata = json.loads((project / "project.json").read_text(encoding="utf-8"))
    if metadata.get("state") == "ready":
        raise ValueError("此音色已经完成训练。请新建项目训练新版本，保留当前可用音色。")
    metadata.update(state="training", epochs=epochs, quality=report)
    write_json(project / "project.json", metadata)
    try:
        job.run([python, Path(__file__).with_name("engine_worker.py"), "train", str(project), str(epochs)],
                source, progress, project / "training.log", dict(os.environ, PYTHONUTF8="1"))
        job.check()
        if not (project / "model.pth").is_file() or not (project / "model.index").is_file():
            raise RuntimeError("训练未生成完整的音色文件，未加入可用音色列表。")
        metadata["state"] = "ready"
    except Exception as exc:
        metadata.update(state="interrupted" if job.cancelled.is_set() else "failed", error=str(exc))
        raise
    finally:
        write_json(project / "project.json", metadata)


def list_voices():
    result = []
    for path in sorted(projects_root().glob("*/project.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if meta.get("state") == "ready" and (path.parent / "model.pth").is_file() and (path.parent / "model.index").is_file():
                result.append((meta["name"] + " · " + path.parent.name[-6:], path.parent))
        except (ValueError, OSError, KeyError):
            continue
    return result
