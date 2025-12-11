"""
自动更新启动器：用于拉起业务可执行文件，并在启动前检查远程版本。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests

# ============== 需要按实际部署修改的常量 ==============
CURRENT_VERSION = "0.0.1"
VERSION_URL = "https://gitee.com/yeekii77/store_system/raw/master/version.txt"      # 远程版本号文本文件
ZIP_URL = "https://gitee.com/yeekii77/store_system/releases/download/1.1.0/main_bot.zip"  # 默认压缩包下载地址（回退用）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

TARGET_EXE_NAME = "main_bot.exe"
BACKUP_EXE_NAME = "main_bot.old"
LOCAL_VERSION_FILE = "local_version.txt"

# ============== 路径处理 ==============
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

TARGET_EXE_PATH = BASE_DIR / TARGET_EXE_NAME
BACKUP_EXE_PATH = BASE_DIR / BACKUP_EXE_NAME
LOCAL_VERSION_PATH = BASE_DIR / LOCAL_VERSION_FILE


# ============== 版本与下载 ==============
def _parse_version(version: str) -> list[int]:
    parts: list[int] = []
    for seg in version.strip().split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return parts or [0]


def _is_remote_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def read_local_version() -> str:
    if LOCAL_VERSION_PATH.exists():
        try:
            return LOCAL_VERSION_PATH.read_text(encoding="utf-8").strip() or CURRENT_VERSION
        except Exception:
            return CURRENT_VERSION
    return CURRENT_VERSION


def write_local_version(version: str) -> None:
    try:
        LOCAL_VERSION_PATH.write_text(version.strip(), encoding="utf-8")
    except Exception:
        pass


def _parse_version_and_url(text: str) -> tuple[str, str | None]:
    """
    解析 version.txt，格式: version|url
    无 | 时仅返回版本，url 为 None。
    """
    raw = text.strip()
    if "|" in raw:
        ver, url = raw.split("|", 1)
        return ver.strip(), url.strip() or None
    return raw, None


def fetch_remote_version() -> tuple[str, str | None]:
    try:
        resp = requests.get(VERSION_URL, timeout=10, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
        return _parse_version_and_url(resp.text)
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 获取远程版本失败: {exc}")
        return "", None


def download_new_zip(url: str) -> Path | None:
    try:
        resp = requests.get(url, stream=True, timeout=60, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
        fd, tmp_path = tempfile.mkstemp(prefix="main_bot_", suffix=".zip")
        with os.fdopen(fd, "wb") as tmp_file:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)
        return Path(tmp_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 下载新版本失败: {exc}")
        return None


def _extract_exe_from_zip(zip_path: Path) -> tuple[Path, Path] | None:
    """
    解压 zip 并返回 (main_bot.exe 的临时路径, 解压根目录)。
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="main_bot_unzip_"))
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
            members = zf.namelist()

        for member in members:
            if member.lower().endswith("main_bot.exe"):
                exe_path = (tmp_dir / member).resolve()
                if exe_path.exists():
                    return exe_path, tmp_dir
        # 如果遍历不到 exe，尝试直接在解压目录下寻找
        candidate = next(tmp_dir.rglob("main_bot.exe"), None)
        if candidate:
            return candidate, tmp_dir
        print("[launcher] 压缩包中未找到 main_bot.exe")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 解压失败: {exc}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


def _replace_with_retry(new_exe: Path, target_path: Path, retries: int = 3, delay: float = 1.5) -> bool:
    """
    将 new_exe 覆盖到 target_path，带简单重试，防止文件占用导致失败。
    """
    for attempt in range(1, retries + 1):
        try:
            if target_path.exists():
                if BACKUP_EXE_PATH.exists():
                    BACKUP_EXE_PATH.unlink()
                target_path.rename(BACKUP_EXE_PATH)
            shutil.copy2(new_exe, target_path)
            try:
                BACKUP_EXE_PATH.unlink()
            except Exception:
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[launcher] 替换文件失败(第{attempt}次): {exc}")
            # 失败后尝试回滚旧版本
            if BACKUP_EXE_PATH.exists() and not target_path.exists():
                try:
                    BACKUP_EXE_PATH.rename(target_path)
                except Exception:
                    pass
            time.sleep(delay)
    return False


# ============== 更新流程 ==============
def perform_update() -> None:
    remote_version, remote_url = fetch_remote_version()
    if not remote_version:
        return

    local_version = read_local_version()
    if not _is_remote_newer(remote_version, local_version):
        print("[launcher] 已是最新版本，无需更新。")
        return

    download_url = remote_url or ZIP_URL
    if not download_url:
        print("[launcher] 远程版本文件格式错误，未找到下载链接")
        return

    print(f"[launcher] 检测到新版本 {remote_version}，开始下载...")
    tmp_zip = download_new_zip(download_url)
    if not tmp_zip:
        return

    extracted_exe: Path | None = None
    extracted_root: Path | None = None

    try:
        extracted = _extract_exe_from_zip(tmp_zip)
        if not extracted:
            return
        extracted_exe, extracted_root = extracted

        if not _replace_with_retry(extracted_exe, TARGET_EXE_PATH):
            print("[launcher] 更新失败，已放弃替换。")
            return

        print("[launcher] 更新完成，已替换为新版本。")
        write_local_version(remote_version)
    except Exception as exc:  # noqa: BLE001
        print(f"[launcher] 更新流程出现异常: {exc}")
    finally:
        if extracted_root and extracted_root.exists():
            shutil.rmtree(extracted_root, ignore_errors=True)
        if tmp_zip and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)


# ============== 启动业务程序 ==============
def launch_main() -> None:
    if not TARGET_EXE_PATH.exists():
        raise FileNotFoundError(f"[launcher] 未找到业务可执行文件: {TARGET_EXE_PATH}")
    print("[launcher] 启动业务程序...")
    subprocess.Popen([str(TARGET_EXE_PATH)], cwd=BASE_DIR)


if __name__ == "__main__":
    perform_update()
    launch_main()
