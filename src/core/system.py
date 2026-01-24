from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import uiautomation as auto
from loguru import logger

from src.config.settings import get_config


def configure_dpi_awareness() -> None:
    """Ensure the process is DPI-aware on high-resolution screens."""
    # 注意：Tkinter 自身有 DPI 处理，不要在这里重复设置
    # uiautomation 会在需要时自动处理 DPI
    # 只保留必要的基础设置，避免与 Tkinter 冲突
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
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
        warnings.append("未配置 WECHAT_EXEC_PATH，程序启动后请手动打开微信客户端。")
    else:
        resolved = Path(exec_path).expanduser()
        if not resolved.exists():
            warnings.append(f"指定的微信路径不存在：{resolved}")

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


def _try_launch_wechat() -> Optional[str]:
    """
    尝试启动微信客户端。

    Returns:
        成功返回 None，失败返回错误信息字符串
    """
    cfg = get_config()
    exec_path = (cfg.get("WECHAT_EXEC_PATH") or "").strip()

    if not exec_path:
        return None  # 没有配置路径时不自动启动

    resolved = Path(exec_path).expanduser()
    if not resolved.exists():
        return f"微信路径不存在：{resolved}"

    try:
        subprocess.Popen(str(resolved))
        logger.info("已启动微信，等待窗口出现...")
        return None
    except Exception as e:
        return f"启动微信失败：{e}"


def _find_wechat_window(max_wait_seconds: int = 3) -> Optional[auto.WindowControl]:
    """
    查找微信窗口。

    Args:
        max_wait_seconds: 最大等待秒数

    Returns:
        找到返回 WindowControl，未找到返回 None
    """
    candidates = [
        {"Name": "微信", "ClassName": "mmui::MainWindow"},
        {"Name": "微信"},
        {"SubName": "微信"},
        {"Name": "WeChat"},
    ]

    for params in candidates:
        window = cast(Any, auto).WindowControl(
            searchDepth=1,
            searchInterval=0.5,
            foundIndex=1,
            Depth=10,
            Name=params.get("Name", ""),
            ClassName=params.get("ClassName", ""),
            SubName=params.get("SubName", ""),
        )
        if window.Exists(maxSearchSeconds=1):
            return window

    return None


def run_self_check() -> None:
    """
    执行启动自检。

    变更：不再因为微信未找到而崩溃，只提示用户手动打开。
    程序可以正常启动，但微信 RPA 功能需要在微信运行时才能工作。
    """
    logger.info("正在执行启动自检...")
    wechat_found = False
    wechat_message = ""

    # 1. 检查屏幕分辨率
    try:
        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if width == 0 or height == 0:
            raise EnvironmentError(
                f"检测到异常屏幕分辨率: {width}x{height}，无法运行 UI 自动化。"
            )
        logger.debug(f"屏幕分辨率检测通过: {width}x{height}")
    except EnvironmentError:
        # 分辨率检查失败是致命错误
        raise
    except Exception as exc:
        logger.warning(f"屏幕分辨率检测异常: {exc}")

    # 2. 检查鼠标控制权
    try:
        user32 = ctypes.windll.user32
        current_x, current_y = auto.GetCursorPos()
        try:
            auto.SetCursorPos(current_x + 1, current_y + 1)
            auto.SetCursorPos(current_x, current_y)
        except Exception as set_pos_err:
            logger.warning(f"鼠标控制权检测异常，继续启动: {set_pos_err}")
    except Exception:
        logger.warning("鼠标控制权检测失败，继续启动")

    # 3. 检查微信窗口（非致命，只提示）
    try:
        wechat_window = _find_wechat_window(max_wait_seconds=2)
        if wechat_window is not None:
            wechat_found = True
            logger.info("✅ 检测到微信窗口已运行")
        else:
            # 尝试自动启动
            launch_error = _try_launch_wechat()
            if launch_error:
                wechat_message = launch_error
                logger.warning(f"微信自动启动失败: {launch_error}")
                logger.info("⚠️ 程序将正常启动，但微信 RPA 功能需要微信客户端运行")
            else:
                # 启动成功，再检查一次
                time.sleep(2)
                wechat_window = _find_wechat_window(max_wait_seconds=3)
                if wechat_window is not None:
                    wechat_found = True
                    logger.info("✅ 微信启动成功")
                else:
                    wechat_message = "微信已启动但窗口未检测到"
                    logger.info("⚠️ 程序将正常启动，请确认微信客户端是否正常运行")

    except Exception as exc:
        logger.warning(f"微信检测异常: {exc}")
        wechat_message = f"微信检测失败: {exc}"

    # 4. 输出检查结果
    if wechat_found:
        logger.info("✅ 启动自检通过，环境正常")
    else:
        if wechat_message:
            logger.warning(f"⚠️ {wechat_message}")
        logger.info("✅ 启动自检完成（微信未运行，RPA 功能受限）")
        logger.info("💡 请手动打开微信客户端以启用 RPA 功能")
        logger.info("💡 或点击程序内的「刷新状态」按钮重新检测")
