"""
业务主入口：轮询飞书任务，调用微信 RPA 添加好友，并回写处理状态。
启动时始终显示 Tk 窗口，并在后台线程跑任务。
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import Tk, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from typing import Any

try:
    import pythoncom
except ImportError:  # pragma: no cover - pywin32 only on Windows
    pythoncom = None

import ctypes
import uiautomation as auto

from loguru import logger

from config import get_config
from src.feishu_client import FeishuClient
from src.logger_config import setup_logger
from src.wechat_bot import WeChatRPA

# === 核心修复：强制开启高 DPI 感知 ===
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if hasattr(auto, "SetHighDpiAware"):
    auto.SetHighDpiAware()

setup_logger()
LOG_QUEUE: "queue.Queue[str]" = queue.Queue(maxsize=500)


def _queue_sink(message) -> None:  # type: ignore[override]
    """将日志推送到 GUI 队列用于实时展示。"""
    try:
        LOG_QUEUE.put_nowait(str(message).rstrip("\n"))
    except Exception:
        pass


# 将 GUI sink 放在最后，避免阻塞主日志输出
logger.add(_queue_sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def _run_env_checks(cfg: dict[str, str]) -> tuple[bool, list[str], list[str]]:
    """基础环境自检，避免在甲方电脑重复踩坑。"""
    fatal_errors: list[str] = []
    warning_messages: list[str] = []

    if os.name != "nt":
        fatal_errors.append("当前系统不是 Windows，无法运行 RPA。")

    exec_path = (cfg.get("WECHAT_EXEC_PATH") or "").strip()
    if not exec_path:
        warning_messages.append("未配置 WECHAT_EXEC_PATH，将尝试使用已运行的微信客户端。")
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

    return len(fatal_errors) == 0, fatal_errors, warning_messages


def run_self_check() -> None:
    """
    启动自检：检测屏幕、鼠标控制权及微信窗口状态。
    自检失败会直接发送 CRITICAL 日志并退出。
    """
    logger.info("正在执行启动自检...")
    try:
        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if width == 0 or height == 0:
            raise EnvironmentError(f"检测到异常屏幕分辨率: {width}x{height}，无法运行UI自动化。")
        logger.debug(f"屏幕分辨率检测通过: {width}x{height}")

        current_x, current_y = auto.GetCursorPos()
        try:
            auto.SetCursorPos(current_x + 1, current_y + 1)
            auto.SetCursorPos(current_x, current_y)
        except Exception as exc:
            raise PermissionError(f"无法控制鼠标，可能屏幕已锁定或权限不足。原始错误: {exc}")
        logger.debug("鼠标控制权检测通过")

        candidate_windows = [
            {"Name": "微信", "ClassName": "WeChatMainWndForPC"},
            {"Name": "微信"},
            {"SubName": "微信"},
            {"Name": "WeChat"},
        ]
        wechat_window = None
        for params in candidate_windows:
            wechat_window = auto.WindowControl(**params)
            if wechat_window.Exists(maxSearchSeconds=2):
                break
            wechat_window = None
        if wechat_window is None:
            raise RuntimeError("未检测到【微信】主窗口，请确认微信已登录且没有最小化至托盘。")
        try:
            _ = wechat_window.NativeWindowHandle
        except Exception as exc:
            raise RuntimeError(f"检测到微信窗口，但无法获取句柄，可能权限不足。错误: {exc}")

        logger.info("✅ 启动自检通过，环境正常。")
    except Exception as exc:
        logger.critical(f"启动自检失败，程序终止！原因: {exc}")
        sys.exit(1)


def _normalize_welcome_step(data: Any) -> dict[str, str] | None:
    action = str((data or {}).get("type") or "").strip().lower()
    if action == "text":
        content = str(data.get("content") or "").strip()
        if content:
            return {"type": "text", "content": content}
    elif action == "image":
        path = str(data.get("path") or "").strip()
        if path:
            return {"type": "image", "path": path}
    elif action == "link":
        url = str(data.get("url") or "").strip()
        if url:
            step: dict[str, str] = {"type": "link", "url": url}
            title = str(data.get("title") or "").strip()
            if title:
                step["title"] = title
            return step
    return None


def _load_welcome_steps(cfg: dict[str, str]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    raw = (cfg.get("WELCOME_STEPS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        normalized = _normalize_welcome_step(item)
                        if normalized:
                            steps.append(normalized)
        except json.JSONDecodeError as exc:
            logger.warning("欢迎步骤配置解析失败，将回落至旧版字段: {}", exc)

    if not steps:
        legacy_text = (cfg.get("WELCOME_TEXT") or "").strip()
        if legacy_text:
            steps.append({"type": "text", "content": legacy_text})
        legacy_images = [
            part.strip()
            for part in (cfg.get("WELCOME_IMAGE_PATHS") or "").split("|")
            if part.strip()
        ]
        for image in legacy_images:
            steps.append({"type": "image", "path": image})
    return steps


def _extract_phone_and_name(fields: dict[str, Any]) -> tuple[str, str]:
    raw_phone = fields.get("手机号")
    phone: str = ""
    if isinstance(raw_phone, str):
        phone = raw_phone.strip()
    elif isinstance(raw_phone, (int, float)):
        phone = str(int(raw_phone))
    elif isinstance(raw_phone, list) and raw_phone:
        first_item = raw_phone[0]
        if isinstance(first_item, dict):
            phone = first_item.get("full_number") or first_item.get("text") or first_item.get("value") or ""
        else:
            phone = str(first_item)

    phone = phone.strip()

    name_value = fields.get("姓名", "")
    name = ""
    if isinstance(name_value, list) and name_value:
        first = name_value[0]
        if isinstance(first, dict):
            name = first.get("text", "")
        else:
            name = str(first)
    elif isinstance(name_value, str):
        name = name_value

    return phone, name.strip()


def run_bot(stop_event: threading.Event, cfg: dict[str, str]) -> None:
    """
    主循环拆分为两个任务：
    A. “待添加” -> 检测状态并发起申请
    B. “已申请” -> 等待通过并发送欢迎包
    """
    co_initialized = False
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
            co_initialized = True
        except Exception:
            logger.warning("COM 初始化失败，可能影响 RPA：{}", "CoInitialize 调用异常")

    feishu = FeishuClient(
        app_id=cfg.get("FEISHU_APP_ID"),
        app_secret=cfg.get("FEISHU_APP_SECRET"),
        task_table_url=cfg.get("FEISHU_TABLE_URL"),
        profile_table_url=cfg.get("FEISHU_PROFILE_TABLE_URL"),
    )
    wechat = WeChatRPA(exec_path=cfg.get("WECHAT_EXEC_PATH", ""))

    welcome_enabled = (cfg.get("WELCOME_ENABLED") or "0") == "1"
    welcome_steps = _load_welcome_steps(cfg)
    if welcome_enabled and not welcome_steps:
        logger.warning("已启用首次欢迎包，但没有配置任何步骤，将跳过自动发送。")
        welcome_enabled = False

    logger.info("系统启动，进入双队列任务循环...")

    def handle_apply_queue() -> None:
        tasks = feishu.fetch_tasks_by_status(["待添加"])
        if not tasks:
            return
        for item in tasks:
            record_id = item.get("record_id") or item.get("recordId")
            fields = item.get("fields", {})
            phone, name = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            relationship = wechat.check_relationship(phone)
            logger.info("[申请队列] 手机:{}, 关系检测: {}", phone, relationship)
            if relationship == "friend":
                logger.info("{} 已经是好友，进入发送队列", phone)
                feishu.update_status(record_id, "已申请")
                continue
            if relationship == "stranger":
                if wechat.apply_friend(phone):
                    feishu.update_status(record_id, "已申请")
                else:
                    logger.warning("申请发送失败 [{}]", phone)
                continue
            logger.warning("无法确定 [{}] 关系状态，稍后重试", phone)

    def handle_welcome_queue() -> None:
        tasks = feishu.fetch_tasks_by_status(["已申请"])
        if not tasks:
            return
        for item in tasks:
            record_id = item.get("record_id") or item.get("recordId")
            fields = item.get("fields", {})
            phone, name = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            relationship = wechat.check_relationship(phone)
            logger.info("[欢迎队列] 手机:{}, 关系检测: {}", phone, relationship)
            if relationship != "friend":
                logger.debug("{} 尚未通过验证，等待下一轮", phone)
                continue

            send_ok = True
            if welcome_enabled and welcome_steps:
                search_keys = [phone]
                if name:
                    search_keys.append(name)
                    search_keys.append(f"{phone}-{name}")
                try:
                    send_ok = wechat.send_welcome_package(search_keys, welcome_steps)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("发送欢迎包异常 [{}]: {}", phone, exc)
                    send_ok = False

            if send_ok:
                feishu.update_status(record_id, "已绑定")
            else:
                logger.warning("{} 欢迎消息发送失败，保持“已申请”供人工处理", phone)

    while not stop_event.is_set():
        try:
            handle_apply_queue()
            handle_welcome_queue()
            time.sleep(5)
        except Exception as exc:  # noqa: BLE001
            if stop_event.is_set():
                break
            logger.exception("主循环发生异常: {}", exc)
            time.sleep(5)

    logger.info("停止信号已收到，退出任务轮询。")
    if co_initialized and pythoncom is not None:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _start_gui() -> None:
    """启动 Tk 窗口与后台线程。"""
    try:
        cfg = get_config()
    except Exception as exc:  # noqa: BLE001
        logger.error("配置加载失败：{}", exc)
        try:
            root = Tk()
            root.withdraw()
            messagebox.showerror("配置未完成", f"请填写配置后重试：{exc}", parent=root)
            root.destroy()
        except Exception:
            pass
        return

    check_ok, errors, warnings = _run_env_checks(cfg)
    for warn in warnings:
        logger.warning("环境自检提示：{}", warn)
    if not check_ok:
        for err in errors:
            logger.error("环境自检失败：{}", err)
        try:
            root = Tk()
            root.withdraw()
            messagebox.showerror("环境检查失败", "\n".join(errors), parent=root)
            root.destroy()
        except Exception:
            pass
        return

    stop_event = threading.Event()
    root = Tk()
    root.title("Store 小助手 · 实时监控面板")
    root.geometry("920x620")
    root.minsize(780, 520)
    root.resizable(True, True)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)

    palette = {
        "bg": "#0d101a",
        "card": "#14182a",
        "muted": "#96a2c6",
        "accent": "#f35b92",
    }
    root.configure(bg=palette["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Main.TFrame", background=palette["bg"])
    style.configure("Card.TFrame", background=palette["card"])
    style.configure("Title.TLabel", background=palette["card"], foreground="#f4f6ff", font=("Microsoft YaHei UI", 15, "bold"))
    style.configure("Subtitle.TLabel", background=palette["card"], foreground=palette["muted"], font=("Microsoft YaHei UI", 10))
    style.configure("Log.TLabelframe", background=palette["card"], foreground="#ced8ff", padding=12)
    style.configure("Log.TLabelframe.Label", background=palette["card"], foreground="#ced8ff")
    style.configure("Hint.TLabel", background=palette["bg"], foreground=palette["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("Danger.TButton", font=("Microsoft YaHei UI", 11, "bold"), foreground="#ffffff", background=palette["accent"], padding=10)
    style.map("Danger.TButton", background=[("active", "#ff77a8"), ("disabled", "#a5a5a5")], foreground=[("disabled", "#f5f5f5")])

    main_frame = ttk.Frame(root, padding=(18, 18, 18, 14), style="Main.TFrame")
    main_frame.grid(row=0, column=0, sticky="nsew")
    main_frame.rowconfigure(1, weight=1)
    main_frame.columnconfigure(0, weight=1)

    header_frame = ttk.Frame(main_frame, padding=(18, 18), style="Card.TFrame")
    header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))
    header_frame.columnconfigure(0, weight=1)
    status_label = ttk.Label(header_frame, text="正在监控飞书任务...", style="Title.TLabel")
    status_label.grid(row=0, column=0, sticky="w")
    ttk.Label(header_frame, text="日志区 + 控制区都在下方啦，窗口现在能自适应，绝不再遮挡～", style="Subtitle.TLabel").grid(
        row=1, column=0, sticky="w", pady=(6, 0)
    )

    log_frame = ttk.LabelFrame(main_frame, text="实时日志", style="Log.TLabelframe")
    log_frame.grid(row=1, column=0, sticky="nsew")
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)
    log_box = ScrolledText(
        log_frame,
        height=18,
        wrap="word",
        state="disabled",
        bg=palette["bg"],
        fg="#e3ebff",
        insertbackground="#e3ebff",
        relief="flat",
        font=("Consolas", 10),
    )
    log_box.grid(row=0, column=0, sticky="nsew")

    btn_frame = ttk.Frame(main_frame, padding=(0, 12, 0, 0), style="Main.TFrame")
    btn_frame.grid(row=2, column=0, sticky="ew")
    btn_frame.columnconfigure(0, weight=1)
    ttk.Label(btn_frame, text="想停就停，我这个小猫保镖随叫随到～", style="Hint.TLabel").grid(row=0, column=0, sticky="w")
    stop_btn = ttk.Button(btn_frame, text="停止任务", width=18, style="Danger.TButton")
    stop_btn.grid(row=0, column=1, sticky="e")

    def poll_log_queue() -> None:
        try:
            while True:
                line = LOG_QUEUE.get_nowait()
                log_box.configure(state="normal")
                log_box.insert("end", line + "\n")
                log_box.see("end")
                log_box.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(500, poll_log_queue)

    def stop_runner() -> None:
        stop_btn.config(state="disabled", text="正在停止...")
        status_label.config(text="正在停止，请稍候...")
        stop_event.set()
        # 守护线程 + 强制退出，避免第三方库挂起进程
        try:
            root.destroy()
        except Exception:
            pass
        os._exit(0)

    def on_close() -> None:
        stop_runner()

    stop_btn.config(command=stop_runner)
    root.protocol("WM_DELETE_WINDOW", on_close)

    worker = threading.Thread(target=run_bot, args=(stop_event, cfg), daemon=True)
    worker.start()

    poll_log_queue()
    root.mainloop()


if __name__ == "__main__":
    run_self_check()
    try:
        _start_gui()
    except Exception as exc:
        logger.critical(f"程序崩溃退出: {exc}")
        time.sleep(5)
        raise
