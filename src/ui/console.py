from __future__ import annotations

import os
import queue
from tkinter import Tk, messagebox, ttk, StringVar, BooleanVar
from tkinter.scrolledtext import ScrolledText

from loguru import logger

from src.core.engine import TaskEngine


class ConsoleApp:
    """Tk-based console that visualizes logs and controls the task engine."""

    def __init__(self, engine: TaskEngine) -> None:
        self.engine = engine
        self.log_queue: "queue.Queue[str]" = queue.Queue(maxsize=500)
        self._log_sink_id = logger.add(self._queue_sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

        self.root = Tk()
        self.root.title("明星 小助手 · 实时监控面板")
        self.root.geometry("1000x700")
        self.root.minsize(900, 580)
        self.root.resizable(True, True)
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.status_label = None
        self.stop_btn = None
        self.log_box_active = None  # 主动加好友日志
        self.log_box_passive = None  # 被动加好友日志
        self.pause_btn = None
        self.welcome_var = None
        self._build_ui()

    def _queue_sink(self, message) -> None:  # type: ignore[override]
        try:
            self.log_queue.put_nowait(str(message).rstrip("\n"))
        except Exception:
            pass

    def _build_ui(self) -> None:
        palette = {
            "bg": "#0d101a",
            "card": "#14182a",
            "muted": "#96a2c6",
            "accent": "#f35b92",
            "success": "#4ade80",
            "warning": "#fbbf24",
            "danger": "#ef4444",
        }
        self.root.configure(bg=palette["bg"])

        style = ttk.Style(self.root)
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
        style.configure("Pause.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="#ffffff", background=palette["warning"], padding=8)
        style.map("Pause.TButton", background=[("active", "#fbbf24"), ("disabled", "#a5a5a5")])

        main_frame = ttk.Frame(self.root, padding=(18, 18, 18, 14), style="Main.TFrame")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # ===== 顶部状态栏 =====
        header_frame = ttk.Frame(main_frame, padding=(18, 18), style="Card.TFrame")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header_frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(header_frame, text="正在监控飞书任务...", style="Title.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")

        # ===== 配置控制区 =====
        control_frame = ttk.Frame(main_frame, padding=(18, 12), style="Card.TFrame")
        control_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)

        # 左侧：监控设置
        settings_left = ttk.Frame(control_frame, style="Card.TFrame")
        settings_left.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        # 新的好友监控频率
        interval_frame = ttk.Frame(settings_left, style="Card.TFrame")
        interval_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(interval_frame, text="新的好友监控:", style="Subtitle.TLabel").pack(side="left")
        self.interval_var = StringVar(value=str(int(self.engine.passive_scan_interval)))
        self.interval_entry = ttk.Entry(interval_frame, textvariable=self.interval_var, width=6, font=("Microsoft YaHei UI", 10))
        self.interval_entry.pack(side="left", padx=(8, 4))
        ttk.Label(interval_frame, text="秒 (5-300)", style="Hint.TLabel").pack(side="left")
        ttk.Button(interval_frame, text="应用", width=6, command=self._apply_monitor_interval).pack(side="left", padx=(8, 0))

        # 飞书轮询频率
        feishu_frame = ttk.Frame(settings_left, style="Card.TFrame")
        feishu_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(feishu_frame, text="飞书轮询频率:", style="Subtitle.TLabel").pack(side="left")
        self.feishu_poll_var = StringVar(value=str(int(self.engine.feishu_poll_interval)))
        self.feishu_poll_entry = ttk.Entry(feishu_frame, textvariable=self.feishu_poll_var, width=6, font=("Microsoft YaHei UI", 10))
        self.feishu_poll_entry.pack(side="left", padx=(8, 4))
        ttk.Label(feishu_frame, text="秒 (3-60)", style="Hint.TLabel").pack(side="left")
        ttk.Button(feishu_frame, text="应用", width=6, command=self._apply_feishu_poll_interval).pack(side="left", padx=(8, 0))

        # 扫描抖动
        jitter_frame = ttk.Frame(settings_left, style="Card.TFrame")
        jitter_frame.pack(fill="x")
        ttk.Label(jitter_frame, text="扫描抖动时间:", style="Subtitle.TLabel").pack(side="left")
        self.jitter_var = StringVar(value=str(int(self.engine.passive_scan_jitter)))
        self.jitter_entry = ttk.Entry(jitter_frame, textvariable=self.jitter_var, width=6, font=("Microsoft YaHei UI", 10))
        self.jitter_entry.pack(side="left", padx=(8, 4))
        ttk.Label(jitter_frame, text="秒 (0-30)", style="Hint.TLabel").pack(side="left")
        ttk.Button(jitter_frame, text="应用", width=6, command=self._apply_jitter).pack(side="left", padx=(8, 0))

        # 右侧：统计面板
        stats_frame = ttk.LabelFrame(control_frame, text="运行统计", padding=(16, 12), style="Log.TLabelframe")
        stats_frame.grid(row=0, column=1, sticky="ew")
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(2, weight=1)

        # 申请数
        self.apply_count_label = ttk.Label(stats_frame, text="0", font=("Microsoft YaHei UI", 24, "bold"), foreground=palette["success"], background=palette["card"])
        self.apply_count_label.grid(row=0, column=0)
        ttk.Label(stats_frame, text="已申请", style="Hint.TLabel").grid(row=1, column=0)

        # 欢迎数
        self.welcome_count_label = ttk.Label(stats_frame, text="0", font=("Microsoft YaHei UI", 24, "bold"), foreground=palette["accent"], background=palette["card"])
        self.welcome_count_label.grid(row=0, column=1)
        ttk.Label(stats_frame, text="已欢迎", style="Hint.TLabel").grid(row=1, column=1)

        # 失败数
        self.fail_count_label = ttk.Label(stats_frame, text="0", font=("Microsoft YaHei UI", 24, "bold"), foreground=palette["danger"], background=palette["card"])
        self.fail_count_label.grid(row=0, column=2)
        ttk.Label(stats_frame, text="失败", style="Hint.TLabel").grid(row=1, column=2)

        # ===== 欢迎包开关和暂停按钮 =====
        bottom_frame = ttk.Frame(main_frame, padding=(0, 8), style="Main.TFrame")
        bottom_frame.grid(row=2, column=0, sticky="ew")
        bottom_frame.columnconfigure(0, weight=1)

        # 欢迎包开关
        self.welcome_var = BooleanVar(value=self.engine.welcome_enabled)
        welcome_check = ttk.Checkbutton(
            bottom_frame,
            text="启用欢迎包",
            variable=self.welcome_var,
            command=self._toggle_welcome
        )
        welcome_check.grid(row=0, column=0, sticky="w")

        # 暂停/继续按钮
        self.pause_btn = ttk.Button(
            bottom_frame,
            text="⏸️ 暂停",
            width=12,
            style="Pause.TButton",
            command=self._toggle_pause
        )
        self.pause_btn.grid(row=0, column=1, sticky="e", padx=(0, 12))

        # 停止按钮
        self.stop_btn = ttk.Button(bottom_frame, text="停止任务", width=18, style="Danger.TButton", command=self.stop)
        self.stop_btn.grid(row=0, column=2, sticky="e")

        # ===== 日志区 =====
        log_frame = ttk.LabelFrame(main_frame, text="实时日志", style="Log.TLabelframe")
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_box = ScrolledText(
            log_frame,
            height=16,
            wrap="word",
            state="disabled",
            bg=palette["bg"],
            fg="#e3ebff",
            insertbackground="#e3ebff",
            relief="flat",
            font=("Consolas", 10),
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")

        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        # 启动统计更新定时器
        self._update_stats()

    def _apply_monitor_interval(self) -> None:
        """应用监控频率设置"""
        try:
            if self.interval_entry:
                value = self.interval_entry.get().strip()
                seconds = float(value)
                if seconds >= 5 and seconds <= 300:
                    self.engine.set_monitor_interval(seconds)
                    self._log_message(f"✅ 监控频率已更新: {seconds}秒")
                else:
                    messagebox.showwarning("输入无效", "请输入5-300之间的数值")
        except ValueError:
            messagebox.showwarning("输入无效", "请输入有效的数字")

    def _apply_feishu_poll_interval(self) -> None:
        """应用飞书轮询频率设置"""
        try:
            if self.feishu_poll_entry:
                value = self.feishu_poll_entry.get().strip()
                seconds = float(value)
                if seconds >= 3 and seconds <= 60:
                    self.engine.set_feishu_poll_interval(seconds)
                    self._log_message(f"✅ 飞书轮询频率已更新: {seconds}秒")
                else:
                    messagebox.showwarning("输入无效", "请输入3-60之间的数值")
        except ValueError:
            messagebox.showwarning("输入无效", "请输入有效的数字")

    def _apply_jitter(self) -> None:
        """应用扫描抖动设置"""
        try:
            if self.jitter_entry:
                value = self.jitter_entry.get().strip()
                seconds = float(value)
                if seconds >= 0 and seconds <= 30:
                    self.engine.set_jitter(seconds)
                    self._log_message(f"✅ 扫描抖动已更新: {seconds}秒")
                else:
                    messagebox.showwarning("输入无效", "请输入0-30之间的数值")
        except ValueError:
            messagebox.showwarning("输入无效", "请输入有效的数字")

    def _toggle_welcome(self) -> None:
        """切换欢迎包开关"""
        self.engine.toggle_welcome(self.welcome_var.get())
        status = "启用" if self.welcome_var.get() else "禁用"
        self._log_message(f"✅ 欢迎包功能已{status}")

    def _toggle_pause(self) -> None:
        """暂停/继续监控"""
        if self.engine.is_paused():
            # 当前是暂停状态，点击继续
            if self.engine.resume():
                self.pause_btn.config(text="⏸️ 暂停")
                self._log_message("▶️ 监控已继续")
        else:
            # 当前是运行状态，点击暂停
            if self.engine.pause():
                self.pause_btn.config(text="▶️ 继续")
                self._log_message("⏸️ 监控已暂停")

    def _update_stats(self) -> None:
        """定时更新统计显示"""
        if hasattr(self, 'apply_count_label'):
            self.apply_count_label.config(text=str(self.engine.apply_count))
        if hasattr(self, 'welcome_count_label'):
            self.welcome_count_label.config(text=str(self.engine.welcome_count))
        if hasattr(self, 'fail_count_label'):
            self.fail_count_label.config(text=str(self.engine.fail_count))
        # 继续定时更新
        self.root.after(500, self._update_stats)

    def _log_message(self, message: str) -> None:
        """向日志框输出一条消息"""
        if self.log_box:
            self.log_box.configure(state="normal")
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_box.insert("end", f"{timestamp} | INFO | {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

    def run(self) -> None:
        try:
            self.engine.start()
            self._poll_log_queue()
            self.root.mainloop()
        except RuntimeError as e:
            error_msg = str(e)
            if "飞书" in error_msg or "网络" in error_msg or "SSL" in error_msg:
                self._show_critical_error("服务连接错误", error_msg)
            else:
                self._show_critical_error("程序启动错误", error_msg)
        except Exception as e:
            self._show_critical_error("未知错误", f"程序启动时发生未知错误：{e}")

    def _show_critical_error(self, title: str, message: str) -> None:
        """显示严重错误对话框并退出程序"""
        try:
            import tkinter.messagebox as messagebox

            if not hasattr(self, 'root') or not self.root:
                temp_root = Tk()
                temp_root.withdraw()
                messagebox.showerror(title, message)
                temp_root.destroy()
            else:
                messagebox.showerror(title, message)
        except Exception:
            print(f"严重错误 [{title}]: {message}")

        import sys
        sys.exit(1)

    def stop(self) -> None:
        if self.stop_btn:
            self.stop_btn.config(state="disabled", text="正在停止...")
        if self.status_label:
            self.status_label.config(text="正在停止，请稍候...")
        self.engine.stop()
        try:
            logger.remove(self._log_sink_id)
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if self.log_box:
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", line + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(500, self._poll_log_queue)

    @staticmethod
    def show_env_error(errors: list[str]) -> None:
        """Display environment check failures with a blocking messagebox."""
        root = Tk()
        root.withdraw()
        messagebox.showerror("环境检查失败！", "\n".join(errors), parent=root)
        root.destroy()
