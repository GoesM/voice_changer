import json
import os
from pathlib import Path


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VoiceChanger"


def load_settings(path=None):
    path = path or data_dir() / "settings.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings, path=None):
    path = path or data_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
