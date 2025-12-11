"""
自动更新启动器：用于拉起业务可执行文件，并在启动前检查远程版本。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

# ============== 需要按实际部署修改的常量 ==============
CURRENT_VERSION = "1.0.0"
VERSION_URL = "https://gitee.com/yeekii77/store_system/raw/master/version.txt"      # 远程版本号文本文件
DOWNLOAD_URL = "https://gitee.com/yeekii77/store_system/raw/master/main_bot.exe"    # 新版可执行文件下载地址

TARGET_EXE_NAME = "main_bot.exe"
BACKUP_EXE_NAME = "main_bot.old"

# ============== 路径处理 ==============
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

TARGET_EXE_PATH = BASE_DIR / TARGET_EXE_NAME
BACKUP_EXE_PATH = BASE_DIR / BACKUP_EXE_NAME


# ============== 版本与下载 ==============
def _parse_version(version: str) -> list[int]:
    parts: list[int] = []
    for seg in version.strip().split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return parts or [0]


def _is_remote_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def fetch_remote_version() -> str:
    try:
        resp = requests.get(VERSION_URL, timeout=10)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 获取远程版本失败: {exc}")
        return ""


def download_new_exe() -> Path | None:
    try:
        resp = requests.get(DOWNLOAD_URL, stream=True, timeout=60)
        resp.raise_for_status()
        fd, tmp_path = tempfile.mkstemp(prefix="main_bot_", suffix=".exe")
        with os.fdopen(fd, "wb") as tmp_file:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)
        return Path(tmp_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 下载新版本失败: {exc}")
        return None


# ============== 更新流程 ==============
def perform_update() -> None:
    remote_version = fetch_remote_version()
    if not remote_version:
        return

    if not _is_remote_newer(remote_version, CURRENT_VERSION):
        print("[launcher] 已是最新版本，无需更新。")
        return

    print(f"[launcher] 检测到新版本 {remote_version}，开始下载...")
    tmp_exe = download_new_exe()
    if not tmp_exe:
        return

    try:
        if TARGET_EXE_PATH.exists():
            # 先备份旧版本
            if BACKUP_EXE_PATH.exists():
                BACKUP_EXE_PATH.unlink()
            TARGET_EXE_PATH.rename(BACKUP_EXE_PATH)

        # 替换为新版本
        tmp_exe.replace(TARGET_EXE_PATH)
        print("[launcher] 更新完成，已替换为新版本。")

        # 尝试删除旧备份（允许失败）
        try:
            BACKUP_EXE_PATH.unlink()
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 更新流程出现异常: {exc}")
        # 尝试回滚
        if tmp_exe.exists():
            tmp_exe.unlink(missing_ok=True)
        if BACKUP_EXE_PATH.exists() and not TARGET_EXE_PATH.exists():
            try:
                shutil.move(BACKUP_EXE_PATH, TARGET_EXE_PATH)
            except Exception:
                pass


# ============== 启动业务程序 ==============
def launch_main() -> None:
    if not TARGET_EXE_PATH.exists():
        raise FileNotFoundError(f"[launcher] 未找到业务可执行文件: {TARGET_EXE_PATH}")
    print("[launcher] 启动业务程序...")
    subprocess.Popen([str(TARGET_EXE_PATH)], cwd=BASE_DIR)


if __name__ == "__main__":
    perform_update()
    launch_main()
