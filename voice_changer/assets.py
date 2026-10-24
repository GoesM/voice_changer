"""Explicit, checksum-pinned first-run downloads. No networking during inference."""
import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

from .config import data_dir

TERMS_URL = "https://prj-beatrice.com/2.0.0-rc.0-official-model-1-terms"
PLUGIN_URL = "https://prj-beatrice.com/"
CABLE_URL = "https://vb-audio.com/Cable/"
ASSETS = (
    {"name": "plugin", "url": "https://storage.prj-beatrice.com/beatrice_2.0.0-rc.3_win.zip",
     "sha256": "fa5b05196796194155618360079eff5471cad5f58fbd108b5a0c6948ca2bf0a1"},
    {"name": "model", "url": "https://storage.prj-beatrice.com/beatrice_2.0.0-rc.0_official_model_1.zip",
     "sha256": "046273adf7403143c64fabe1f84645f3a0349fdaf6aad23055a0dda23a2efe8f"},
)


def verify_file(path, expected):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("下载文件校验失败，请重试或在 GitHub 报告；未加载该文件。")


def extract_checked(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as zf:
        if sum(item.file_size for item in zf.infolist()) > 512 * 1024 * 1024:
            raise ValueError("解压大小超过限制。")
        for item in zf.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("压缩包包含不安全路径。")
        zf.extractall(destination)


def asset_paths(root=None):
    root = root or data_dir() / "assets"
    return (
        root / "plugin/beatrice_2.0.0-rc.3/beatrice_2.0.0-rc.3.vst3",
        root / "model/beatrice_2.0.0-rc.0_official_model_1/beatrice_2.0.0-rc.0_official_model_1.toml",
    )


def install_assets(progress, root=None):
    root = root or data_dir() / "assets"
    root.mkdir(parents=True, exist_ok=True)
    for asset in ASSETS:
        archive = root / (asset["name"] + ".zip")
        valid = False
        if archive.exists():
            try:
                verify_file(archive, asset["sha256"])
                valid = True
            except ValueError:
                pass
        if not valid:
            temporary = archive.with_suffix(".part")
            request = urllib.request.Request(asset["url"], headers={
                "User-Agent": "Mozilla/5.0 VoiceChanger/0.1", "Referer": "https://prj-beatrice.com/"})
            with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as file:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                while chunk := response.read(256 * 1024):
                    received += len(chunk)
                    if received > 150 * 1024 * 1024:
                        raise ValueError("下载大小超过限制。")
                    file.write(chunk)
                    progress(f"下载 {asset['name']}：{received / 1048576:.1f} / {total / 1048576:.1f} MB")
            verify_file(temporary, asset["sha256"])
            temporary.replace(archive)
        progress(f"校验通过，正在解压 {asset['name']}…")
        extract_checked(archive, root / asset["name"])
    return asset_paths(root)
