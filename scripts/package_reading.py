"""Build a text-only reading companion. Never collect files from user data folders."""
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_changer import __version__
from voice_changer.reading import script


def build():
    output = ROOT / "dist" / f"VoiceChanger-ReadingKit-{__version__}.zip"
    output.parent.mkdir(exist_ok=True)
    content = script()
    lines = ["# 日常中文自然朗读", "", "40 段原创稿件，约 4,900 字。按每分钟 240–320 字估算约 15–20 分钟。",
             "实际录音时长为准；保持自然语速，不要为了凑时间拖长句子。", "",
             "在 Voice Changer 中打开“素材库 / 朗读采集 / 训练”，创建素材集，再选择“原创稿件 · 引导朗读”。",
             "每段录完先试听，再确认；未确认的录音不会进入训练素材。可关闭窗口后继续。", "",
             "这是文字稿件包，不包含明星录音、其他语音文件或模型。正文采用 CC0-1.0，详见 LICENSE-reading.txt。", ""]
    for segment in content["segments"]:
        lines += ["## " + segment["title"], "", segment["tip"], "", segment["text"], ""]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("READING.md", "\n".join(lines))
        archive.writestr("reading_zh.json", json.dumps(content, ensure_ascii=False, indent=2))
        archive.write(ROOT / "voice_changer/resources/LICENSE-reading.txt", "LICENSE-reading.txt")
    print(output.name)
    return output


if __name__ == "__main__":
    build()
