import configparser
import os
import sys
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv
from tkinter import Tk, simpledialog

# ============== 路径与配置文件定位 ==============
if getattr(sys, "frozen", False):
    # PyInstaller 打包后的 exe 所在目录
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # 源码运行
    BASE_DIR = Path(__file__).resolve().parent

ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.ini"

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


def _prompt_credentials() -> Tuple[str, str]:
    """
    通过 Tk 简单弹窗收集飞书凭据。
    会创建一个隐藏的 root 窗口，再使用 simpledialog 询问。
    """
    root = Tk()
    root.withdraw()
    app_id = simpledialog.askstring("飞书配置", "请输入 FEISHU_APP_ID", parent=root) or ""
    app_secret = simpledialog.askstring(
        "飞书配置", "请输入 FEISHU_APP_SECRET", parent=root, show="*"
    ) or ""
    root.destroy()
    return app_id.strip(), app_secret.strip()


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


def _ensure_credentials() -> Tuple[str, str]:
    """
    保证 FEISHU_APP_ID / FEISHU_APP_SECRET 有值；
    若缺失则弹窗提示用户输入，并写入 config.ini。
    """
    app_id = os.getenv("FEISHU_APP_ID") or _config["DEFAULT"].get("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET") or _config["DEFAULT"].get("FEISHU_APP_SECRET", "").strip()

    if not app_id or not app_secret:
        app_id, app_secret = _prompt_credentials()
        if not app_id or not app_secret:
            raise RuntimeError("缺少飞书凭据，请重新运行并输入 FEISHU_APP_ID/FEISHU_APP_SECRET")
        _config["DEFAULT"]["FEISHU_APP_ID"] = app_id
        _config["DEFAULT"]["FEISHU_APP_SECRET"] = app_secret
        _save_config()

    return app_id, app_secret


# ============== 对外暴露的配置变量 ==============
FEISHU_APP_ID, FEISHU_APP_SECRET = _ensure_credentials()
FEISHU_TABLE_URL = _get_config_value("FEISHU_TABLE_URL", required=True)
FEISHU_PROFILE_TABLE_URL = _get_config_value("FEISHU_PROFILE_TABLE_URL", required=True)
WECHAT_EXEC_PATH = _get_config_value("WECHAT_EXEC_PATH", required=True)
