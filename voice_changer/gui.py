import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

from . import __version__
from .assets import TERMS_URL, PLUGIN_URL, CABLE_URL, asset_paths, install_assets
from .audio import AudioEngine, devices
from .beatrice import BeatriceProcessor
from .config import load_settings, save_settings

TUTORIAL = "https://github.com/GoesM/voice_changer/blob/main/docs/user/QUICKSTART.md"


class Application:
    def __init__(self, root):
        self.root = root
        root.title(f"Voice Changer  ·  离线 AI 变声  {__version__}")
        root.geometry("900x760")
        root.minsize(800, 710)
        root.configure(bg="#f4f6fb")
        self.engine = None
        self.busy = False
        self.loading = False
        self.studio = None
        self.events = queue.Queue()
        self.settings = load_settings()
        self.device_list = []
        self.status = tk.StringVar(value="尚未启动 · 麦克风未采集")
        self.health = tk.StringVar(value="完成首次配置后，声音处理可完全离线运行。")
        self.pitch = tk.DoubleVar(value=float(self.settings.get("pitch", 8)))
        self.formant = tk.DoubleVar(value=float(self.settings.get("formant", 0)))
        self.voice = tk.StringVar(value=self.settings.get("voice", "自然女声 · つくよみちゃん Corpus"))
        self.mode = tk.StringVar(value=self.settings.get("mode", "游戏低延迟"))
        self.custom_voices = {}
        self.mute = tk.BooleanVar(value=False)
        self.agree = tk.BooleanVar(value=False)
        self.plugin_path = self.settings.get("plugin", "")
        self.model_path = self.settings.get("model", "")
        p, m = asset_paths()
        if not self.plugin_path and p.exists():
            self.plugin_path, self.model_path = str(p), str(m)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6fb")
        style.configure("TLabel", background="#f4f6fb", foreground="#202b46", font=("Microsoft YaHei UI", 10))
        style.configure("TLabelframe", background="#f4f6fb")
        style.configure("TLabelframe.Label", background="#f4f6fb", foreground="#344565", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 7))
        style.configure("Accent.TButton", background="#3459d4", foreground="white")
        style.configure("TCheckbutton", background="#f4f6fb", font=("Microsoft YaHei UI", 9))
        viewport = ttk.Frame(root)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, bg="#f4f6fb", highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=24)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        root.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        ttk.Label(body, text="让声音，换一种表达。", font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w")
        ttk.Label(body, text="本地 AI 男声 → 女声    /    Windows 11    /    首次配置后离线使用").pack(anchor="w", pady=(6, 14))
        setup = ttk.LabelFrame(body, text="01  首次准备", padding=12)
        setup.pack(fill="x", pady=5)
        links = ttk.Frame(setup)
        links.pack(fill="x")
        for label, url in [("使用教程 ↗", TUTORIAL), ("虚拟麦克风驱动 ↗", CABLE_URL),
                           ("模型使用条款 ↗", TERMS_URL), ("AI 插件官网 ↗", PLUGIN_URL)]:
            ttk.Button(links, text=label, command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=(0, 5))
        ttk.Checkbutton(setup, text="我已阅读并接受官方插件、模型及相应音色的使用条款", variable=self.agree).pack(anchor="w", pady=6)
        row = ttk.Frame(setup)
        row.pack(fill="x")
        self.download_button = ttk.Button(row, text="下载并配置 AI（约 58 MB）", command=self.download)
        self.download_button.pack(side="left")
        ttk.Button(row, text="选择已有插件与模型…", command=self.select_assets).pack(side="left", padx=8)
        ttk.Button(row, text="安装虚拟麦克风…", command=self.install_driver).pack(side="left")
        self.asset_label = ttk.Label(setup, text="")
        self.asset_label.pack(anchor="w", pady=(6, 0))
        route = ttk.LabelFrame(body, text="02  声音路由", padding=12)
        route.pack(fill="x", pady=7)
        self.input_box = self.route_row(route, "实体麦克风", 0)
        self.output_box = self.route_row(route, "变声输出", 1)
        self.monitor_box = self.route_row(route, "耳机监听", 2)
        ttk.Button(route, text="刷新设备", command=self.refresh).grid(row=0, column=2, padx=8)
        ttk.Button(route, text="系统声音设置", command=self.sound_settings).grid(row=1, column=2, padx=8)
        ttk.Label(route, text="本软件输出选 CABLE Input；腾讯会议 / 游戏麦克风选 CABLE Output。",
                  font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        route.columnconfigure(1, weight=1)
        tone = ttk.LabelFrame(body, text="03  音色调节（停止后修改，启动时生效）", padding=12)
        tone.pack(fill="x", pady=7)
        self.voice_box = ttk.Combobox(tone, textvariable=self.voice, state="readonly", width=45)
        self.voice_box.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(tone, text="素材库 / 朗读采集 / 训练", command=self.open_studio).grid(row=0, column=2, padx=8)
        ttk.Label(tone, text="音调（半音，建议 +6 至 +12）").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Spinbox(tone, from_=-24, to=24, increment=0.5, textvariable=self.pitch, width=9).grid(row=1, column=1, sticky="w")
        ttk.Label(tone, text="共振峰（建议先保持 0）").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(tone, from_=-2, to=2, increment=0.25, textvariable=self.formant, width=9).grid(row=2, column=1, sticky="w")
        ttk.Label(tone, text="自定义音色模式").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Combobox(tone, textvariable=self.mode, state="readonly", width=18,
                     values=["游戏低延迟", "会议高音质"]).grid(row=3, column=1, sticky="w")
        ttk.Label(tone, text="RVC 模式调整上下文和音色检索；实际延迟依显卡而定。\n"
                  "官方音色使用固定低延迟引擎。自定义音色暂不使用共振峰调节。",
                  font=("Microsoft YaHei UI", 9)).grid(row=4, column=0, columnspan=3, sticky="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=12)
        self.start_button = ttk.Button(actions, text="开始 AI 变声", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(actions, text="停止", command=self.stop).pack(side="left", padx=8)
        ttk.Checkbutton(actions, text="静音", variable=self.mute, command=self.set_mute).pack(side="left", padx=8)
        ttk.Button(actions, text="导出诊断…", command=self.diagnostics).pack(side="right")
        ttk.Label(body, textvariable=self.status, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(body, textvariable=self.health, wraplength=830).pack(anchor="w", pady=6)
        ttk.Label(body, text="预览版 · 故障时停止输出，不自动切回原声。目标应用兼容性仍需实机验证。",
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", side="bottom")
        self.refresh()
        self.refresh_voices()
        self.update_assets()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(200, self.poll)

    def route_row(self, frame, label, row):
        ttk.Label(frame, text=label, width=12).grid(row=row, column=0, sticky="w", pady=4)
        box = ttk.Combobox(frame, state="readonly", width=55)
        box.grid(row=row, column=1, sticky="ew", pady=4)
        return box

    def refresh(self):
        if self.engine or self.busy:
            return
        try:
            self.device_list = devices()
            inputs = [d["name"] for d in self.device_list if d["inputs"] and "cable" not in d["name"].lower()]
            outputs = [d["name"] for d in self.device_list if d["outputs"]]
            cable = [n for n in outputs if "cable input" in n.lower()]
            monitors = ["关闭监听"] + [n for n in outputs if "cable" not in n.lower()]
            for box, values, key in [(self.input_box, inputs, "input"), (self.output_box, cable, "output"),
                                     (self.monitor_box, monitors, "monitor")]:
                box["values"] = values
                saved = self.settings.get(key)
                box.set(saved if saved in values else (values[0] if values else ""))
            if not cable:
                self.health.set("未检测到虚拟麦克风。请点击‘安装虚拟麦克风’，完成安装并重启后重新打开本软件。")
            else:
                self.health.set("✓ 虚拟麦克风已检测到。应用麦克风请选择 CABLE Output；先用耳机监听确认变声。")
        except Exception as exc:
            self.health.set(f"设备枚举失败：{exc}")

    def update_assets(self):
        ready = bool(self.plugin_path and self.model_path and Path(self.plugin_path).exists() and Path(self.model_path).exists())
        self.asset_label.configure(text="✓ AI 文件已配置；启动前还会进行模型自检" if ready else "尚未配置 AI 插件和模型")

    def select_assets(self):
        if self.engine or self.busy:
            return
        plugin = filedialog.askdirectory(title="选择 beatrice_2.0.0-rc.3.vst3 文件夹")
        if not plugin:
            return
        model = filedialog.askopenfilename(title="选择官方模型 1 的 .toml 文件", filetypes=[("Beatrice model", "*.toml")])
        if model:
            self.plugin_path, self.model_path = plugin, model
            self.persist()
            self.update_assets()

    def persist(self):
        self.settings = {**self.settings, "plugin": self.plugin_path, "model": self.model_path,
                         "input": self.input_box.get(), "output": self.output_box.get(),
                         "monitor": self.monitor_box.get(), "voice": self.voice.get(),
                         "pitch": self.pitch.get(), "formant": self.formant.get(), "mode": self.mode.get()}
        save_settings(self.settings)

    def refresh_voices(self):
        from .studio import list_voices
        self.custom_voices = dict(list_voices())
        self.voice_box["values"] = ["自然女声 · つくよみちゃん Corpus", "明亮女声 · つくよみちゃん UTAU"] + list(self.custom_voices)
        if self.voice.get() not in self.voice_box["values"]:
            self.voice.set("自然女声 · つくよみちゃん Corpus")

    def open_studio(self):
        if self.engine or self.busy:
            messagebox.showinfo("请先停止变声", "训练和录音需要独占资源，请先停止当前任务。")
            return
        from .studio_ui import Studio
        if self.studio and self.studio.window.winfo_exists():
            self.studio.window.lift()
            return
        self.studio = Studio(self)

    def install_driver(self):
        if self.busy or self.engine:
            return
        if not messagebox.askokcancel("安装虚拟麦克风", "将从 VB-Audio 官网下载并校验驱动，随后打开官方安装器。\n"
                "请阅读安装器条款，点击 Install Driver，并按提示重启电脑。\nWindows 会要求管理员授权。是否继续？"):
            return
        self.busy = True
        def work():
            from .setup import prepare_driver
            from .jobs import Job
            try:
                installer = prepare_driver(lambda msg: self.events.put(("progress", msg)), Job())
                self.events.put(("driver", installer))
            except Exception as exc:
                self.events.put(("failed", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def download(self):
        if self.busy or self.engine:
            return
        if not self.agree.get():
            messagebox.showinfo("首次配置", "请先阅读官方条款并勾选同意。模型不随本程序再分发。")
            return
        self.busy = True
        self.download_button.configure(state="disabled")
        self.status.set("正在准备 AI 文件…")
        def work():
            try:
                result = install_assets(lambda msg: self.events.put(("progress", msg)))
                self.events.put(("installed", result))
            except Exception as exc:
                self.events.put(("failed", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def find_device(self, name, direction):
        matches = [d for d in self.device_list if d["name"] == name and d[direction]]
        if len(matches) > 1:
            raise ValueError("检测到同名设备，请在 Windows 中重命名后重新打开程序。")
        return matches[0] if matches else None

    def start(self):
        if self.busy or self.engine:
            return
        try:
            from .audio import validate_route
            mic = self.find_device(self.input_box.get(), "inputs")
            out = self.find_device(self.output_box.get(), "outputs")
            monitor = self.find_device(self.monitor_box.get(), "outputs")
            validate_route(mic, out, monitor)
            self.persist()
            self.status.set("加载本地模型并自检…")
            self.root.update_idletasks()
            self.busy = self.loading = True
            self.start_button.configure(state="disabled")
            project = self.custom_voices.get(self.voice.get())
            mode = "game" if self.mode.get() == "游戏低延迟" else "meeting"
            pitch, formant = self.pitch.get(), self.formant.get()
            speaker = 1 if "Corpus" in self.voice.get() else 0
            def work():
                try:
                    if project:
                        from .rvc import RvcProcessor
                        processor = RvcProcessor(project, mode, pitch)
                    else:
                        processor = BeatriceProcessor(self.plugin_path, self.model_path, speaker, pitch, formant)
                    self.events.put(("loaded", (processor, mic, out, monitor)))
                except Exception as exc:
                    self.events.put(("load_failed", str(exc)))
            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            self.stop()
            self.status.set("启动失败 · 未输出原声")
            messagebox.showerror("无法启动", str(exc))

    def stop(self):
        if self.loading:
            self.status.set("正在加载模型，请等待自检完成后停止。")
            return
        if self.engine:
            try:
                self.engine.stop()
            except Exception as exc:
                messagebox.showerror("停止异常", str(exc))
                return
            self.engine = None
        self.start_button.configure(state="normal")
        self.status.set("已停止 · 麦克风未采集")

    def set_mute(self):
        if self.engine:
            self.engine.set_muted(self.mute.get())

    def sound_settings(self):
        os.startfile("ms-settings:sound")

    def diagnostics(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="voice-changer-diagnostics.json")
        if path:
            report = {"app_version": __version__, "devices": self.device_list,
                      "stats": self.engine.stats() if self.engine else {},
                      "note": "包含设备名称与运行统计；不含音频、模型、用户文件路径。"}
            Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("诊断已保存", "内容包括设备名称和运行统计，不包含音频。分享前可自行检查。")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                else:
                    self.busy = False
                    self.download_button.configure(state="normal")
                    if kind in ("loaded", "load_failed"):
                        self.loading = False
                        if kind == "loaded":
                            processor, mic, out, monitor = value
                            try:
                                self.engine = AudioEngine(processor, getattr(processor, "block", 960))
                                self.engine.set_muted(self.mute.get())
                                self.engine.start(mic, out, monitor)
                                self.status.set("AI 变声运行中 · 本地离线处理")
                            except Exception as exc:
                                self.stop()
                                messagebox.showerror("无法启动", str(exc))
                        else:
                            self.start_button.configure(state="normal")
                            self.status.set("启动失败 · 未输出原声")
                            messagebox.showerror("无法加载音色", value)
                    elif kind == "driver":
                        from .setup import launch_driver
                        try:
                            launch_driver(value)
                            self.settings["driver_setup"] = "awaiting_device_after_restart"
                            self.persist()
                            self.status.set("官方安装器已打开；完成安装并重启后，重新打开软件检测。")
                        except Exception as exc:
                            messagebox.showerror("驱动安装", str(exc))
                    elif kind == "installed":
                        self.plugin_path, self.model_path = map(str, value)
                        self.persist()
                        self.update_assets()
                        self.status.set("AI 配置完成 · 可以断网使用")
                    else:
                        self.status.set("下载失败 · 可重试或手动选择官方文件")
                        messagebox.showerror("下载失败", value)
        except queue.Empty:
            pass
        if self.engine:
            stats = self.engine.stats()
            if self.engine.error or any(not stream.active for stream in self.engine.streams):
                reason = self.engine.error or "音频设备已停止或断开。"
                self.stop()
                self.status.set("音频故障 · 已停止输出")
                self.health.set(reason)
            else:
                self.status.set("静音中" if self.mute.get() else "AI 变声运行中 · 本地离线处理")
                self.health.set(f"输入 {stats['input_level']:.2f}  /  输出 {stats['output_level']:.2f}  ·  "
                                f"处理 p95 {stats['processing_p95_ms']} ms（非总延迟）  ·  "
                                f"丢块 {stats['dropped_blocks']}  /  欠载 {stats['output_underflows']}")
        self.root.after(200, self.poll)

    def close(self):
        if self.studio and self.studio.window.winfo_exists():
            self.studio.close()
            if self.studio.window.winfo_exists():
                return
        if self.loading:
            messagebox.showinfo("正在加载", "请等待模型自检结束后关闭。")
            return
        if self.busy and not messagebox.askyesno("正在下载", "退出会中断下载，下次可重新下载。现在退出？"):
            return
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()
