from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import uiautomation as auto
from loguru import logger


def configure_dpi_awareness() -> None:
    """Ensure the process is DPI-aware on high-resolution screens."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    if hasattr(auto, "SetHighDpiAware"):
        try:
            auto.SetHighDpiAware()
        except Exception:
            pass


def check_environment(cfg: Dict[str, str]) -> Tuple[bool, List[str], List[str]]:
    """Validate basic runtime requirements before launching the UI."""
    fatal_errors: List[str] = []
    warnings: List[str] = []

    if os.name != "nt":
        fatal_errors.append("当前系统不是 Windows，无法运行 RPA。")

    exec_path = (cfg.get("WECHAT_EXEC_PATH") or "").strip()
    if not exec_path:
        warnings.append("未配置 WECHAT_EXEC_PATH，将尝试使用已运行的微信客户端。")
    else:
        resolved = Path(exec_path).expanduser()
        if not resolved.exists():
            fatal_errors.append(f"指定的微信路径不存在：{resolved}")

    dependencies = [
        ("pyperclip", "pip install pyperclip"),
        ("win32clipboard", "pip install pywin32"),
        ("win32con", "pip install pywin32"),
    ]
    for module_name, hint in dependencies:
        try:
            __import__(module_name)
        except ImportError:
            fatal_errors.append(f"缺少依赖 {module_name}，请运行：{hint}")

    return len(fatal_errors) == 0, fatal_errors, warnings


def run_self_check() -> None:
    """
    Perform a foreground self-check to ensure the desktop environment is ready.
    Failure results in a CRITICAL log and immediate exit.
    """
    logger.info("正在执行启动自检...")
    try:
        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if width == 0 or height == 0:
            raise EnvironmentError(f"检测到异常屏幕分辨率: {width}x{height}，无法运行 UI 自动化。")
        logger.debug(f"屏幕分辨率检测通过: {width}x{height}")

        current_x, current_y = auto.GetCursorPos()
        try:
            auto.SetCursorPos(current_x + 1, current_y + 1)
            auto.SetCursorPos(current_x, current_y)
        except Exception as exc:
            raise PermissionError(f"无法控制鼠标，可能屏幕已锁定或权限不足。原始错误: {exc}")
        logger.debug("鼠标控制权检测通过")

        candidates = [
            {"Name": "微信", "ClassName": "WeChatMainWndForPC"},
            {"Name": "微信"},
            {"SubName": "微信"},
            {"Name": "WeChat"},
        ]
        wechat_window = None
        for params in candidates:
            window = auto.WindowControl(**params)
            if window.Exists(maxSearchSeconds=2):
                wechat_window = window
                break
        if wechat_window is None:
            raise RuntimeError("未检测到【微信】主窗口，请确保微信已登录且未最小化。")
        try:
            _ = wechat_window.NativeWindowHandle
        except Exception as exc:
            raise RuntimeError(f"检测到微信窗口，但无法获取句柄，可能权限不足。错误: {exc}")

        logger.info("✅ 启动自检通过，环境正常。")
    except Exception as exc:
        logger.critical(f"启动自检失败，程序终止！原因: {exc}")
        sys.exit(1)

