import json
import os
import queue
import threading
import tkinter as tk
import wave
import webbrowser
import numpy as np
import sounddevice as sd
from tkinter import ttk, messagebox, filedialog, simpledialog

from .jobs import Job
from .setup import engine_ready, engine_root, install_engine
from .studio import (new_project, projects_root, dataset_report, import_wav, Recorder, train)
from . import materials


class Studio:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("素材库 · 引导采集 · 本地训练")
        self.window.geometry("800x780")
        self.window.transient(app.root)
        self.window.grab_set()
        self.project = None
        self.recorder = None
        self.job = None
        self.guide = None
        self.events = queue.Queue()
        self.state = tk.StringVar(value="先创建音色项目，再录制或导入素材。")
        canvas = tk.Canvas(self.window, bg="#f4f6fb", highlightthickness=0)
        scroll = ttk.Scrollbar(self.window, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=20)
        item = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        self.window.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        ttk.Label(body, text="录下声音，训练专属音色", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="请使用本人或获得授权的目标声音。安静环境、无伴奏，累计 10–20 分钟。\n"
                  "录制的是希望转换成的声音；男声素材不会自动训练出女声音色。", wraplength=700).pack(anchor="w", pady=8)
        self.consent = tk.BooleanVar()
        ttk.Checkbutton(body, text="我拥有素材使用授权，同意只在这台电脑保存和训练", variable=self.consent).pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=10)
        self.buttons = []
        for text, command in [("新建素材集", self.create), ("打开旧项目目录", self.choose), ("安装 / 修复训练环境", self.install)]:
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        ttk.Label(body, text="首次安装需联网下载数 GB，建议至少 15 GB 空间；训练需要 NVIDIA CUDA 显卡。\n"
                  "训练耗时取决于素材和显卡；训练期间建议停止游戏。", wraplength=700).pack(anchor="w")
        ttk.Button(body, text="训练教程与组件条款 ↗", command=lambda: webbrowser.open(
            "https://github.com/GoesM/voice_changer/blob/main/docs/user/CUSTOM_VOICE.md")).pack(anchor="w", pady=5)
        ttk.Label(body, text="每个素材集只收集同一个说话人的声音；不包含明星录音。选择已有素材集：").pack(anchor="w", pady=(10, 2))
        self.collection_box = ttk.Combobox(body, state="readonly")
        self.collection_box.pack(fill="x")
        self.collection_box.bind("<<ComboboxSelected>>", self.select_collection)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=5)
        for text, command in [("重命名素材集", self.rename_collection), ("复制为新训练项目", self.copy_collection), ("原创稿件 · 引导朗读", self.open_guide)]:
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        self.project_label = ttk.Label(body, text="尚未选择素材集")
        self.project_label.pack(anchor="w", pady=12)
        row = ttk.Frame(body)
        row.pack(fill="x")
        for text, command in [("开始录音", self.record), ("停止并保存", self.stop_record), ("导入 WAV 素材", self.import_audio), ("检查素材", self.report)]:
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        self.quality = tk.StringVar(value="素材仅保存在本机；云训练：功能仍在开发中....")
        ttk.Label(body, textvariable=self.quality, wraplength=700).pack(anchor="w", pady=10)
        self.clips = []
        self.clip_list = tk.Listbox(body, height=4)
        self.clip_list.pack(fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=5)
        for text, command in [("试听所选素材（耳机）", self.play), ("停止试听", sd.stop), ("重命名素材", self.rename_clip), ("移除所选素材", self.delete)]:
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text="训练轮数（默认 100）").pack(side="left")
        self.epochs = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=10, to=1000, textvariable=self.epochs, width=7).pack(side="left", padx=10)
        button = ttk.Button(row, text="开始本地训练", command=self.training)
        button.pack(side="left")
        self.buttons.append(button)
        ttk.Button(row, text="取消当前任务", command=self.cancel).pack(side="left", padx=5)
        ttk.Label(body, textvariable=self.state, wraplength=700).pack(anchor="w", pady=10)
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x")
        ttk.Button(body, text="打开项目 / 日志目录", command=self.open_folder).pack(anchor="w", pady=12)
        ttk.Label(body, text="云训练：功能仍在开发中.... 本版没有上传入口。\n"
                  "取消保留素材与训练检查点，再次开始会复用同一项目。\n"
                  "音量检查无法识别背景人声、混响或发音问题，请自行试听素材。", wraplength=700).pack(anchor="w")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_collections()
        self.timer = self.window.after(200, self.poll)

    def refresh_collections(self):
        self.collection_map = dict(materials.collections())
        self.collection_box["values"] = list(self.collection_map)
        self.collection_box.set(next((name for name, path in self.collection_map.items() if path == self.project), ""))

    def select_collection(self, event=None):
        if not self.allowed(False):
            self.refresh_collections()
            return
        sd.stop()
        self.project = self.collection_map.get(self.collection_box.get())
        self.report()

    def rename_collection(self):
        if not self.allowed():
            return
        name = simpledialog.askstring("重命名素材集", "同一说话人的素材集名称：", parent=self.window)
        if name:
            try:
                materials.rename_collection(self.project, name)
                self.report()
                self.app.refresh_voices()
            except Exception as exc:
                messagebox.showerror("无法重命名", str(exc), parent=self.window)

    def copy_collection(self):
        if not self.allowed():
            return
        name = simpledialog.askstring("复制素材集", "新项目名称（只复制已确认素材，不复制模型或待确认录音）：", parent=self.window)
        if name:
            source = self.project
            def work(progress, job):
                job.check()
                progress("正在复制素材…")
                target = materials.copy_collection(source, name, job.check)
                self.events.put(("collection", target))
            self.run(work)

    def rename_clip(self):
        if not self.allowed() or not self.clip_list.curselection():
            return
        clip = self.clips[self.clip_list.curselection()[0]]
        label = simpledialog.askstring("素材名称", "给这段素材起个容易辨认的名字：", parent=self.window)
        if label:
            try:
                materials.rename_clip(self.project, clip.name, label)
                self.report()
            except Exception as exc:
                messagebox.showerror("无法重命名", str(exc), parent=self.window)

    def open_guide(self):
        if not self.allowed():
            return
        from .reading_ui import ReadingGuide
        try:
            sd.stop()
            self.guide = ReadingGuide(self)
        except Exception as exc:
            messagebox.showerror("无法打开朗读稿", str(exc), parent=self.window)

    def allowed(self, project=True):
        if self.job or self.recorder or self.guide:
            messagebox.showinfo("任务进行中", "请先停止录音或等待当前任务结束。", parent=self.window)
            return False
        if project and not self.project:
            messagebox.showinfo("选择项目", "请先创建或选择音色项目。", parent=self.window)
            return False
        return True

    def create(self):
        if not self.allowed(False):
            return
        if not self.consent.get():
            messagebox.showinfo("素材授权", "请先确认你拥有目标声音素材的使用授权。", parent=self.window)
            return
        name = simpledialog.askstring("音色名称", "给新音色起个名字：", parent=self.window)
        if name:
            try:
                self.project = new_project(name)
                self.report()
            except Exception as exc:
                messagebox.showerror("无法创建音色", str(exc), parent=self.window)

    def choose(self):
        if not self.allowed(False):
            return
        path = filedialog.askdirectory(initialdir=projects_root(), title="选择本软件创建的 voice_ 音色项目", parent=self.window)
        if path:
            from pathlib import Path
            candidate = Path(path).resolve()
            if candidate.parent != projects_root().resolve() or not (candidate / "project.json").is_file():
                messagebox.showerror("无法打开", "请选择本软件创建的本地项目目录。", parent=self.window)
                return
            self.project = candidate
            self.report()

    def report(self):
        if not self.allowed():
            return
        try:
            meta = json.loads((self.project / "project.json").read_text(encoding="utf-8"))
            self.refresh_collections()
            self.project_label.configure(text=f"当前音色：{meta['name']} · 状态：{meta['state']}")
            entries = materials.list_clips(self.project)
            self.clips = [entry["path"] for entry in entries]
            self.clip_list.delete(0, "end")
            for entry in entries:
                q = entry["quality"]
                self.clip_list.insert("end", f"{entry['label']} · {q['seconds']:.1f} 秒 · {entry['source']}"
                                      + (" · 建议重录" if q['clipping'] > .005 else ""))
            report = dataset_report(self.project)
            self.quality.set(f"{report['files']} 段 · 总时长 {report['seconds'] / 60:.1f} 分钟 · "
                f"有效声音约 {report['active_seconds'] / 60:.1f} 分钟 · 削波素材 {report['clipped_files']} 段\n"
                + ("达到训练门槛，可开始本地训练。" if report['ready'] else "需总时长 ≥10 分钟、有效声音 ≥5 分钟且无明显削波。"))
        except Exception as exc:
            messagebox.showerror("素材检查", str(exc), parent=self.window)

    def record(self):
        if not self.allowed():
            return
        try:
            device = self.app.find_device(self.app.input_box.get(), "inputs")
            if not device or "cable" in device["name"].lower():
                raise ValueError("请先在主界面选择实体麦克风。")
            sd.stop()
            self.recorder = Recorder(self.project, device['index'])
            self.recorder.start()
            self.state.set("正在录音，请自然朗读；停止后保存。每段最多 20 分钟。")
        except Exception as exc:
            self.recorder = None
            messagebox.showerror("录音失败", str(exc), parent=self.window)

    def stop_record(self):
        if not self.recorder:
            return
        recorder, self.recorder = self.recorder, None
        try:
            recorder.stop()
            materials.register_clip(self.project, recorder.path)
            self.state.set("录音已保存在本机。")
        except Exception as exc:
            messagebox.showerror("录音", str(exc), parent=self.window)
        self.report()

    def import_audio(self):
        if not self.allowed():
            return
        paths = filedialog.askopenfilenames(filetypes=[("16 位 PCM WAV", "*.wav")], parent=self.window)
        try:
            for path in paths:
                from pathlib import Path
                target = import_wav(self.project, path)
                materials.register_clip(self.project, target, Path(path).stem, "用户导入")
        except Exception as exc:
            messagebox.showerror("素材导入", str(exc), parent=self.window)
        self.report()

    def run(self, function):
        sd.stop()
        self.job = Job()
        for button in self.buttons:
            button.configure(state="disabled")
        self.progress.start()
        def work():
            try:
                function(lambda msg: self.events.put(("progress", msg)), self.job)
                self.events.put(("done", "操作完成。"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def play(self):
        if not self.allowed() or not self.clip_list.curselection():
            return
        try:
            device = self.app.find_device(self.app.monitor_box.get(), "outputs")
            if not device or "cable" in device["name"].lower():
                raise ValueError("请关闭音色窗口，在主界面‘耳机监听’选择实体耳机后再试听。")
            with wave.open(str(self.clips[self.clip_list.curselection()[0]]), "rb") as audio:
                data = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(-1, audio.getnchannels())
                sd.play(data, audio.getframerate(), device=device['index'])
        except Exception as exc:
            messagebox.showerror("无法试听", str(exc), parent=self.window)

    def delete(self):
        if not self.allowed() or not self.clip_list.curselection():
            return
        if messagebox.askyesno("移除素材", "从训练素材中移除所选录音？原文件会保留在项目的 .trash 文件夹。", parent=self.window):
            sd.stop()
            try:
                materials.remove_clip(self.project, self.clips[self.clip_list.curselection()[0]].name)
                self.report()
            except Exception as exc:
                messagebox.showerror("无法移除", str(exc), parent=self.window)

    def install(self):
        if self.allowed(False) and messagebox.askokcancel("安装本地环境", "将联网下载 Applio、Python、CUDA 依赖和基础模型，可能需要数 GB。\n"
                "只在应用数据目录安装，不上传素材。是否开始？", parent=self.window):
            self.run(install_engine)

    def training(self):
        if self.allowed():
            try:
                epochs = self.epochs.get()
                if not 10 <= epochs <= 1000:
                    raise ValueError("轮数必须介于 10–1000。")
                self.run(lambda progress, job: train(self.project, epochs, progress, job))
            except Exception as exc:
                messagebox.showerror("无法训练", str(exc), parent=self.window)

    def cancel(self):
        if self.job:
            self.state.set("正在取消，请等待子进程退出…")
            threading.Thread(target=self.job.cancel, daemon=True).start()

    def open_folder(self):
        folder = self.project or engine_root()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def poll(self):
        try:
            while True:
                kind, text = self.events.get_nowait()
                if kind == "collection":
                    self.project = text
                    continue
                self.state.set(text)
                if kind != "progress":
                    self.job = None
                    self.progress.stop()
                    for button in self.buttons:
                        button.configure(state="normal")
                    if self.project:
                        self.report()
                    self.app.refresh_voices()
        except queue.Empty:
            pass
        if self.recorder:
            self.state.set(f"正在录音：{self.recorder.frames / 48000:.0f} 秒；目标累计 10–20 分钟。")
            if self.recorder.error or self.recorder.frames >= 48000 * 1200:
                self.stop_record()
        self.timer = self.window.after(200, self.poll)

    def close(self):
        if self.guide:
            self.guide.close()
        if self.job:
            messagebox.showinfo("任务进行中", "请先取消任务并等待退出，再关闭窗口。", parent=self.window)
            return
        if self.recorder:
            self.stop_record()
        sd.stop()
        self.window.after_cancel(self.timer)
        self.window.grab_release()
        self.window.destroy()
