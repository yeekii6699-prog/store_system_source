import configparser
import hashlib
import os
import platform
import sys
import uuid
from pathlib import Path
from typing import Dict, List

from dotenv import dotenv_values  # pyright: ignore[reportMissingImports]

WELCOME_IMAGE_DELIMITER = "|"

# ============== 路径与配置文件定位 ==============
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)

ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.ini"

_config = configparser.ConfigParser()
if CONFIG_PATH.exists():
    _config.read(CONFIG_PATH, encoding="utf-8")
if "DEFAULT" not in _config:
    _config["DEFAULT"] = {}


def _import_env_to_config_once() -> None:
    """仅在首启时导入 .env 到 config.ini，避免运行期双写来源。"""
    if CONFIG_PATH.exists() or not ENV_PATH.exists():
        return

    env_values = dotenv_values(ENV_PATH)
    default_section = _config["DEFAULT"]
    changed = False

    for key, value in env_values.items():
        normalized_key = (key or "").strip().upper()
        if not normalized_key or value is None:
            continue

        text_value = str(value).strip()
        if not text_value:
            continue

        default_section[normalized_key] = text_value
        changed = True

    if changed:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            _config.write(f)


def _config_env_get(_key: str) -> str:
    """运行期禁用环境变量覆盖，保持 config.ini 为唯一真源。"""
    return ""


_import_env_to_config_once()


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
    "ACTIVATION_CODE": "激活码",
    "ACTIVATION_MACHINE_ID": "机器码",
    "ACTIVATION_TABLE_URL": "激活码表链接",
    "ACTIVATION_STATUS": "激活状态",
    "ACTIVATION_EXPIRY": "激活过期时间",
    "FOLLOWUP_ENABLED": "自动回访开关",
    "FOLLOWUP_DRY_RUN": "回访仅生成不发送",
    "FOLLOWUP_POLL_INTERVAL": "回访轮询间隔（秒）",
    "FOLLOWUP_BATCH_LIMIT": "回访单轮处理上限",
    "FOLLOWUP_VISIT_DELAY_DAYS": "到店回访阈值（天）",
    "FOLLOWUP_CONSUME_DELAY_DAYS": "消费回访阈值（天）",
    "FOLLOWUP_COOLDOWN_DAYS": "客户回访冷却（天）",
    "FOLLOWUP_DAILY_CAP": "回访每日上限",
    "FOLLOWUP_HOURLY_CAP": "回访每小时上限",
    "FOLLOWUP_QUIET_START_HOUR": "回访静默开始时",
    "FOLLOWUP_QUIET_END_HOUR": "回访静默结束时",
    "FOLLOWUP_PROMPT_VERSION": "回访提示词版本",
    "LLM_BASE_URL": "LLM 接口地址",
    "LLM_API_KEY": "LLM API Key",
    "LLM_MODEL": "LLM 模型名",
    "LLM_TIMEOUT": "LLM 超时（秒）",
    "LLM_MAX_TOKENS": "LLM 最大输出Token",
    "LLM_RETRY_COUNT": "LLM 重试次数",
    "FEISHU_FIELD_LAST_VISIT": "最近到店字段名",
    "FEISHU_FIELD_LAST_CONSUME": "最近消费字段名",
    "FEISHU_FIELD_CONSUME_SUMMARY": "消费摘要字段名",
    "FEISHU_FIELD_FOLLOWUP_STATUS": "回访状态字段名",
    "FEISHU_FIELD_FOLLOWUP_LAST_SENT_AT": "回访发送时间字段名",
    "FEISHU_FIELD_FOLLOWUP_REASON": "回访原因字段名",
    "FEISHU_FIELD_FOLLOWUP_SNAPSHOT": "回访快照字段名",
    "FEISHU_FIELD_FOLLOWUP_MESSAGE": "回访消息字段名",
    "FEISHU_FIELD_FOLLOWUP_ATTEMPTS": "回访尝试次数字段名",
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


def _generate_machine_id() -> str:
    """生成稳定且可读的机器码。"""
    node = (platform.node() or "").strip().lower()
    system = (platform.system() or "").strip().lower()
    release = (platform.release() or "").strip().lower()
    processor = (platform.processor() or "").strip().lower()

    try:
        mac = hex(uuid.getnode())[2:]
    except Exception:
        mac = ""

    raw = "|".join([node, system, release, processor, mac]).encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha256(raw).hexdigest().upper()[:16]


def _resolve_activation_machine_id(default_section: configparser.SectionProxy) -> str:
    """优先从配置读取机器码，缺失时自动生成并持久化。"""
    env_machine_id = (_config_env_get("ACTIVATION_MACHINE_ID") or "").strip()
    if env_machine_id:
        return env_machine_id

    configured_machine_id = (
        default_section.get("ACTIVATION_MACHINE_ID", "") or ""
    ).strip()
    if configured_machine_id:
        return configured_machine_id

    generated_machine_id = _generate_machine_id()
    default_section["ACTIVATION_MACHINE_ID"] = generated_machine_id
    _save_config()
    return generated_machine_id


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
    activation_machine_id = _resolve_activation_machine_id(default_section)
    return {
        "FEISHU_APP_ID": (
            _config_env_get("FEISHU_APP_ID") or default_section.get("FEISHU_APP_ID", "")
        ).strip(),
        "FEISHU_APP_SECRET": (
            _config_env_get("FEISHU_APP_SECRET")
            or default_section.get("FEISHU_APP_SECRET", "")
        ).strip(),
        "FEISHU_TABLE_URL": (
            _config_env_get("FEISHU_TABLE_URL")
            or default_section.get("FEISHU_TABLE_URL", "")
        ).strip(),
        "FEISHU_PROFILE_TABLE_URL": (
            _config_env_get("FEISHU_PROFILE_TABLE_URL")
            or default_section.get("FEISHU_PROFILE_TABLE_URL", "")
        ).strip(),
        "WECHAT_EXEC_PATH": (
            _config_env_get("WECHAT_EXEC_PATH")
            or default_section.get("WECHAT_EXEC_PATH", "")
            or detected_wechat
            or ""
        ).strip(),
        "WELCOME_ENABLED": (
            _config_env_get("WELCOME_ENABLED")
            or default_section.get("WELCOME_ENABLED", "0")
        ).strip(),
        "WELCOME_TEXT": (
            _config_env_get("WELCOME_TEXT") or default_section.get("WELCOME_TEXT", "")
        ).strip(),
        "WELCOME_IMAGE_PATHS": (
            _config_env_get("WELCOME_IMAGE_PATHS")
            or default_section.get("WELCOME_IMAGE_PATHS", "")
        ).strip(),
        "WELCOME_STEPS": (
            _config_env_get("WELCOME_STEPS") or default_section.get("WELCOME_STEPS", "")
        ).strip(),
        "NEW_FRIEND_SCAN_INTERVAL": (
            _config_env_get("NEW_FRIEND_SCAN_INTERVAL")
            or default_section.get("NEW_FRIEND_SCAN_INTERVAL", "30")
        ).strip(),
        "PASSIVE_SCAN_JITTER": (
            _config_env_get("PASSIVE_SCAN_JITTER")
            or default_section.get("PASSIVE_SCAN_JITTER", "5")
        ).strip(),
        "FEISHU_POLL_INTERVAL": (
            _config_env_get("FEISHU_POLL_INTERVAL")
            or default_section.get("FEISHU_POLL_INTERVAL", "5")
        ).strip(),
        "NETWORK_PROXY": (
            _config_env_get("NETWORK_PROXY") or default_section.get("NETWORK_PROXY", "")
        ).strip(),
        "NETWORK_VERIFY_SSL": (
            _config_env_get("NETWORK_VERIFY_SSL")
            or default_section.get("NETWORK_VERIFY_SSL", "1")
        ).strip(),
        "NETWORK_TIMEOUT": (
            _config_env_get("NETWORK_TIMEOUT")
            or default_section.get("NETWORK_TIMEOUT", "15")
        ).strip(),
        "NETWORK_USE_SYSTEM_PROXY": (
            _config_env_get("NETWORK_USE_SYSTEM_PROXY")
            or default_section.get("NETWORK_USE_SYSTEM_PROXY", "0")
        ).strip(),
        "FEISHU_RATE_LIMIT_COOLDOWN": (
            _config_env_get("FEISHU_RATE_LIMIT_COOLDOWN")
            or default_section.get("FEISHU_RATE_LIMIT_COOLDOWN", "0.3")
        ).strip(),
        "RPA_DELAY_MIN": (
            _config_env_get("RPA_DELAY_MIN")
            or default_section.get("RPA_DELAY_MIN", "0.5")
        ).strip(),
        "RPA_DELAY_MAX": (
            _config_env_get("RPA_DELAY_MAX")
            or default_section.get("RPA_DELAY_MAX", "1.5")
        ).strip(),
        "LOG_RETENTION_DAYS": (
            _config_env_get("LOG_RETENTION_DAYS")
            or default_section.get("LOG_RETENTION_DAYS", "7")
        ).strip(),
        "LOG_LEVEL": (
            _config_env_get("LOG_LEVEL") or default_section.get("LOG_LEVEL", "INFO")
        ).strip(),
        "FEISHU_WEBHOOK_URL": (
            _config_env_get("FEISHU_WEBHOOK_URL")
            or default_section.get("FEISHU_WEBHOOK_URL", "")
        ).strip(),
        "ALERT_COOLDOWN": (
            _config_env_get("ALERT_COOLDOWN")
            or default_section.get("ALERT_COOLDOWN", "60")
        ).strip(),
        "WELCOME_STEP_DELAY": (
            _config_env_get("WELCOME_STEP_DELAY")
            or default_section.get("WELCOME_STEP_DELAY", "1.0")
        ).strip(),
        "WELCOME_RETRY_COUNT": (
            _config_env_get("WELCOME_RETRY_COUNT")
            or default_section.get("WELCOME_RETRY_COUNT", "0")
        ).strip(),
        "MONITOR_KEYWORDS": (
            _config_env_get("MONITOR_KEYWORDS")
            or default_section.get("MONITOR_KEYWORDS", "")
        ).strip(),
        "MAX_CHATS": (
            _config_env_get("MAX_CHATS") or default_section.get("MAX_CHATS", "6")
        ).strip(),
        "RELATIONSHIP_DETECT_TIMEOUT": (
            _config_env_get("RELATIONSHIP_DETECT_TIMEOUT")
            or default_section.get("RELATIONSHIP_DETECT_TIMEOUT", "6.0")
        ).strip(),
        "PROFILE_WAIT_TIMEOUT": (
            _config_env_get("PROFILE_WAIT_TIMEOUT")
            or default_section.get("PROFILE_WAIT_TIMEOUT", "4.0")
        ).strip(),
        "BUTTON_FIND_TIMEOUT": (
            _config_env_get("BUTTON_FIND_TIMEOUT")
            or default_section.get("BUTTON_FIND_TIMEOUT", "3.0")
        ).strip(),
        # 激活码配置
        "ACTIVATION_CODE": (
            _config_env_get("ACTIVATION_CODE")
            or default_section.get("ACTIVATION_CODE", "")
        ).strip(),
        "ACTIVATION_MACHINE_ID": (
            _config_env_get("ACTIVATION_MACHINE_ID")
            or default_section.get("ACTIVATION_MACHINE_ID", "")
            or activation_machine_id
        ).strip(),
        "ACTIVATION_TABLE_URL": (
            _config_env_get("ACTIVATION_TABLE_URL")
            or default_section.get("ACTIVATION_TABLE_URL", "")
        ).strip(),
        "ACTIVATION_STATUS": (
            _config_env_get("ACTIVATION_STATUS")
            or default_section.get("ACTIVATION_STATUS", "")
        ).strip(),
        "ACTIVATION_EXPIRY": (
            _config_env_get("ACTIVATION_EXPIRY")
            or default_section.get("ACTIVATION_EXPIRY", "")
        ).strip(),
        "FOLLOWUP_ENABLED": (
            _config_env_get("FOLLOWUP_ENABLED")
            or default_section.get("FOLLOWUP_ENABLED", "0")
        ).strip(),
        "FOLLOWUP_DRY_RUN": (
            _config_env_get("FOLLOWUP_DRY_RUN")
            or default_section.get("FOLLOWUP_DRY_RUN", "0")
        ).strip(),
        "FOLLOWUP_POLL_INTERVAL": (
            _config_env_get("FOLLOWUP_POLL_INTERVAL")
            or default_section.get("FOLLOWUP_POLL_INTERVAL", "300")
        ).strip(),
        "FOLLOWUP_BATCH_LIMIT": (
            _config_env_get("FOLLOWUP_BATCH_LIMIT")
            or default_section.get("FOLLOWUP_BATCH_LIMIT", "5")
        ).strip(),
        "FOLLOWUP_VISIT_DELAY_DAYS": (
            _config_env_get("FOLLOWUP_VISIT_DELAY_DAYS")
            or default_section.get("FOLLOWUP_VISIT_DELAY_DAYS", "7")
        ).strip(),
        "FOLLOWUP_CONSUME_DELAY_DAYS": (
            _config_env_get("FOLLOWUP_CONSUME_DELAY_DAYS")
            or default_section.get("FOLLOWUP_CONSUME_DELAY_DAYS", "10")
        ).strip(),
        "FOLLOWUP_COOLDOWN_DAYS": (
            _config_env_get("FOLLOWUP_COOLDOWN_DAYS")
            or default_section.get("FOLLOWUP_COOLDOWN_DAYS", "7")
        ).strip(),
        "FOLLOWUP_DAILY_CAP": (
            _config_env_get("FOLLOWUP_DAILY_CAP")
            or default_section.get("FOLLOWUP_DAILY_CAP", "50")
        ).strip(),
        "FOLLOWUP_HOURLY_CAP": (
            _config_env_get("FOLLOWUP_HOURLY_CAP")
            or default_section.get("FOLLOWUP_HOURLY_CAP", "10")
        ).strip(),
        "FOLLOWUP_QUIET_START_HOUR": (
            _config_env_get("FOLLOWUP_QUIET_START_HOUR")
            or default_section.get("FOLLOWUP_QUIET_START_HOUR", "22")
        ).strip(),
        "FOLLOWUP_QUIET_END_HOUR": (
            _config_env_get("FOLLOWUP_QUIET_END_HOUR")
            or default_section.get("FOLLOWUP_QUIET_END_HOUR", "8")
        ).strip(),
        "FOLLOWUP_PROMPT_VERSION": (
            _config_env_get("FOLLOWUP_PROMPT_VERSION")
            or default_section.get("FOLLOWUP_PROMPT_VERSION", "v1")
        ).strip(),
        "LLM_BASE_URL": (
            _config_env_get("LLM_BASE_URL") or default_section.get("LLM_BASE_URL", "")
        ).strip(),
        "LLM_API_KEY": (
            _config_env_get("LLM_API_KEY") or default_section.get("LLM_API_KEY", "")
        ).strip(),
        "LLM_MODEL": (
            _config_env_get("LLM_MODEL")
            or default_section.get("LLM_MODEL", "gpt-4o-mini")
        ).strip(),
        "LLM_TIMEOUT": (
            _config_env_get("LLM_TIMEOUT") or default_section.get("LLM_TIMEOUT", "30")
        ).strip(),
        "LLM_MAX_TOKENS": (
            _config_env_get("LLM_MAX_TOKENS")
            or default_section.get("LLM_MAX_TOKENS", "180")
        ).strip(),
        "LLM_RETRY_COUNT": (
            _config_env_get("LLM_RETRY_COUNT")
            or default_section.get("LLM_RETRY_COUNT", "2")
        ).strip(),
        "FEISHU_FIELD_LAST_VISIT": (
            _config_env_get("FEISHU_FIELD_LAST_VISIT")
            or default_section.get("FEISHU_FIELD_LAST_VISIT", "最近到店时间")
        ).strip(),
        "FEISHU_FIELD_LAST_CONSUME": (
            _config_env_get("FEISHU_FIELD_LAST_CONSUME")
            or default_section.get("FEISHU_FIELD_LAST_CONSUME", "最近消费时间")
        ).strip(),
        "FEISHU_FIELD_CONSUME_SUMMARY": (
            _config_env_get("FEISHU_FIELD_CONSUME_SUMMARY")
            or default_section.get("FEISHU_FIELD_CONSUME_SUMMARY", "最近消费摘要")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_STATUS": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_STATUS")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_STATUS", "回访状态")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_LAST_SENT_AT": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_LAST_SENT_AT")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_LAST_SENT_AT", "回访发送时间")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_REASON": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_REASON")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_REASON", "回访原因")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_SNAPSHOT": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_SNAPSHOT")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_SNAPSHOT", "回访快照指纹")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_MESSAGE": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_MESSAGE")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_MESSAGE", "回访消息")
        ).strip(),
        "FEISHU_FIELD_FOLLOWUP_ATTEMPTS": (
            _config_env_get("FEISHU_FIELD_FOLLOWUP_ATTEMPTS")
            or default_section.get("FEISHU_FIELD_FOLLOWUP_ATTEMPTS", "回访尝试次数")
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
