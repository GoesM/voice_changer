"""Bounded real-time audio transport. Inference never runs on the audio callbacks."""
import queue
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48000
BLOCK = 960  # 20 ms; inference latency is additional, never advertised as total latency.


def offer_latest(q, value):
    """Drop oldest data under overload rather than accumulate unbounded delay."""
    dropped = False
    try:
        q.put_nowait(value)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(value)
        except queue.Full:
            pass
        dropped = True
    return dropped


def devices():
    hosts = sd.query_hostapis()
    result = []
    for index, item in enumerate(sd.query_devices()):
        # WASAPI avoids duplicate MME/DirectSound entries and allows distinct devices.
        host = hosts[item["hostapi"]]["name"]
        if "WASAPI" in host:
            result.append({"index": index, "name": item["name"], "host": host,
                           "inputs": item["max_input_channels"],
                           "outputs": item["max_output_channels"]})
    return result


def validate_route(input_device, output_device, monitor_device=None):
    if not input_device or not output_device:
        raise ValueError("请选择实体麦克风和 CABLE Input 输出。")
    if "cable" in input_device["name"].lower():
        raise ValueError("输入不能选择虚拟线缆，请选择实体麦克风，避免音频回路。")
    if "cable input" not in output_device["name"].lower():
        raise ValueError("变声输出请选择 CABLE Input；耳机请放在监听选项。")
    if monitor_device and "cable" in monitor_device["name"].lower():
        raise ValueError("监听请选择实体耳机，不能选择虚拟线缆。")


class AudioEngine:
    def __init__(self, processor, block=BLOCK):
        self.processor = processor
        self.block = block
        self.input_max_age = max(.10, 2 * block / SAMPLE_RATE)
        self.output_max_age = max(.15, 3 * block / SAMPLE_RATE)
        self.inputs = queue.Queue(maxsize=3)
        self.outputs = queue.Queue(maxsize=3)
        self.monitor = queue.Queue(maxsize=3)
        self.running = threading.Event()
        self.muted = False
        self.error = ""
        self.drops = 0
        self.underflows = 0
        self.level_in = 0.0
        self.level_out = 0.0
        self.times = deque(maxlen=500)
        self.streams = []
        self.thread = None
        self.generation = 0

    def set_muted(self, muted):
        self.muted = bool(muted)
        self.generation += 1
        for q in (self.inputs, self.outputs, self.monitor):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def _input(self, data, frames, timing, status):
        if status:
            self.drops += 1
        if self.running.is_set():
            self.level_in = float(np.max(np.abs(data)))
            if not self.muted:
                self.drops += int(offer_latest(self.inputs, (time.monotonic(), self.generation, data[:, 0].copy())))

    def _output(self, q, data):
        data.fill(0)
        if not self.running.is_set() or self.muted or self.error:
            return
        try:
            stamp, generation, converted = q.get_nowait()
            if generation != self.generation:
                return
            if time.monotonic() - stamp > self.output_max_age:
                self.drops += 1
                return
            data[:] = converted[:, None]
        except queue.Empty:
            self.underflows += 1

    def _worker(self):
        try:
            while self.running.is_set():
                try:
                    stamp, generation, data = self.inputs.get(timeout=0.1)
                except queue.Empty:
                    continue
                if time.monotonic() - stamp > self.input_max_age:
                    self.drops += 1
                    continue
                start = time.perf_counter()
                converted = np.asarray(self.processor(data), dtype=np.float32).reshape(-1)
                self.times.append((time.perf_counter() - start) * 1000)
                if len(converted) != len(data) or not np.isfinite(converted).all():
                    raise RuntimeError("AI 引擎返回无效音频，已静音。")
                converted = np.clip(converted, -0.98, 0.98)
                if self.muted or generation != self.generation:
                    converted.fill(0)
                self.level_out = float(np.max(np.abs(converted)))
                self.drops += int(offer_latest(self.outputs, (stamp, generation, converted)))
                offer_latest(self.monitor, (stamp, generation, converted.copy()))
        except Exception as exc:
            self.error = str(exc)
            self.running.clear()

    def start(self, input_device, output_device, monitor_device=None):
        validate_route(input_device, output_device, monitor_device)
        self.running.set()
        try:
            self.streams.append(sd.InputStream(
                device=input_device["index"], samplerate=SAMPLE_RATE, blocksize=self.block,
                channels=1, dtype="float32", callback=self._input))
            for device, q in [(output_device, self.outputs), (monitor_device, self.monitor)]:
                if device:
                    self.streams.append(sd.OutputStream(
                        device=device["index"], samplerate=SAMPLE_RATE, blocksize=self.block,
                        channels=min(2, device["outputs"]), dtype="float32",
                        callback=lambda out, frames, timing, status, buffer=q: self._output(buffer, out)))
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            for stream in self.streams:
                stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.running.clear()
        for stream in self.streams:
            try:
                stream.abort()
            finally:
                stream.close()
        self.streams.clear()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError("AI 引擎未及时停止，请关闭程序后重开。")
        if hasattr(self.processor, "close"):
            self.processor.close()

    def stats(self):
        return {"processing_p95_ms": round(float(np.percentile(self.times, 95)), 2) if self.times else 0,
                "dropped_blocks": self.drops, "output_underflows": self.underflows,
                "input_level": self.level_in, "output_level": self.level_out,
                "error": self.error}
