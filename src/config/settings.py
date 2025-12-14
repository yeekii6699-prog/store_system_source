import configparser
import json
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv
from tkinter import BooleanVar, StringVar, Tk, Canvas, Toplevel, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# ============== 路径与配置文件定位 ==============
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parents[2]

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
        "WELCOME_STEPS": (os.getenv("WELCOME_STEPS") or default_section.get("WELCOME_STEPS", "")).strip(),
    }


def _prompt_full_config(defaults: Dict[str, str]) -> Tuple[Dict[str, str], bool]:
    """
    Tkinter 配置窗口：支持粘贴完整的飞书链接，并可选择是否保存到 config.ini。
    返回：用户输入的配置字典，以及是否记住配置的布尔值。
    """
    result: Dict[str, str] | None = None
    root = Tk()
    root.title("飞书/微信 配置")
    root.geometry("780x620")
    root.minsize(720, 520)
    root.resizable(True, True)
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

    def _normalize_step_data(data: Dict[str, str]) -> Dict[str, str] | None:
        action = (data.get("type") or "").strip().lower()
        if action == "text":
            content = (data.get("content") or "").strip()
            if content:
                return {"type": "text", "content": content}
        elif action == "image":
            path = (data.get("path") or "").strip()
            if path:
                return {"type": "image", "path": path}
        elif action == "link":
            url = (data.get("url") or "").strip()
            if url:
                step = {"type": "link", "url": url}
                title = (data.get("title") or "").strip()
                if title:
                    step["title"] = title
                return step
        return None

    welcome_steps: list[dict[str, str]] = []
    raw_steps = defaults.get("WELCOME_STEPS", "")
    if raw_steps:
        try:
            parsed = json.loads(raw_steps)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        normalized = _normalize_step_data(item)
                        if normalized:
                            welcome_steps.append(normalized)
        except json.JSONDecodeError:
            pass

    if not welcome_steps:
        legacy_text = defaults.get("WELCOME_TEXT", "").strip()
        if legacy_text:
            welcome_steps.append({"type": "text", "content": legacy_text})
        legacy_images = [
            item.strip()
            for item in defaults.get("WELCOME_IMAGE_PATHS", "").split(WELCOME_IMAGE_DELIMITER)
            if item.strip()
        ]
        for image in legacy_images:
            welcome_steps.append({"type": "image", "path": image})

    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)

    canvas = Canvas(container, highlightthickness=0)
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scroll_frame = ttk.Frame(canvas, padding=12)
    frame_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_frame_configure(event=None) -> None:  # noqa: ANN001
        canvas.configure(scrollregion=canvas.bbox("all"))

    scroll_frame.bind("<Configure>", _on_frame_configure)
    def _on_mousewheel(event):  # noqa: ANN001
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    canvas.bind(
        "<Configure>",
        lambda event: canvas.itemconfig(frame_window, width=event.width),
    )

    for idx, (key, label) in enumerate(field_labels.items()):
        ttk.Label(scroll_frame, text=label, anchor="w").grid(row=idx, column=0, sticky="w", pady=4)
        entry = ttk.Entry(scroll_frame, textvariable=field_vars[key], width=62, show="*" if key == "FEISHU_APP_SECRET" else "")
        entry.grid(row=idx, column=1, sticky="ew", pady=4)
        if key == "WECHAT_EXEC_PATH":
            def _browse_file(event=None):  # noqa: ANN001
                path = filedialog.askopenfilename(
                    title="选择 WeChat.exe",
                    filetypes=[("WeChat", "WeChat.exe"), ("可执行文件", "*.exe")],
                )
                if path:
                    field_vars["WECHAT_EXEC_PATH"].set(path)
            ttk.Button(scroll_frame, text="浏览...", command=_browse_file).grid(row=idx, column=2, padx=(6, 0), pady=4)
        if idx == 0:
            entry.focus_set()

    ttk.Checkbutton(scroll_frame, text="记住配置（写入 config.ini）", variable=remember_var).grid(
        row=len(field_labels), column=0, columnspan=2, sticky="w", pady=8
    )

    welcome_frame = ttk.LabelFrame(scroll_frame, text="首次欢迎包配置（可选）", padding=(10, 8))
    welcome_row = len(field_labels) + 1
    welcome_frame.grid(row=welcome_row, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    welcome_frame.columnconfigure(1, weight=1)

    ttk.Checkbutton(
        welcome_frame,
        text="启用加好友成功后自动发送门店指引",
        variable=welcome_enabled_var,
    ).grid(row=0, column=0, columnspan=3, sticky="w")

    type_labels = {"text": "文字", "image": "图片", "link": "链接"}

    steps_frame = ttk.Frame(welcome_frame)
    steps_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
    steps_frame.columnconfigure(0, weight=1)
    steps_frame.rowconfigure(0, weight=1)

    steps_columns = ("type", "detail")
    steps_tree = ttk.Treeview(steps_frame, columns=steps_columns, show="headings", selectmode="browse", height=6)
    steps_tree.heading("type", text="类型")
    steps_tree.heading("detail", text="内容 / 摘要")
    steps_tree.column("type", width=80, anchor="center")
    steps_tree.column("detail", width=420, anchor="w")
    steps_scroll = ttk.Scrollbar(steps_frame, orient="vertical", command=steps_tree.yview)
    steps_tree.configure(yscrollcommand=steps_scroll.set)
    steps_tree.grid(row=0, column=0, sticky="nsew")
    steps_scroll.grid(row=0, column=1, sticky="ns", padx=(4, 0))

    ttk.Label(
        welcome_frame,
        text="拖拽步骤即可换顺序，双击可编辑，支持文字/图片/链接多条内容灵活组合。",
        anchor="w",
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

    steps_btn_frame = ttk.Frame(welcome_frame)
    steps_btn_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Button(steps_btn_frame, text="新增步骤", command=lambda: _open_step_editor()).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(steps_btn_frame, text="编辑选中", command=lambda: _edit_selected_step()).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(steps_btn_frame, text="删除选中", command=lambda: _delete_selected_step()).grid(row=0, column=2)

    drag_state: dict[str, str | None] = {"item": None}

    def _step_summary(step: dict[str, str]) -> str:
        if step["type"] == "text":
            snippet = step.get("content", "")
            return (snippet[:40] + "…") if len(snippet) > 40 else snippet
        if step["type"] == "image":
            return Path(step.get("path", "")).name or step.get("path", "")
        if step["type"] == "link":
            title = step.get("title", "")
            url = step.get("url", "")
            return f"{title} | {url}" if title else url
        return ""

    def _refresh_steps_tree(select_index: int | None = None) -> None:
        for item in steps_tree.get_children():
            steps_tree.delete(item)
        for idx, step in enumerate(welcome_steps):
            steps_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(type_labels.get(step["type"], step["type"]), _step_summary(step)),
            )
        if select_index is not None and 0 <= select_index < len(welcome_steps):
            iid = str(select_index)
            steps_tree.selection_set(iid)
            steps_tree.focus(iid)

    def _selected_step_index() -> int | None:
        selection = steps_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except (ValueError, TypeError):
            return None

    def _open_step_editor(index: int | None = None) -> None:
        existing = welcome_steps[index] if index is not None else {"type": "text"}
        editor = Toplevel(root)
        editor.title("编辑欢迎步骤" if index is not None else "新增欢迎步骤")
        editor.geometry("420x360")
        editor.transient(root)
        editor.grab_set()

        type_var = StringVar(value=existing.get("type", "text"))
        ttk.Label(editor, text="发送类型").pack(anchor="w", padx=12, pady=(12, 4))
        combo_map = {
            type_labels["text"]: "text",
            type_labels["image"]: "image",
            type_labels["link"]: "link",
        }
        reverse_combo_map = {v: k for k, v in combo_map.items()}
        type_display_var = StringVar(value=reverse_combo_map.get(type_var.get(), type_labels["text"]))
        type_combo = ttk.Combobox(
            editor,
            state="readonly",
            textvariable=type_display_var,
            values=list(combo_map.keys()),
        )
        type_combo.pack(fill="x", padx=12)

        form_frame = ttk.Frame(editor, padding=12)
        form_frame.pack(fill="both", expand=True)

        text_frame = ttk.Frame(form_frame)
        ttk.Label(text_frame, text="文字内容").pack(anchor="w")
        text_widget = ScrolledText(text_frame, width=40, height=6, wrap="word")
        text_widget.insert("1.0", existing.get("content", ""))
        text_widget.pack(fill="both", expand=True, pady=(6, 0))

        image_frame = ttk.Frame(form_frame)
        ttk.Label(image_frame, text="图片路径").grid(row=0, column=0, sticky="w")
        image_path_var = StringVar(value=existing.get("path", ""))
        ttk.Entry(image_frame, textvariable=image_path_var).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        image_frame.columnconfigure(0, weight=1)

        def _browse_image() -> None:
            path = filedialog.askopenfilename(
                title="选择图片",
                filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"), ("所有文件", "*.*")],
            )
            if path:
                image_path_var.set(path)

        ttk.Button(image_frame, text="浏览...", command=_browse_image).grid(row=1, column=1, padx=(8, 0))

        link_frame = ttk.Frame(form_frame)
        ttk.Label(link_frame, text="链接标题").grid(row=0, column=0, sticky="w")
        link_title_var = StringVar(value=existing.get("title", ""))
        ttk.Entry(link_frame, textvariable=link_title_var).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        ttk.Label(link_frame, text="链接 URL").grid(row=2, column=0, sticky="w")
        link_url_var = StringVar(value=existing.get("url", ""))
        ttk.Entry(link_frame, textvariable=link_url_var).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        link_frame.columnconfigure(0, weight=1)

        def _sync_type_from_combo(*_) -> None:  # noqa: ANN001
            type_var.set(combo_map.get(type_display_var.get(), "text"))
            _show_form()

        type_display_var.trace_add("write", _sync_type_from_combo)

        def _show_form() -> None:
            for widget in (text_frame, image_frame, link_frame):
                widget.pack_forget()
            current = type_var.get()
            if current == "image":
                image_frame.pack(fill="x", expand=False)
            elif current == "link":
                link_frame.pack(fill="x", expand=False)
            else:
                text_frame.pack(fill="both", expand=True)

        def _save_step() -> None:
            current_type = type_var.get()
            if current_type == "image":
                path_value = image_path_var.get().strip()
                if not path_value:
                    messagebox.showerror("请完善信息", "请选择要发送的图片路径。", parent=editor)
                    return
                new_step = {"type": "image", "path": path_value}
            elif current_type == "link":
                url_value = link_url_var.get().strip()
                if not url_value:
                    messagebox.showerror("请完善信息", "请输入链接 URL。", parent=editor)
                    return
                title_value = link_title_var.get().strip()
                new_step = {"type": "link", "url": url_value}
                if title_value:
                    new_step["title"] = title_value
            else:
                content_value = text_widget.get("1.0", "end").strip()
                if not content_value:
                    messagebox.showerror("请完善信息", "文字内容不能为空。", parent=editor)
                    return
                new_step = {"type": "text", "content": content_value}

            if index is None:
                welcome_steps.append(new_step)
                target_index = len(welcome_steps) - 1
            else:
                welcome_steps[index] = new_step
                target_index = index
            _refresh_steps_tree(select_index=target_index)
            editor.destroy()

        def _cancel() -> None:
            editor.destroy()

        ttk.Frame(editor).pack(fill="x")
        action_bar = ttk.Frame(editor, padding=12)
        action_bar.pack(fill="x")
        ttk.Button(action_bar, text="保存", command=_save_step).pack(side="right", padx=(8, 0))
        ttk.Button(action_bar, text="取消", command=_cancel).pack(side="right")

        _show_form()
        editor.bind("<Return>", lambda event: _save_step())  # noqa: ANN001
        editor.protocol("WM_DELETE_WINDOW", _cancel)

    def _edit_selected_step() -> None:
        idx = _selected_step_index()
        if idx is None:
            messagebox.showinfo("提示", "请选择要编辑的步骤。", parent=root)
            return
        _open_step_editor(idx)

    def _delete_selected_step() -> None:
        idx = _selected_step_index()
        if idx is None:
            messagebox.showinfo("提示", "请选择要删除的步骤。", parent=root)
            return
        if messagebox.askyesno("确认删除", "确定要删除该步骤吗？", parent=root):
            welcome_steps.pop(idx)
            _refresh_steps_tree()

    def _on_tree_press(event) -> None:  # noqa: ANN001
        drag_state["item"] = steps_tree.identify_row(event.y) or None

    def _on_tree_release(event) -> None:  # noqa: ANN001
        if drag_state["item"] is None:
            return
        try:
            start_index = int(drag_state["item"])
        except (TypeError, ValueError):
            drag_state["item"] = None
            return
        if not welcome_steps:
            drag_state["item"] = None
            return
        target_row = steps_tree.identify_row(event.y)
        if target_row:
            target_index = int(target_row)
        else:
            children = steps_tree.get_children()
            if children:
                first_bbox = steps_tree.bbox(children[0])
                if first_bbox and event.y < first_bbox[1]:
                    target_index = 0
                else:
                    target_index = len(welcome_steps)
            else:
                target_index = 0
        if target_index < 0:
            target_index = 0
        if start_index == target_index:
            drag_state["item"] = None
            return
        step = welcome_steps.pop(start_index)
        if start_index < target_index:
            target_index -= 1
        target_index = max(0, min(target_index, len(welcome_steps)))
        welcome_steps.insert(target_index, step)
        drag_state["item"] = None
        _refresh_steps_tree(select_index=target_index)

    steps_tree.bind("<ButtonPress-1>", _on_tree_press)
    steps_tree.bind("<ButtonRelease-1>", _on_tree_release)
    steps_tree.bind("<Double-1>", lambda event: _edit_selected_step())  # noqa: ANN001
    _refresh_steps_tree()

    required_keys = {"FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_PROFILE_TABLE_URL", "FEISHU_TABLE_URL"}

    def _submit(event=None) -> None:  # noqa: ANN001
        nonlocal result
        values = {k: v.get().strip() for k, v in field_vars.items()}
        missing = [label for key, label in field_labels.items() if key in required_keys and not values.get(key)]
        if missing:
            messagebox.showerror("????", f"???: {', '.join(missing)}")
            return
        if welcome_enabled_var.get() and not welcome_steps:
            messagebox.showerror("请完善欢迎步骤", "请至少添加一个欢迎步骤后再开启自动欢迎功能。")
            return
        values["WELCOME_ENABLED"] = "1" if welcome_enabled_var.get() else "0"
        values["WELCOME_TEXT"] = ""
        values["WELCOME_IMAGE_PATHS"] = ""
        values["WELCOME_STEPS"] = json.dumps(welcome_steps, ensure_ascii=False)
        result = values
        root.destroy()

    def _on_close() -> None:
        root.destroy()

    btn = ttk.Button(scroll_frame, text="保存并启动", command=_submit)
    btn.grid(row=welcome_row + 1, column=0, columnspan=3, pady=8)

    root.bind("<Return>", _submit)
    root.protocol("WM_DELETE_WINDOW", _on_close)
    scroll_frame.columnconfigure(1, weight=1)

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
