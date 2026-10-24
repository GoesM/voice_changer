"""Collect installed dependency license texts into the downloadable bundle."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

target = Path("build/licenses")
target.mkdir(parents=True, exist_ok=True)
for file in Path("third_party").glob("*.txt"):
    shutil.copy2(file, target / file.name)
for name in ("numpy", "pedalboard", "sounddevice", "cffi", "pycparser"):
    distribution = importlib.metadata.distribution(name)
    found = 0
    for file in distribution.files or []:
        if any(part.lower().startswith(("license", "copying", "notice", "copyright")) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                output = target / name / str(file).replace("..", "_")
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
                found += 1
    if not found:
        raise RuntimeError(f"No license text found for {name}")
    (target / name / "version.txt").write_text(distribution.version, encoding="utf-8")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
for file in (Path(sys.base_prefix) / "tcl").rglob("*"):
    if file.is_file() and file.name.lower().startswith(("license", "copying")):
        output = target / "tcl-tk" / file.relative_to(Path(sys.base_prefix) / "tcl")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, output)
