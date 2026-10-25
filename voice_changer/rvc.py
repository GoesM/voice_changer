"""Offline RVC inference in the managed environment, isolated from the UI runtime."""
import os
from pathlib import Path
import queue
import subprocess
import threading

import numpy as np

from .setup import engine_paths, engine_ready


class RvcProcessor:
    def __init__(self, project, mode="game", pitch=8):
        if not engine_ready():
            raise RuntimeError("请先安装或修复本地训练环境。")
        self.block = 4800 if mode == "game" else 9600
        self.responses = queue.Queue(maxsize=2)
        self.process = None
        self.log = (project / "inference.log").open("ab")
        python, source = engine_paths()
        try:
            self.process = subprocess.Popen([str(python), str(Path(__file__).with_name("engine_worker.py")),
                "realtime", str(project), mode, str(pitch)], cwd=source,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                env=dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1"),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            try:
                ready = self.responses.get(timeout=180)
            except queue.Empty:
                raise RuntimeError("自定义音色加载超过 3 分钟，已停止。请检查显存和 inference.log。") from None
            if ready != b"READY\n":
                raise RuntimeError("自定义音色未能加载，请查看音色目录的 inference.log。")
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            ready = self.process.stdout.readline(256)
            self.responses.put(ready, timeout=1)
            if ready != b"READY\n":
                return
            while True:
                raw = bytearray()
                while len(raw) < self.block * 4:
                    chunk = self.process.stdout.read(self.block * 4 - len(raw))
                    if not chunk:
                        raise EOFError("本地 AI 进程已退出。")
                    raw.extend(chunk)
                self.responses.put(bytes(raw), timeout=1)
        except Exception as exc:
            try:
                self.responses.put(exc, timeout=1)
            except queue.Full:
                pass

    def __call__(self, data):
        if self.process.poll() is not None:
            raise RuntimeError("本地 AI 进程已退出，已静音。")
        if len(data) != self.block:
            raise ValueError("音频块长度与所选模式不匹配。")
        self.process.stdin.write(np.asarray(data, dtype="<f4").tobytes())
        self.process.stdin.flush()
        try:
            result = self.responses.get(timeout=2)
        except queue.Empty:
            raise RuntimeError("AI 推理超时，已停止输出。") from None
        if isinstance(result, Exception):
            raise result
        return np.frombuffer(result, dtype="<f4").copy()

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self.log.close()
