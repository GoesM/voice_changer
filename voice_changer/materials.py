"""Local speaker collections. Recordings stay private; names never become paths."""
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .studio import projects_root, new_project, write_json, analyze_wav


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def clip_path(project, name, folder="recordings"):
    root = (project / folder).resolve()
    target = root / name
    if Path(name).name != name or target.suffix.lower() != ".wav" or target.resolve().parent != root:
        raise ValueError("素材路径无效。")
    return target


def catalog(project):
    value = read_json(project / "materials.json", {})
    if not isinstance(value, dict):
        raise ValueError("素材目录索引损坏，请保留录音并检查 materials.json。")
    return value


def register_clip(project, path, label=None, source="自由录音", reading_id=None):
    path = clip_path(project, path.name)
    quality = analyze_wav(path)
    entries = catalog(project)
    entries[path.name] = {"label": (label or datetime.now().strftime("录音 %m-%d %H:%M:%S"))[:100],
                          "source": source, "reading_id": reading_id, "quality": quality,
                          "size": path.stat().st_size, "mtime": path.stat().st_mtime_ns}
    write_json(project / "materials.json", entries)


def list_clips(project):
    entries = catalog(project)
    result = []
    changed = False
    for path in sorted((project / "recordings").glob("*.wav")):
        path = clip_path(project, path.name)
        entry = entries.get(path.name, {})
        if entry.get("size") != path.stat().st_size or entry.get("mtime") != path.stat().st_mtime_ns:
            entry = {**entry, "label": entry.get("label", "已有素材 " + path.stem[:8]),
                     "source": entry.get("source", "已有录音"), "quality": analyze_wav(path),
                     "size": path.stat().st_size, "mtime": path.stat().st_mtime_ns}
            entries[path.name] = entry
            changed = True
        result.append({**entry, "path": path})
    if changed:
        write_json(project / "materials.json", entries)
    return sorted(result, key=lambda entry: entry["label"])


def rename_clip(project, name, label):
    label = label.strip()
    if not label or len(label) > 100:
        raise ValueError("素材名称需为 1–100 字。")
    path = clip_path(project, name)
    if not path.is_file():
        raise ValueError("素材不存在。")
    list_clips(project)
    entries = catalog(project)
    entries[name]["label"] = label
    write_json(project / "materials.json", entries)


def remove_clip(project, name, folder="recordings"):
    path = clip_path(project, name, folder)
    if path.exists():
        trash = project / ".trash"
        trash.mkdir(exist_ok=True)
        path.replace(trash / (uuid.uuid4().hex + ".wav"))
    # Keep metadata for auditing; only recordings/*.wav are used for training.


def collections():
    items = []
    for path in sorted(projects_root().glob("*/project.json")):
        try:
            meta = read_json(path, {})
            if isinstance(meta.get("name"), str):
                items.append((f"{meta['name']} · {path.parent.name[-6:]}", path.parent))
        except (OSError, ValueError, AttributeError):
            continue
    return items


def rename_collection(project, name):
    if not name.strip() or len(name.strip()) > 60:
        raise ValueError("素材集名称需为 1–60 字。")
    meta = read_json(project / "project.json", {})
    meta["name"] = name.strip()
    write_json(project / "project.json", meta)


def copy_collection(project, name, check=lambda: None):
    # A new training revision copies materials, never trained checkpoints.
    clips = list_clips(project)
    check()
    target = new_project(name)
    for entry in clips:
        check()
        shutil.copyfile(entry["path"], target / "recordings" / entry["path"].name)
    check()
    write_json(target / "materials.json", catalog(project))
    state = read_json(project / "reading.json", {})
    if state:
        state["pending"] = {}
        write_json(target / "reading.json", state)
    return target
