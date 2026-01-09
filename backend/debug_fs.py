# backend/debug_fs.py
from pathlib import Path
from config import MEDIA_ROOT, PROJECTS_ROOT

print("MEDIA_ROOT :", MEDIA_ROOT)
print("存在吗     :", MEDIA_ROOT.exists(), "是否目录:", MEDIA_ROOT.is_dir())
print("PROJECTS_ROOT :", PROJECTS_ROOT)
print("存在吗         :", PROJECTS_ROOT.exists(), "是否目录:", PROJECTS_ROOT.is_dir())

print("\nMEDIA_ROOT 下的前几十个子项：")
if MEDIA_ROOT.exists():
    for p in list(MEDIA_ROOT.iterdir())[:50]:
        print(" -", p)
