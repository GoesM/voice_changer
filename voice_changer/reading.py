"""Original reading script and resumable take review; no microphone access here."""
import json
from pathlib import Path

from .materials import read_json, clip_path, register_clip, remove_clip
from .studio import analyze_wav, write_json


def script():
    return json.loads((Path(__file__).parent / "resources/reading_zh.json").read_text(encoding="utf-8"))


def state(project):
    value = read_json(project / "reading.json", {"current": 0, "accepted": {}, "pending": {}})
    if not isinstance(value, dict):
        raise ValueError("朗读进度文件损坏，请保留录音并检查 reading.json。")
    value.setdefault("accepted", {})
    value.setdefault("pending", {})
    value.setdefault("current", 0)
    if not isinstance(value["current"], int):
        raise ValueError("朗读进度格式无效。")
    for key, folder in (("accepted", "recordings"), ("pending", ".takes")):
        if not isinstance(value[key], dict):
            raise ValueError("朗读素材索引无效。")
        for name in value[key].values():
            if not isinstance(name, str):
                raise ValueError("朗读素材名称无效。")
            clip_path(project, name, folder)
    return value


def save_position(project, index):
    value = state(project)
    value["current"] = max(0, min(len(script()["segments"]) - 1, index))
    write_json(project / "reading.json", value)


def pending_take(project, segment_id):
    name = state(project)["pending"].get(segment_id)
    if name:
        path = clip_path(project, name, ".takes")
        if path.is_file():
            return path
    return None


def save_pending(project, segment_id, path):
    if segment_id not in {item["id"] for item in script()["segments"]}:
        raise ValueError("未知稿件段落。")
    if path.resolve() != clip_path(project, path.name, ".takes").resolve() or not path.is_file():
        raise ValueError("录音不在当前素材集的待确认目录。")
    value = state(project)
    previous = value["pending"].get(segment_id)
    value["pending"][segment_id] = path.name
    write_json(project / "reading.json", value)
    if previous and previous != path.name:
        remove_clip(project, previous, ".takes")


def accept_take(project, segment):
    path = pending_take(project, segment["id"])
    if path is None:
        raise ValueError("请先录制本段并试听。")
    quality = analyze_wav(path)
    minimum = max(3, len(segment["text"]) / 8)
    if quality["seconds"] < minimum:
        raise ValueError(f"本段录音偏短，至少需要约 {minimum:.0f} 秒。请完整朗读后重录。")
    if quality["clipping"] > .005:
        raise ValueError("录音明显削波，请降低麦克风音量后重录。")
    if quality["active_seconds"] < quality["seconds"] * .5:
        raise ValueError("静音或声音过轻占比偏高，请靠近麦克风并完整朗读后重录。")
    value = state(project)
    previous = value["accepted"].get(segment["id"])
    target = clip_path(project, path.name)
    # Copy first so a metadata write failure leaves the pending take recoverable.
    import shutil
    shutil.copyfile(path, target)
    try:
        register_clip(project, target, segment["title"], "引导朗读", segment["id"])
        value["accepted"][segment["id"]] = target.name
        value["pending"].pop(segment["id"], None)
        write_json(project / "reading.json", value)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    path.unlink(missing_ok=True)
    if previous and previous != target.name:
        remove_clip(project, previous)
    return quality


def completed(project):
    accepted = state(project)["accepted"]
    return {key for key, name in accepted.items() if clip_path(project, name).is_file()}
