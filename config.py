import configparser
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# ============== 路径与配置文件定位 ==============
if getattr(sys, "frozen", False):
    # PyInstaller 打包后的 exe 所在目录
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # 源码运行
    BASE_DIR = Path(__file__).resolve().parent

ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.ini"
WELCOME_IMAGE_DELIMITER = "|"

# 尝试加载 .env（保留对旧配置方式的兼容）
load_dotenv(ENV_PATH)

_config = configparser.ConfigParser()
if CONFIG_PATH.exists():
    _config.read(CONFIG_PATH, encoding="utf-8")
if "DEFAULT" not in _config:
    _config["DEFAULT"] = {}


# ============== 基础工具函数 ==============
def _save_config() -> None:
    """写回 config.ini，供下次启动使用。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        _config.write(f)


def auto_detect_wechat_path() -> str:
    """
    尝试通过注册表或常见安装目录自动发现 WeChat.exe。
    未找到则返回空字符串。
    """
    candidates: list[Path] = []
    try:
        import winreg  # type: ignore

        reg_locations = [
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Tencent\WeChat"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat"),
        ]
        for hive, sub_key in reg_locations:
            try:
                with winreg.OpenKey(hive, sub_key) as key:
                    install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                    if install_path:
                        candidates.append(Path(install_path) / "WeChat.exe")
            except FileNotFoundError:
                continue
    except Exception:
        # 非 Windows 或无法读取注册表时忽略
        pass

    program_files = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    candidates.append(program_files / "Tencent" / "WeChat" / "WeChat.exe")
    program_files64 = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates.append(program_files64 / "Tencent" / "WeChat" / "WeChat.exe")

    for cand in candidates:
        if cand.exists():
            return str(cand)
    return ""


def _collect_defaults() -> Dict[str, str]:
    """
    汇总环境变量或 config.ini 中已有的值，用于界面预填。
    优先级：环境变量 > config.ini > 空。
    """
    default_section = _config["DEFAULT"]
    detected_wechat = auto_detect_wechat_path()
    return {
        "FEISHU_APP_ID": (os.getenv("FEISHU_APP_ID") or default_section.get("FEISHU_APP_ID", "")).strip(),
        "FEISHU_APP_SECRET": (os.getenv("FEISHU_APP_SECRET") or default_section.get("FEISHU_APP_SECRET", "")).strip(),
        "FEISHU_TABLE_URL": (os.getenv("FEISHU_TABLE_URL") or default_section.get("FEISHU_TABLE_URL", "")).strip(),
        "FEISHU_PROFILE_TABLE_URL": (os.getenv("FEISHU_PROFILE_TABLE_URL") or default_section.get("FEISHU_PROFILE_TABLE_URL", "")).strip(),
        "WECHAT_EXEC_PATH": (
            os.getenv("WECHAT_EXEC_PATH")
            or default_section.get("WECHAT_EXEC_PATH", "")
            or detected_wechat
            or ""
        ).strip(),
        "WELCOME_ENABLED": (os.getenv("WELCOME_ENABLED") or default_section.get("WELCOME_ENABLED", "0")).strip(),
        "WELCOME_TEXT": (os.getenv("WELCOME_TEXT") or default_section.get("WELCOME_TEXT", "")).strip(),
        "WELCOME_IMAGE_PATHS": (
            os.getenv("WELCOME_IMAGE_PATHS") or default_section.get("WELCOME_IMAGE_PATHS", "")
        ).strip(),
    }


def _prompt_full_config(defaults: Dict[str, str]) -> Tuple[Dict[str, str], bool]:
    """
    Tkinter 配置窗口：支持粘贴完整的飞书链接，并可选择是否保存到 config.ini。
    返回：用户输入的配置字典，以及是否记住配置的布尔值。
    """
    result: Dict[str, str] | None = None
    root = Tk()
    root.title("飞书/微信 配置")
    root.geometry("620x320")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    field_labels = {
        "FEISHU_APP_ID": "飞书 App ID",
        "FEISHU_APP_SECRET": "飞书 App Secret",
        "FEISHU_PROFILE_TABLE_URL": "客户表链接 (资料表)",
        "FEISHU_TABLE_URL": "预约表链接 (任务表)",
        "WECHAT_EXEC_PATH": "PC微信启动路径",
    }

    field_vars: Dict[str, StringVar] = {
        key: StringVar(value=defaults.get(key, "")) for key in field_labels
    }
    remember_var = BooleanVar(value=CONFIG_PATH.exists())
    welcome_enabled_var = BooleanVar(value=defaults.get("WELCOME_ENABLED", "0") == "1")
    welcome_text_default = defaults.get("WELCOME_TEXT", "")
    welcome_images: list[str] = [
        item.strip()
        for item in defaults.get("WELCOME_IMAGE_PATHS", "").split(WELCOME_IMAGE_DELIMITER)
        if item.strip()
    ]

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    for idx, (key, label) in enumerate(field_labels.items()):
        ttk.Label(frame, text=label, anchor="w").grid(row=idx, column=0, sticky="w", pady=4)
        entry = ttk.Entry(frame, textvariable=field_vars[key], width=62, show="*" if key == "FEISHU_APP_SECRET" else "")
        entry.grid(row=idx, column=1, sticky="ew", pady=4)
        if key == "WECHAT_EXEC_PATH":
            def _browse_file(event=None):  # noqa: ANN001
                path = filedialog.askopenfilename(
                    title="选择 WeChat.exe",
                    filetypes=[("WeChat", "WeChat.exe"), ("可执行文件", "*.exe")],
                )
                if path:
                    field_vars["WECHAT_EXEC_PATH"].set(path)
            ttk.Button(frame, text="浏览...", command=_browse_file).grid(row=idx, column=2, padx=(6, 0), pady=4)
        if idx == 0:
            entry.focus_set()

    ttk.Checkbutton(frame, text="记住配置（写入 config.ini）", variable=remember_var).grid(
        row=len(field_labels), column=0, columnspan=2, sticky="w", pady=8
    )

    welcome_frame = ttk.LabelFrame(frame, text="首次欢迎包配置（可选）", padding=(10, 8))
    welcome_row = len(field_labels) + 1
    welcome_frame.grid(row=welcome_row, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    welcome_frame.columnconfigure(1, weight=1)

    ttk.Checkbutton(
        welcome_frame,
        text="启用加好友成功后自动发送门店指引",
        variable=welcome_enabled_var,
    ).grid(row=0, column=0, columnspan=3, sticky="w")

    ttk.Label(welcome_frame, text="欢迎文案").grid(row=1, column=0, sticky="nw", pady=(6, 0))
    welcome_text_widget = ScrolledText(welcome_frame, width=50, height=4, wrap="word")
    welcome_text_widget.insert("1.0", welcome_text_default)
    welcome_text_widget.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))

    ttk.Label(welcome_frame, text="图片附件").grid(row=2, column=0, sticky="nw", pady=(8, 0))
    images_label = ttk.Label(welcome_frame, text="", anchor="w", justify="left")
    images_label.grid(row=2, column=1, sticky="ew", pady=(8, 0))

    def _refresh_images_label() -> None:
        if not welcome_images:
            images_label.config(text="未选择任何图片")
            return
        preview = [Path(p).name for p in welcome_images[:3]]
        extra = ""
        if len(welcome_images) > 3:
            extra = f"... 共 {len(welcome_images)} 张"
        images_label.config(text="\n".join(preview) + (f"\n{extra}" if extra else ""))

    def _add_images() -> None:
        files = filedialog.askopenfilenames(
            title="选择欢迎图集",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"), ("所有文件", "*.*")],
        )
        if not files:
            return
        welcome_images.extend([str(Path(f)) for f in files])
        _refresh_images_label()

    def _clear_images() -> None:
        welcome_images.clear()
        _refresh_images_label()

    ttk.Button(welcome_frame, text="添加图片...", command=_add_images).grid(row=2, column=2, padx=(6, 0), pady=(8, 0))
    ttk.Button(welcome_frame, text="清空", command=_clear_images).grid(row=3, column=2, padx=(6, 0), pady=(4, 0))
    _refresh_images_label()

    required_keys = {"FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_PROFILE_TABLE_URL", "FEISHU_TABLE_URL"}

    def _submit(event=None) -> None:  # noqa: ANN001
        nonlocal result
        values = {k: v.get().strip() for k, v in field_vars.items()}
        missing = [label for key, label in field_labels.items() if key in required_keys and not values.get(key)]
        if missing:
            messagebox.showerror("????", f"???: {', '.join(missing)}")
            return
        welcome_text_value = welcome_text_widget.get("1.0", "end").strip()
        values["WELCOME_ENABLED"] = "1" if welcome_enabled_var.get() else "0"
        values["WELCOME_TEXT"] = welcome_text_value
        values["WELCOME_IMAGE_PATHS"] = WELCOME_IMAGE_DELIMITER.join(welcome_images)
        result = values
        root.destroy()

    def _on_close() -> None:
        root.destroy()

    btn = ttk.Button(frame, text="保存并启动", command=_submit)
    btn.grid(row=welcome_row + 1, column=0, columnspan=3, pady=8)

    root.bind("<Return>", _submit)
    root.protocol("WM_DELETE_WINDOW", _on_close)
    frame.columnconfigure(1, weight=1)

    root.mainloop()
    if result is None:
        raise RuntimeError("未完成配置输入，程序已退出")
    return result, bool(remember_var.get())


def _get_config_value(key: str, default: str | None = None, required: bool = False) -> str:
    """
    优先读环境变量，其次 config.ini，最后使用默认值。
    required=True 时会在缺失时抛出异常。
    """
    value = os.getenv(key)
    if not value:
        value = _config["DEFAULT"].get(key, "").strip()
    if not value and default is not None:
        value = default
    if required and not value:
        raise RuntimeError(f"缺少必要配置: {key}")
    return value


def _ensure_full_config() -> Dict[str, str]:
    """
    弹出界面收集配置，支持“记住配置”写入 config.ini。
    若设置环境变量 SKIP_CONFIG_UI=1 且必填项已存在，则跳过界面直接返回。
    """
    cfg = _collect_defaults()
    required_keys = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_TABLE_URL",
        "FEISHU_PROFILE_TABLE_URL",
    ]
    skip_ui = os.getenv("SKIP_CONFIG_UI") == "1"
    if not skip_ui or any(not cfg.get(k) for k in required_keys):
        filled, remember = _prompt_full_config(cfg)
        cfg.update(filled)
        if remember:
            for key, value in cfg.items():
                _config["DEFAULT"][key] = value
            _save_config()
        else:
            _config["DEFAULT"].clear()
            CONFIG_PATH.unlink(missing_ok=True)
    return cfg


_cfg_cache: Dict[str, str] | None = None


def get_config() -> Dict[str, str]:
    """
    懒加载配置，首次调用时才弹出界面或读取文件。
    """
    global _cfg_cache  # noqa: PLW0603
    if _cfg_cache is None:
        _cfg_cache = _ensure_full_config()
    return _cfg_cache
