from __future__ import annotations

import os
import queue
from tkinter import Tk, messagebox, ttk
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
        self.root.geometry("920x620")
        self.root.minsize(780, 520)
        self.root.resizable(True, True)
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.status_label = None
        self.stop_btn = None
        self.log_box = None

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

        main_frame = ttk.Frame(self.root, padding=(18, 18, 18, 14), style="Main.TFrame")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

        header_frame = ttk.Frame(main_frame, padding=(18, 18), style="Card.TFrame")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header_frame.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(header_frame, text="正在监控飞书任务...", style="Title.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(
            header_frame,
            text="日志区 + 控制区都在下方啦",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        log_frame = ttk.LabelFrame(main_frame, text="实时日志", style="Log.TLabelframe")
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_box = ScrolledText(
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
        self.log_box.grid(row=0, column=0, sticky="nsew")

        btn_frame = ttk.Frame(main_frame, padding=(0, 12, 0, 0), style="Main.TFrame")
        btn_frame.grid(row=2, column=0, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)
        ttk.Label(btn_frame, text="想停就停", style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        self.stop_btn = ttk.Button(btn_frame, text="停止任务", width=18, style="Danger.TButton", command=self.stop)
        self.stop_btn.grid(row=0, column=1, sticky="e")

        self.root.protocol("WM_DELETE_WINDOW", self.stop)

    def run(self) -> None:
        self.engine.start()
        self._poll_log_queue()
        self.root.mainloop()

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

