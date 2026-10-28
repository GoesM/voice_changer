"""Read, record, review, accept. Pending takes never enter the training dataset."""
import tkinter as tk
from tkinter import ttk, messagebox
import wave

import numpy as np
import sounddevice as sd

from . import reading
from .studio import Recorder, analyze_wav


class ReadingGuide:
    def __init__(self, studio):
        self.studio = studio
        self.project = studio.project
        self.segments = reading.script()["segments"]
        self.index = max(0, min(int(reading.state(self.project)["current"]), len(self.segments) - 1))
        self.recorder = None
        self.window = tk.Toplevel(studio.window)
        self.window.title("原创稿件 · 引导朗读")
        self.window.geometry("820x720")
        self.window.minsize(650, 580)
        self.window.transient(studio.window)
        self.window.grab_set()
        body = ttk.Frame(self.window, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="日常中文自然朗读 · 40 段", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="约 4,900 字，估计 15–20 分钟，实际以录音时长为准。保持同一说话人、自然音色和麦克风距离。\n"
                  "每段：阅读 → 开始录音 → 停止 → 试听 → 确认。可跳过，关闭后可继续。", wraplength=760).pack(anchor="w", pady=8)
        devices = studio.app.device_list
        self.mic = tk.StringVar(value=studio.app.input_box.get())
        self.ear = tk.StringVar(value=studio.app.monitor_box.get())
        route = ttk.Frame(body)
        route.pack(fill="x")
        ttk.Label(route, text="麦克风").grid(row=0, column=0)
        self.mic_box = ttk.Combobox(route, textvariable=self.mic, state="readonly", width=55,
            values=[d["name"] for d in devices if d["inputs"] and "cable" not in d["name"].lower()])
        self.mic_box.grid(row=0, column=1, sticky="ew")
        ttk.Label(route, text="试听耳机").grid(row=1, column=0)
        self.ear_box = ttk.Combobox(route, textvariable=self.ear, state="readonly", width=55,
            values=[d["name"] for d in devices if d["outputs"] and "cable" not in d["name"].lower()])
        self.ear_box.grid(row=1, column=1, sticky="ew")
        route.columnconfigure(1, weight=1)
        self.selector = ttk.Combobox(body, state="readonly", values=[s["title"] for s in self.segments])
        self.selector.pack(fill="x", pady=10)
        self.selector.bind("<<ComboboxSelected>>", self.select)
        self.tip = tk.StringVar()
        ttk.Label(body, textvariable=self.tip).pack(anchor="w")
        self.text = tk.Text(body, wrap="word", font=("Microsoft YaHei UI", 16), height=8, padx=12, pady=12)
        self.text.pack(fill="both", expand=True, pady=8)
        self.status = tk.StringVar()
        self.progress = tk.StringVar()
        ttk.Label(body, textvariable=self.status, wraplength=760).pack(anchor="w")
        ttk.Label(body, textvariable=self.progress, wraplength=760).pack(anchor="w", pady=6)
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.controls = []
        for label, command in [("开始 / 重录本段", self.record), ("试听", self.play), ("确认并下一段", self.accept)]:
            button = ttk.Button(row, text=label, command=command)
            button.pack(side="left", padx=3)
            self.controls.append(button)
        ttk.Button(row, text="停止录音 / 试听", command=self.stop).pack(side="left", padx=3)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=8)
        for label, command in [("上一段", lambda: self.move(-1)), ("跳过 / 下一段", lambda: self.move(1))]:
            button = ttk.Button(row, text=label, command=command)
            button.pack(side="left", padx=3)
            self.controls.append(button)
        ttk.Button(row, text="保存进度并返回", command=self.close).pack(side="right")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.render()
        except Exception:
            self.window.destroy()
            studio.window.grab_set()
            raise
        self.timer = self.window.after(200, self.poll)

    @property
    def segment(self):
        return self.segments[self.index]

    def render(self):
        self.selector.current(self.index)
        self.tip.set(self.segment["tip"])
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.segment["text"])
        self.text.configure(state="disabled")
        done = reading.completed(self.project)
        pending = reading.pending_take(self.project, self.segment["id"])
        label = "已确认，可重新录制" if self.segment["id"] in done else "尚未确认"
        if pending:
            q = analyze_wav(pending)
            label += f"；待确认录音 {q['seconds']:.1f} 秒，有效声音约 {q['active_seconds']:.1f} 秒"
        self.status.set(label)
        self.progress.set(f"已确认 {len(done)} / {len(self.segments)} 段。完成段数不等于训练时长；返回素材库查看实际统计。")
        reading.save_position(self.project, self.index)

    def select(self, event=None):
        if self.recorder:
            self.selector.current(self.index)
            return
        sd.stop()
        self.index = self.selector.current()
        self.render()

    def move(self, delta):
        if not self.recorder:
            sd.stop()
            self.index = max(0, min(len(self.segments) - 1, self.index + delta))
            self.render()

    def record(self):
        if self.recorder:
            return
        try:
            device = self.studio.app.find_device(self.mic.get(), "inputs")
            if not device or "cable" in device["name"].lower():
                raise ValueError("请选择实体麦克风。")
            sd.stop()
            self.recorder = Recorder(self.project, device["index"], self.project / ".takes")
            self.recorder.start()
            for button in self.controls:
                button.configure(state="disabled")
            self.selector.configure(state="disabled")
            self.mic_box.configure(state="disabled")
        except Exception as exc:
            self.recorder = None
            messagebox.showerror("录音失败", str(exc), parent=self.window)

    def stop(self):
        sd.stop()
        if not self.recorder:
            return
        recorder, self.recorder = self.recorder, None
        try:
            recorder.stop()
            reading.save_pending(self.project, self.segment["id"], recorder.path)
        except Exception as exc:
            messagebox.showerror("录音未确认", str(exc), parent=self.window)
        for button in self.controls:
            button.configure(state="normal")
        self.selector.configure(state="readonly")
        self.mic_box.configure(state="readonly")
        self.render()

    def play(self):
        if self.recorder:
            return
        try:
            path = reading.pending_take(self.project, self.segment["id"])
            if path is None:
                from .materials import clip_path
                name = reading.state(self.project)["accepted"].get(self.segment["id"])
                path = clip_path(self.project, name) if name else None
            if path is None or not path.is_file():
                raise ValueError("请先录制本段。")
            device = self.studio.app.find_device(self.ear.get(), "outputs")
            if not device or "cable" in device["name"].lower():
                raise ValueError("请选择实体耳机用于试听。")
            with wave.open(str(path), "rb") as audio:
                data = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(-1, audio.getnchannels())
                sd.play(data, audio.getframerate(), device=device["index"])
        except Exception as exc:
            messagebox.showerror("无法试听", str(exc), parent=self.window)

    def accept(self):
        if self.recorder:
            return
        try:
            sd.stop()
            reading.accept_take(self.project, self.segment)
            if self.index == len(self.segments) - 1:
                messagebox.showinfo("本段已确认", "请检查跳过的段落，返回素材库查看实际时长；不足 10 分钟时继续补录。", parent=self.window)
            self.move(1)
        except Exception as exc:
            messagebox.showerror("本段尚未通过", str(exc), parent=self.window)

    def poll(self):
        if self.recorder:
            self.status.set(f"正在录音 {self.recorder.frames / 48000:.1f} 秒；读完本段后点击停止。")
            if self.recorder.error or self.recorder.frames >= 48000 * 180:
                self.stop()
        self.timer = self.window.after(200, self.poll)

    def close(self):
        self.stop()
        reading.save_position(self.project, self.index)
        self.window.after_cancel(self.timer)
        self.window.grab_release()
        self.window.destroy()
        self.studio.guide = None
        self.studio.window.grab_set()
        self.studio.report()
