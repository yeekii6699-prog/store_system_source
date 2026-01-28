import configparser
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

WELCOME_IMAGE_DELIMITER = "|"

# ============== 路径与配置文件定位 ==============
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)

ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.ini"

# 尝试加载 .env
load_dotenv(ENV_PATH)

_config = configparser.ConfigParser()
if CONFIG_PATH.exists():
    _config.read(CONFIG_PATH, encoding="utf-8")
if "DEFAULT" not in _config:
    _config["DEFAULT"] = {}


FIELD_LABELS: Dict[str, str] = {
    "FEISHU_APP_ID": "飞书 App ID",
    "FEISHU_APP_SECRET": "飞书 App Secret",
    "FEISHU_PROFILE_TABLE_URL": "客户表链接 (资料表)",
    "FEISHU_TABLE_URL": "预约表链接 (任务表)",
    "WECHAT_EXEC_PATH": "PC 微信启动路径",
    "NETWORK_PROXY": "手动代理地址",
    "NETWORK_USE_SYSTEM_PROXY": "使用系统代理",
    "NETWORK_VERIFY_SSL": "验证 SSL 证书",
    "NETWORK_TIMEOUT": "网络超时（秒）",
    "FEISHU_RATE_LIMIT_COOLDOWN": "飞书频控冷却（秒）",
    "RPA_DELAY_MIN": "RPA 操作最小延迟（秒）",
    "RPA_DELAY_MAX": "RPA 操作最大延迟（秒）",
    "LOG_RETENTION_DAYS": "日志保留天数",
    "LOG_LEVEL": "日志级别",
    "FEISHU_WEBHOOK_URL": "飞书告警 Webhook",
    "ALERT_COOLDOWN": "告警推送冷却（秒）",
    "WELCOME_STEP_DELAY": "欢迎步骤间隔（秒）",
    "WELCOME_RETRY_COUNT": "欢迎失败重试次数",
    "MONITOR_KEYWORDS": "监控关键词（逗号分隔）",
    "MAX_CHATS": "最大聊天窗口数",
    "RELATIONSHIP_DETECT_TIMEOUT": "关系检测超时（秒）",
    "PROFILE_WAIT_TIMEOUT": "资料卡等待超时（秒）",
    "BUTTON_FIND_TIMEOUT": "按钮查找超时（秒）",
}

REQUIRED_KEYS: List[str] = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_PROFILE_TABLE_URL",
    "FEISHU_TABLE_URL",
]


def _save_config() -> None:
    """写回 config.ini，供下次启动使用。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        _config.write(f)


def auto_detect_wechat_path() -> str:
    """
    通过注册表或常见安装目录自动发现 WeChat.exe。
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
    汇总环境变量或 config.ini 的值，用于界面预填。
    优先级：环境变量 > config.ini > 空
    """
    default_section = _config["DEFAULT"]
    detected_wechat = auto_detect_wechat_path()
    return {
        "FEISHU_APP_ID": (
            os.getenv("FEISHU_APP_ID") or default_section.get("FEISHU_APP_ID", "")
        ).strip(),
        "FEISHU_APP_SECRET": (
            os.getenv("FEISHU_APP_SECRET")
            or default_section.get("FEISHU_APP_SECRET", "")
        ).strip(),
        "FEISHU_TABLE_URL": (
            os.getenv("FEISHU_TABLE_URL") or default_section.get("FEISHU_TABLE_URL", "")
        ).strip(),
        "FEISHU_PROFILE_TABLE_URL": (
            os.getenv("FEISHU_PROFILE_TABLE_URL")
            or default_section.get("FEISHU_PROFILE_TABLE_URL", "")
        ).strip(),
        "WECHAT_EXEC_PATH": (
            os.getenv("WECHAT_EXEC_PATH")
            or default_section.get("WECHAT_EXEC_PATH", "")
            or detected_wechat
            or ""
        ).strip(),
        "WELCOME_ENABLED": (
            os.getenv("WELCOME_ENABLED") or default_section.get("WELCOME_ENABLED", "0")
        ).strip(),
        "WELCOME_TEXT": (
            os.getenv("WELCOME_TEXT") or default_section.get("WELCOME_TEXT", "")
        ).strip(),
        "WELCOME_IMAGE_PATHS": (
            os.getenv("WELCOME_IMAGE_PATHS")
            or default_section.get("WELCOME_IMAGE_PATHS", "")
        ).strip(),
        "WELCOME_STEPS": (
            os.getenv("WELCOME_STEPS") or default_section.get("WELCOME_STEPS", "")
        ).strip(),
        "NEW_FRIEND_SCAN_INTERVAL": (
            os.getenv("NEW_FRIEND_SCAN_INTERVAL")
            or default_section.get("NEW_FRIEND_SCAN_INTERVAL", "30")
        ).strip(),
        "PASSIVE_SCAN_JITTER": (
            os.getenv("PASSIVE_SCAN_JITTER")
            or default_section.get("PASSIVE_SCAN_JITTER", "5")
        ).strip(),
        "FEISHU_POLL_INTERVAL": (
            os.getenv("FEISHU_POLL_INTERVAL")
            or default_section.get("FEISHU_POLL_INTERVAL", "5")
        ).strip(),
        "NETWORK_PROXY": (
            os.getenv("NETWORK_PROXY") or default_section.get("NETWORK_PROXY", "")
        ).strip(),
        "NETWORK_VERIFY_SSL": (
            os.getenv("NETWORK_VERIFY_SSL")
            or default_section.get("NETWORK_VERIFY_SSL", "1")
        ).strip(),
        "NETWORK_TIMEOUT": (
            os.getenv("NETWORK_TIMEOUT") or default_section.get("NETWORK_TIMEOUT", "15")
        ).strip(),
        "NETWORK_USE_SYSTEM_PROXY": (
            os.getenv("NETWORK_USE_SYSTEM_PROXY")
            or default_section.get("NETWORK_USE_SYSTEM_PROXY", "0")
        ).strip(),
        "FEISHU_RATE_LIMIT_COOLDOWN": (
            os.getenv("FEISHU_RATE_LIMIT_COOLDOWN")
            or default_section.get("FEISHU_RATE_LIMIT_COOLDOWN", "0.3")
        ).strip(),
        "RPA_DELAY_MIN": (
            os.getenv("RPA_DELAY_MIN") or default_section.get("RPA_DELAY_MIN", "0.5")
        ).strip(),
        "RPA_DELAY_MAX": (
            os.getenv("RPA_DELAY_MAX") or default_section.get("RPA_DELAY_MAX", "1.5")
        ).strip(),
        "LOG_RETENTION_DAYS": (
            os.getenv("LOG_RETENTION_DAYS")
            or default_section.get("LOG_RETENTION_DAYS", "7")
        ).strip(),
        "LOG_LEVEL": (
            os.getenv("LOG_LEVEL") or default_section.get("LOG_LEVEL", "INFO")
        ).strip(),
        "FEISHU_WEBHOOK_URL": (
            os.getenv("FEISHU_WEBHOOK_URL")
            or default_section.get("FEISHU_WEBHOOK_URL", "")
        ).strip(),
        "ALERT_COOLDOWN": (
            os.getenv("ALERT_COOLDOWN") or default_section.get("ALERT_COOLDOWN", "60")
        ).strip(),
        "WELCOME_STEP_DELAY": (
            os.getenv("WELCOME_STEP_DELAY")
            or default_section.get("WELCOME_STEP_DELAY", "1.0")
        ).strip(),
        "WELCOME_RETRY_COUNT": (
            os.getenv("WELCOME_RETRY_COUNT")
            or default_section.get("WELCOME_RETRY_COUNT", "0")
        ).strip(),
        "MONITOR_KEYWORDS": (
            os.getenv("MONITOR_KEYWORDS") or default_section.get("MONITOR_KEYWORDS", "")
        ).strip(),
        "MAX_CHATS": (
            os.getenv("MAX_CHATS") or default_section.get("MAX_CHATS", "6")
        ).strip(),
        "RELATIONSHIP_DETECT_TIMEOUT": (
            os.getenv("RELATIONSHIP_DETECT_TIMEOUT")
            or default_section.get("RELATIONSHIP_DETECT_TIMEOUT", "6.0")
        ).strip(),
        "PROFILE_WAIT_TIMEOUT": (
            os.getenv("PROFILE_WAIT_TIMEOUT")
            or default_section.get("PROFILE_WAIT_TIMEOUT", "4.0")
        ).strip(),
        "BUTTON_FIND_TIMEOUT": (
            os.getenv("BUTTON_FIND_TIMEOUT")
            or default_section.get("BUTTON_FIND_TIMEOUT", "3.0")
        ).strip(),
    }


def validate_required_config(cfg: Dict[str, str]) -> List[str]:
    """返回缺失的必填字段 key 列表。"""
    missing: List[str] = []
    for key in REQUIRED_KEYS:
        if not (cfg.get(key) or "").strip():
            missing.append(key)
    return missing


def update_config(values: Dict[str, str], persist: bool = True) -> Dict[str, str]:
    """更新配置缓存，按需写入 config.ini。"""
    if persist:
        for key, value in values.items():
            _config["DEFAULT"][key] = value
        _save_config()

    cfg = _collect_defaults()
    global _cfg_cache  # noqa: PLW0603
    _cfg_cache = cfg
    return cfg


_cfg_cache: Dict[str, str] | None = None


def get_config() -> Dict[str, str]:
    """加载配置，不再弹出任何旧界面。"""
    global _cfg_cache  # noqa: PLW0603
    if _cfg_cache is None:
        _cfg_cache = _collect_defaults()
    return _cfg_cache
