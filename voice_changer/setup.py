"""Download official components on explicit user action, never during audio processing."""
import ctypes
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .assets import extract_checked, verify_file
from .config import data_dir

CABLE = ("https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
         "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb")
UV = ("https://github.com/astral-sh/uv/releases/download/0.9.5/uv-x86_64-pc-windows-msvc.zip",
      "515dc53d7553f1357d0abc1f70acd921fbb9e30230b1d9a08737236daa6ee920")
REVISION = "a864a1dc5aca33386753c40c192feac53ca71682"
SOURCE = (f"https://github.com/IAHispano/Applio/archive/{REVISION}.zip",
          "af38ff93964f4700452e2f70db3067fa0a832f261e0f5f2bcfe4ab34e7f116f7")


def fetch(spec, destination, progress, job):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            verify_file(destination, spec[1])
            return destination
        except ValueError:
            pass
    part = destination.with_suffix(".part")
    request = urllib.request.Request(spec[0], headers={"User-Agent": "VoiceChanger/0.2"})
    with urllib.request.urlopen(request, timeout=30) as response, part.open("wb") as stream:
        count = 0
        total = int(response.headers.get("Content-Length", 0))
        while chunk := response.read(1024 * 1024):
            job.check()
            count += len(chunk)
            if count > 512 * 1024 * 1024:
                raise ValueError("组件下载超过大小限制。")
            stream.write(chunk)
            progress(f"下载 {destination.name}：{count / 1048576:.1f} / {total / 1048576:.1f} MB")
    job.check()
    verify_file(part, spec[1])
    part.replace(destination)
    return destination


def prepare_driver(progress, job):
    root = data_dir() / "driver"
    archive = fetch(CABLE, root / "vbcable45.zip", progress, job)
    extract_checked(archive, root / "official")
    installer = root / "official/VBCABLE_Setup_x64.exe"
    # Supply the path via environment, not interpolated PowerShell source.
    env = dict(os.environ, VOICE_CHANGER_INSTALLER=str(installer))
    # PowerShell 7 launchers can export an incompatible module search path to 5.1.
    env = {key: value for key, value in env.items() if key.upper() != "PSMODULEPATH"}
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command",
        "(Get-AuthenticodeSignature -LiteralPath $env:VOICE_CHANGER_INSTALLER).Status.ToString()"],
        env=env, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    if result.returncode or result.stdout.strip() != "Valid":
        raise RuntimeError("官方驱动数字签名验证失败，未启动安装器。")
    job.check()
    return installer


def launch_driver(installer):
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(installer), None,
                                                str(Path(installer).parent), 1)
    if result <= 32:
        raise RuntimeError("未启动驱动安装器，可能取消了 Windows 管理员授权。")


def engine_root():
    return data_dir() / "training-engine"


def engine_paths(root=None):
    root = root or engine_root()
    return root / "env/Scripts/python.exe", root / f"Applio-{REVISION}"


def install_engine(progress, job, root=None):
    root = root or engine_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        if gpu.returncode or not gpu.stdout.strip():
            raise RuntimeError("没有检测到可用的 NVIDIA GPU 驱动。")
        progress("检测到显卡：" + gpu.stdout.strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("本版自定义音色需要 NVIDIA 显卡及其驱动；官方音色仍可使用 CPU。") from exc
    if shutil.disk_usage(root).free < 15 * 1024**3:
        raise RuntimeError("本地训练环境建议至少预留 15 GB 空间，请清理后重试。")
    marker = root / "ready.json"
    marker.unlink(missing_ok=True)
    extract_checked(fetch(UV, root / "uv.zip", progress, job), root / "tools")
    extract_checked(fetch(SOURCE, root / "source.zip", progress, job), root)
    uv = root / "tools/uv.exe"
    python, source = engine_paths(root)
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(root / "python"),
               UV_CACHE_DIR=str(root / "cache"), PYTHONUTF8="1",
               UV_HTTP_TIMEOUT="60", UV_CONCURRENT_DOWNLOADS="4", HF_HUB_DISABLE_TELEMETRY="1")
    log = root / "install.log"
    progress("配置独立 Python 3.12 环境…")
    if not python.exists():
        job.run([uv, "venv", "--python", "3.12.11", "--managed-python", root / "env"], root, progress, log, env)
    progress("安装训练依赖（数 GB，首次安装可能较久）…")
    lock = Path(__file__).with_name("engine-requirements.txt")
    job.run([uv, "pip", "install", "--python", python, "-r", lock,
             "--index-url", "https://pypi.org/simple", "--extra-index-url",
             "https://download.pytorch.org/whl/cu128", "--index-strategy", "unsafe-best-match"],
            source, progress, log, env)
    progress("下载本地训练和推理所需基础模型…")
    job.run([python, "-c", "from rvc.lib.tools.prerequisites_download import prequisites_download_pipeline, ensure_pretrained; "
             "prequisites_download_pipeline(False, True, True); ensure_pretrained('HiFi-GAN', 40000)"],
            source, progress, log, env)
    job.run([python, "-c", "import torch; from rvc.realtime.core import VoiceChanger; "
             "assert torch.cuda.is_available(), '本版本地训练需要支持 CUDA 的 NVIDIA 显卡'; "
             "print(torch.cuda.get_device_name(0))"], source, progress, log, env)
    marker.write_text(json.dumps({"revision": REVISION}), encoding="utf-8")


def engine_ready():
    python, source = engine_paths()
    try:
        marker = json.loads((engine_root() / "ready.json").read_text(encoding="utf-8"))
        return python.is_file() and source.is_dir() and marker.get("revision") == REVISION
    except (OSError, ValueError):
        return False
