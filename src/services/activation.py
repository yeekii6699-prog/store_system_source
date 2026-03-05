"""src.services.activation

激活码验证核心逻辑：
- 机器码生成
- 在线校验/激活（基于飞书多维表格）
- 本地配置写回（config.ini）
- 到期/剩余天数计算

约束：
- 不做离线缓存校验（只做本地状态展示）
- 不做复杂指纹算法（只生成稳定、足够唯一的机器码）
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Tuple

from loguru import logger

from src.config.settings import get_config, update_config


# ========================= 激活码飞书配置 =========================
# 优先级（高 → 低）：
# 1) 用户配置（config.ini/.env）：ACTIVATION_TABLE_URL
# 2) 环境变量：ACTIVATION_FEISHU_APP_ID/ACTIVATION_FEISHU_APP_SECRET/ACTIVATION_FEISHU_TABLE_URL
# 3) 代码常量：仅保留为空，避免在仓库中硬编码密钥

ACTIVATION_FEISHU_APP_ID = os.getenv("ACTIVATION_FEISHU_APP_ID", "").strip()
ACTIVATION_FEISHU_APP_SECRET = os.getenv("ACTIVATION_FEISHU_APP_SECRET", "").strip()
ACTIVATION_FEISHU_TABLE_URL = os.getenv("ACTIVATION_FEISHU_TABLE_URL", "").strip()

ACTIVATION_FEISHU_CODE_FIELD = "激活码"

# 激活码表字段（兼容历史字段名）
ACTIVATION_FIELD_CODE_CANDIDATES = (
    "激活码",
    "激活码（必填）",
    "卡密",
    "兑换码",
    "注册码",
    "Code",
    "code",
)
ACTIVATION_FIELD_VALIDITY_DAYS_CANDIDATES = (
    "有效期天数",
    "时长（天）",
    "时长(天)",
    "时长天数",
)
ACTIVATION_FIELD_STATUS_CANDIDATES = ("使用状态", "状态")
ACTIVATION_FIELD_MACHINE_ID_CANDIDATES = ("机器ID", "机器Id", "MachineID")
ACTIVATION_FIELD_ACTIVATED_AT_CANDIDATES = ("激活时间",)
ACTIVATION_FIELD_EXPIRES_AT_CANDIDATES = ("到期时间",)

ACTIVATION_STATUS_UNUSED = "未使用"
ACTIVATION_STATUS_ACTIVATED = "已激活"
ACTIVATION_STATUS_DISABLED = "已禁用"


def _activation_state_path() -> Path:
    appdata = (os.getenv("APPDATA") or "").strip()
    if appdata:
        base_dir = Path(appdata) / "store_system"
    else:
        base_dir = Path(__file__).resolve().parents[2] / "data"
    return base_dir / "activation_state.json"


def _normalize_local_activation_status(status: str) -> str:
    text = (status or "").strip().lower()
    if text in {"activated", "active", "已激活", "已绑定"}:
        return "activated"
    return text


def _load_activation_state() -> Dict[str, str]:
    path = _activation_state_path()
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取激活状态缓存失败: {}", exc)
        return {}

    if not isinstance(payload, dict):
        return {}

    code = str(payload.get("code") or "").strip()
    status = _normalize_local_activation_status(str(payload.get("status") or ""))
    expiry = str(payload.get("expiry") or "").strip()
    if not code:
        return {}

    return {
        "ACTIVATION_CODE": code,
        "ACTIVATION_STATUS": status or "activated",
        "ACTIVATION_EXPIRY": expiry,
    }


def _save_activation_state(code: str, status: str, expiry: str) -> None:
    normalized_code = (code or "").strip().upper()
    normalized_status = _normalize_local_activation_status(status) or "activated"
    normalized_expiry = (expiry or "").strip()
    if not normalized_code:
        return

    payload = {
        "code": normalized_code,
        "status": normalized_status,
        "expiry": normalized_expiry,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    path = _activation_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("写入激活状态缓存失败: {}", exc)


def _clear_activation_state() -> None:
    path = _activation_state_path()
    if not path.exists():
        return

    try:
        path.unlink()
    except Exception as exc:
        logger.warning("清理激活状态缓存失败: {}", exc)


def _recover_activation_from_state(cfg: Dict[str, str]) -> Dict[str, str]:
    code = (cfg.get("ACTIVATION_CODE") or "").strip()
    status = _normalize_local_activation_status(cfg.get("ACTIVATION_STATUS") or "")
    expiry = (cfg.get("ACTIVATION_EXPIRY") or "").strip()

    if code and status == "activated":
        return cfg

    state_values = _load_activation_state()
    if not state_values:
        return cfg

    merged_values = {
        "ACTIVATION_CODE": code or state_values.get("ACTIVATION_CODE", ""),
        "ACTIVATION_STATUS": (
            status or state_values.get("ACTIVATION_STATUS", "activated") or "activated"
        ),
        "ACTIVATION_EXPIRY": expiry or state_values.get("ACTIVATION_EXPIRY", ""),
    }

    if (
        merged_values["ACTIVATION_CODE"] == (cfg.get("ACTIVATION_CODE") or "").strip()
        and merged_values["ACTIVATION_STATUS"]
        == _normalize_local_activation_status(cfg.get("ACTIVATION_STATUS") or "")
        and merged_values["ACTIVATION_EXPIRY"]
        == (cfg.get("ACTIVATION_EXPIRY") or "").strip()
    ):
        return cfg

    return update_config(merged_values, persist=True)


class ActivationCodeNotFoundError(Exception):
    """激活码不存在异常"""

    pass


class ActivationCodeDisabledError(Exception):
    """激活码已被禁用异常"""

    pass


class ActivationCodeExpiredError(Exception):
    """激活码已过期异常"""

    pass


class ActivationMachineMismatchError(Exception):
    """激活码已在其他机器使用异常"""

    pass


class ActivationNetworkError(Exception):
    """激活码网络相关异常"""

    pass


def create_activation_feishu_client() -> Any:
    """创建激活码专用飞书客户端。

    设计目标：激活逻辑不依赖用户业务表配置。
    因此构造 FeishuClient 时，将 task/profile/activation URL 统一指向激活码表。
    """

    cfg = get_config()

    activation_table_url = (cfg.get("ACTIVATION_TABLE_URL") or "").strip()
    if not activation_table_url:
        activation_table_url = ACTIVATION_FEISHU_TABLE_URL

    # 兼容回退：若未单独配置激活码表，则复用业务任务表 URL
    if not activation_table_url:
        activation_table_url = (cfg.get("FEISHU_TABLE_URL") or "").strip()
        if activation_table_url:
            logger.warning(
                "未配置 ACTIVATION_TABLE_URL，已临时回退使用 FEISHU_TABLE_URL"
            )
            try:
                update_config(
                    {"ACTIVATION_TABLE_URL": activation_table_url}, persist=True
                )
            except Exception as exc:
                logger.warning("回填 ACTIVATION_TABLE_URL 到配置文件失败: {}", exc)

    # 优先使用激活专用凭证，缺失时回退业务凭证
    app_id = ACTIVATION_FEISHU_APP_ID or (cfg.get("FEISHU_APP_ID") or "").strip()
    app_secret = (
        ACTIVATION_FEISHU_APP_SECRET or (cfg.get("FEISHU_APP_SECRET") or "").strip()
    )

    if not activation_table_url:
        raise ActivationNetworkError(
            "未配置 ACTIVATION_TABLE_URL（激活码表链接），且 FEISHU_TABLE_URL 也为空"
        )
    if not app_id or not app_secret:
        raise ActivationNetworkError(
            "未配置飞书 AppID/AppSecret，请设置 ACTIVATION_FEISHU_* 或 FEISHU_APP_*"
        )

    # 延迟导入避免与 src.services.feishu 的静态循环依赖（feishu.py 内部会调用本模块生成激活码）
    from src.services.feishu import FeishuClient

    return FeishuClient(
        app_id=app_id,
        app_secret=app_secret,
        task_table_url=activation_table_url,
        profile_table_url=activation_table_url,
        activation_table_url=activation_table_url,
    )


def _safe_get_first_str(value: Any, default: str = "") -> str:
    """安全地从值中获取第一个字符串元素，处理各种边界情况"""
    if not value:
        return default

    if isinstance(value, list):
        # 取第一个元素，如果不存在或为空则返回默认值
        first = value[0] if value else None
        if first is None:
            return default
        if isinstance(first, str):
            return first.strip()
        if isinstance(first, dict):
            # 飞书富文本常见结构: {"text": "...", "type": "text"}
            text = first.get("text") or first.get("name") or first.get("value")
            if text is not None:
                return str(text).strip()
        return str(first).strip()
    elif isinstance(value, str):
        return value.strip()
    elif isinstance(value, dict):
        text = value.get("text") or value.get("name") or value.get("value")
        if text is not None:
            return str(text).strip()
        return str(value).strip()
    else:
        return str(value).strip()


def _safe_get_first_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return default
    try:
        # 飞书数字字段可能返回 int/float，也可能是字符串
        return int(float(str(value).strip()))
    except Exception:
        return default


def _normalize_code_text(value: str) -> str:
    return (value or "").strip().replace("-", "").replace(" ", "").upper()


def _normalize_name_text(value: str) -> str:
    return (
        (value or "").strip().replace(" ", "").replace("_", "").replace("-", "").lower()
    )


def _is_invalid_filter_error(exc: Exception) -> bool:
    text = str(exc)
    return "InvalidFilter" in text or "field_name" in text


def _extract_field_names(field_items: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(field_items, list):
        return names

    for item in field_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("field_name") or "").strip()
        if name:
            names.append(name)
    return names


def _build_code_field_candidates(feishu_client: Any) -> list[str]:
    configured = str(getattr(feishu_client, "activation_field_code", "") or "").strip()
    candidates = [
        configured,
        ACTIVATION_FEISHU_CODE_FIELD,
        *ACTIVATION_FIELD_CODE_CANDIDATES,
    ]
    result: list[str] = []
    for name in candidates:
        normalized = name.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _pick_code_field_from_schema(
    field_names: list[str], candidates: list[str]
) -> list[str]:
    if not field_names:
        return []

    exact_matches = [name for name in candidates if name in field_names]
    if exact_matches:
        return exact_matches

    normalized_map = {_normalize_name_text(name): name for name in field_names}
    normalized_matches: list[str] = []
    for candidate in candidates:
        mapped = normalized_map.get(_normalize_name_text(candidate))
        if mapped and mapped not in normalized_matches:
            normalized_matches.append(mapped)
    if normalized_matches:
        return normalized_matches

    heuristic_matches: list[str] = []
    for name in field_names:
        lowered = _normalize_name_text(name)
        if ("激活" in name and "码" in name) or "code" in lowered or "卡密" in name:
            heuristic_matches.append(name)
    return heuristic_matches


def _search_activation_items_by_scan(
    feishu_client: Any, code: str
) -> list[Dict[str, Any]]:
    """兜底：当字段筛选不可用时，扫描记录查找激活码。"""
    records = feishu_client.list_records(
        feishu_client.activation_table_url, page_size=500
    )
    target = _normalize_code_text(code)
    if not target:
        return []

    for record in records:
        fields = record.get("fields", {})
        if not isinstance(fields, dict):
            continue
        for raw_value in fields.values():
            text = _normalize_code_text(_safe_get_first_str(raw_value, ""))
            if text and text == target:
                return [record]
    return []


def _search_activation_items(feishu_client: Any, code: str) -> list[Dict[str, Any]]:
    """按候选字段名搜索激活码，必要时回退到扫描。"""
    if not getattr(feishu_client, "activation_table_url", None):
        raise ActivationNetworkError("未配置激活码表 URL")

    table_url = feishu_client.activation_table_url
    candidates = _build_code_field_candidates(feishu_client)
    schema_field_names: list[str] = []

    try:
        schema_field_names = _extract_field_names(feishu_client.list_fields(table_url))
    except Exception as exc:
        logger.warning("读取激活码表字段失败，将直接尝试候选字段: {}", exc)

    search_fields: list[str] = []
    if schema_field_names:
        search_fields.extend(
            _pick_code_field_from_schema(schema_field_names, candidates)
        )

    for candidate in candidates:
        if candidate not in search_fields:
            search_fields.append(candidate)

    last_error: Exception | None = None
    for field_name in search_fields:
        try:
            items = feishu_client.search_by_field(field_name, code, table_url)
            if items:
                try:
                    feishu_client.activation_field_code = field_name
                except Exception:
                    pass
                return items
        except Exception as exc:
            last_error = exc
            if _is_invalid_filter_error(exc):
                logger.warning("激活码字段 [{}] 不存在，尝试下一个候选字段", field_name)
                continue
            raise

    try:
        items = _search_activation_items_by_scan(feishu_client, code)
    except Exception as exc:
        if last_error:
            raise ActivationNetworkError(
                f"字段筛选失败且扫描回退失败: {last_error}; scan_error: {exc}"
            )
        raise

    if items:
        logger.warning("激活码查询使用了扫描回退，请尽快配置 ACTIVATION_FIELD_CODE")
    elif last_error and _is_invalid_filter_error(last_error):
        logger.warning(
            "激活码字段匹配失败，建议在配置中设置 ACTIVATION_FIELD_CODE；当前候选: {}",
            search_fields,
        )
    return items


def _pick_first_existing_field(
    fields: Dict[str, Any], candidates: Tuple[str, ...]
) -> Tuple[str, Any]:
    for name in candidates:
        if name in fields:
            return name, fields.get(name)
    return "", None


def _is_activation_disabled(status: str) -> bool:
    return status == ACTIVATION_STATUS_DISABLED or "禁用" in status


def _is_activation_bound(status: str) -> bool:
    return status in ("已绑定", ACTIVATION_STATUS_ACTIVATED)


def _resolve_activation_runtime(
    machine_id: str | None, feishu_client: Any | None
) -> Tuple[str, Any]:
    resolved_machine_id = machine_id or get_machine_id_from_config()

    if feishu_client is None:
        try:
            feishu_client = create_activation_feishu_client()
        except Exception as exc:
            raise ActivationNetworkError(f"无法连接到飞书服务: {exc}")

    assert feishu_client is not None

    if not feishu_client.activation_table_url:
        raise ActivationNetworkError(
            "未配置激活码表！请检查 activation.py 中的 ACTIVATION_FEISHU_TABLE_URL"
        )

    return resolved_machine_id, feishu_client


def _search_activation_items_guarded(
    feishu_client: Any, code: str, purpose: str
) -> list[Dict[str, Any]]:
    try:
        return _search_activation_items(feishu_client, code)
    except Exception as exc:
        raise ActivationNetworkError(f"网络错误，无法{purpose}: {exc}")


def _extract_activation_record_state(
    feishu_client: Any, record: Dict[str, Any]
) -> Tuple[str, Dict[str, Any], str, Any]:
    record_id = feishu_client._extract_record_id(record)
    fields = record.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}

    _, status_raw = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_STATUS_CANDIDATES
    )
    status = _safe_get_first_str(status_raw)

    _, expires_raw = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_EXPIRES_AT_CANDIDATES
    )
    expires_at = expires_raw[0] if isinstance(expires_raw, list) else expires_raw

    return record_id, fields, status, expires_at


def _extract_bound_machine(fields: Dict[str, Any]) -> str:
    _, bound_machine_raw = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_MACHINE_ID_CANDIDATES
    )
    return _safe_get_first_str(bound_machine_raw)


def _normalize_machine_id(value: str) -> str:
    """归一化机器码用于比较（忽略大小写与连接符差异）。"""
    if not value:
        return ""
    return "".join(ch for ch in value.strip().lower() if ch.isalnum())


def _normalize_expiry_text(expiry_value: Any) -> str:
    """将飞书返回的到期时间（可能是毫秒时间戳/字符串/列表）规范为字符串。"""
    if isinstance(expiry_value, list):
        expiry_value = expiry_value[0] if expiry_value else ""

    if not expiry_value:
        return ""

    if isinstance(expiry_value, datetime):
        return expiry_value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(expiry_value, (int, float)):
        ts = expiry_value / 1000.0 if expiry_value > 1e12 else expiry_value
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    return str(expiry_value).strip()


def generate_machine_id() -> str:
    """生成稳定、足够唯一的机器码。

    不追求硬件指纹级别精度，避免复杂算法与兼容性风险。
    """

    import platform

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
    digest = hashlib.sha256(raw).hexdigest().upper()
    # 16 位足够短、可展示；也便于人工核对
    return digest[:16]


def get_machine_id_from_config() -> str:
    """从配置中获取机器ID"""
    try:
        cfg = get_config()
        machine_id = cfg.get("ACTIVATION_MACHINE_ID", "")
        if not machine_id:
            # 生成新的机器ID并保存
            machine_id = generate_machine_id()
            update_config({"ACTIVATION_MACHINE_ID": machine_id}, persist=True)
        return machine_id
    except Exception:
        return generate_machine_id()


def generate_activation_code(length: int = 16) -> str:
    """生成随机激活码，格式：XXXX-XXXX-XXXX-XXXX"""
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(length))
    return "-".join(code[i : i + 4] for i in range(0, length, 4))


def get_remaining_days(
    expiry_date: str
    | int
    | float
    | datetime
    | list[str | int | float | datetime]
    | None,
) -> int:
    """计算剩余天数。

    返回值：
    - 正数：剩余天数（按天向上取整，便于展示）
    - 0：当天到期或无法解析
    - 负数：已过期天数（按天向下取整）
    """

    if not expiry_date:
        return 0

    if isinstance(expiry_date, list):
        expiry_date = expiry_date[0] if expiry_date else None
    if not expiry_date:
        return 0

    dt_obj: datetime | None = None
    if isinstance(expiry_date, datetime):
        dt_obj = expiry_date
    elif isinstance(expiry_date, (int, float)):
        ts = expiry_date / 1000.0 if expiry_date > 1e12 else float(expiry_date)
        dt_obj = datetime.fromtimestamp(ts)
    elif isinstance(expiry_date, str):
        text = expiry_date.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt_obj = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt_obj is None:
            logger.warning("无法解析到期时间: {}", expiry_date)
            return 0
    else:
        logger.warning("不支持的到期时间类型: {}", type(expiry_date))
        return 0

    seconds = (dt_obj - datetime.now()).total_seconds()
    if seconds == 0:
        return 0
    day_seconds = 86400.0
    if seconds > 0:
        # 剩余不足 1 天也算 1 天（展示友好）
        return int((seconds + day_seconds - 1) // day_seconds)
    # 过期：按天向下取整（-0.1 天 -> -1, -1.1 天 -> -2）
    return int(seconds // day_seconds)


def validate_activation_code(
    code: str,
    machine_id: str | None = None,
    feishu_client: Any | None = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """验证激活码是否有效"""
    if not code or not code.strip():
        return False, "请输入激活码", {}

    code = code.strip().upper()
    machine_id, feishu_client = _resolve_activation_runtime(machine_id, feishu_client)
    assert feishu_client is not None
    items = _search_activation_items_guarded(feishu_client, code, "验证激活码")

    if not items:
        return False, "激活码不存在", {}

    record = items[0]
    record_id, fields, status, expires_at = _extract_activation_record_state(
        feishu_client, record
    )

    if _is_activation_disabled(status):
        return False, "激活码已被禁用", {"record_id": record_id, "status": status}

    if _is_activation_bound(status):
        if expires_at:
            remaining_days = get_remaining_days(expires_at)
            if remaining_days < 0:
                return (
                    False,
                    f"激活码已过期",
                    {
                        "record_id": record_id,
                        "status": "已过期",
                        "remaining_days": remaining_days,
                    },
                )

        bound_machine = _extract_bound_machine(fields)
        if bound_machine and _normalize_machine_id(
            bound_machine
        ) != _normalize_machine_id(machine_id or ""):
            return (
                False,
                "激活码已在其他机器使用",
                {"record_id": record_id, "status": status, "machine_id": bound_machine},
            )

        remaining_days = get_remaining_days(expires_at)
        return (
            True,
            f"激活码已激活，剩余{remaining_days}天",
            {
                "record_id": record_id,
                "status": ACTIVATION_STATUS_ACTIVATED,
                "remaining_days": remaining_days,
                "machine_id": machine_id,
            },
        )

    _, validity_raw = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_VALIDITY_DAYS_CANDIDATES
    )
    validity_days = _safe_get_first_int(validity_raw, default=30)

    return (
        True,
        f"激活码可用，有效期{validity_days}天",
        {
            "record_id": record_id,
            "status": "未使用",
            "validity_days": validity_days,
        },
    )


def activate_code(
    code: str,
    machine_id: str | None = None,
    phone: str | None = None,
    feishu_client: Any | None = None,
) -> Dict[str, Any]:
    """激活激活码"""
    if not code or not code.strip():
        raise ActivationCodeNotFoundError("请输入激活码")

    code = code.strip().upper()
    machine_id, feishu_client = _resolve_activation_runtime(machine_id, feishu_client)
    assert feishu_client is not None
    items = _search_activation_items_guarded(feishu_client, code, "激活")

    if not items:
        raise ActivationCodeNotFoundError("激活码不存在")

    record = items[0]
    record_id, fields, status, expires_at = _extract_activation_record_state(
        feishu_client, record
    )

    if _is_activation_disabled(status):
        raise ActivationCodeDisabledError("激活码已被禁用")

    if _is_activation_bound(status):
        # 仅已绑定/已激活记录需要按到期时间拦截。
        if expires_at:
            remaining = get_remaining_days(expires_at)
            if remaining < 0:
                raise ActivationCodeExpiredError("激活码已过期")

        bound_machine = _extract_bound_machine(fields)
        normalized_expiry = _normalize_expiry_text(expires_at)

        # 已绑定到其他机器：拒绝
        if bound_machine and _normalize_machine_id(
            bound_machine
        ) != _normalize_machine_id(machine_id or ""):
            raise ActivationMachineMismatchError("激活码已在其他机器使用")

        # 已绑定到当前机器（或历史数据未写机器ID）：按幂等激活处理
        if not bound_machine:
            try:
                activation_table_url = getattr(
                    feishu_client, "activation_table_url", None
                )
                feishu_client.update_record(
                    record_id,
                    {"机器ID": machine_id},
                    activation_table_url,
                )
            except Exception as e:
                raise ActivationNetworkError(f"无法补全机器绑定信息: {e}")

        update_config(
            {
                "ACTIVATION_CODE": code,
                "ACTIVATION_STATUS": "activated",
                "ACTIVATION_EXPIRY": normalized_expiry,
            },
            persist=True,
        )
        _save_activation_state(code, "activated", normalized_expiry)

        remaining_days = get_remaining_days(expires_at)
        return {
            "success": True,
            "message": f"已激活，剩余{remaining_days}天",
            "record_id": record_id,
            "expires_at": normalized_expiry,
            "remaining_days": remaining_days,
        }

    # 计算到期时间（优先读取表内有效期字段；缺失则默认 30 天）
    _, validity_raw = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_VALIDITY_DAYS_CANDIDATES
    )
    validity_days = _safe_get_first_int(validity_raw, default=30)
    now = datetime.now()
    # 飞书日期字段需要Unix时间戳（毫秒）
    activated_ts = int(now.timestamp() * 1000)
    expires_ts = int((now + timedelta(days=validity_days)).timestamp() * 1000)

    status_field_name, _ = _pick_first_existing_field(
        fields, ACTIVATION_FIELD_STATUS_CANDIDATES
    )
    if not status_field_name:
        # 新表优先使用“使用状态”；老表兼容“状态”
        status_field_name = ACTIVATION_FIELD_STATUS_CANDIDATES[0]

    update_fields: Dict[str, Any] = {
        status_field_name: ACTIVATION_STATUS_ACTIVATED,
        "机器ID": machine_id,
        "激活时间": activated_ts,
        "到期时间": expires_ts,
    }

    if phone:
        update_fields["联系电话"] = phone

    try:
        # 确定激活码表URL
        activation_table_url = getattr(feishu_client, "activation_table_url", None)
        feishu_client.update_record(record_id, update_fields, activation_table_url)
    except Exception as e:
        raise ActivationNetworkError(f"无法更新激活状态: {e}")

    # 转换为可读字符串用于存储和返回
    expires_str = (now + timedelta(days=validity_days)).strftime("%Y-%m-%d %H:%M:%S")
    activated_str = now.strftime("%Y-%m-%d %H:%M:%S")

    update_config(
        {
            "ACTIVATION_CODE": code,
            "ACTIVATION_STATUS": "activated",
            "ACTIVATION_EXPIRY": expires_str,
        },
        persist=True,
    )
    _save_activation_state(code, "activated", expires_str)

    logger.info(f"激活成功: {code}, 到期: {expires_str}")

    return {
        "success": True,
        "message": f"激活成功（剩余{validity_days}天）",
        "record_id": record_id,
        "activated_at": activated_str,
        "expires_at": expires_str,
        "remaining_days": validity_days,
    }


def check_local_activation_status() -> Dict[str, Any]:
    """检查本地激活状态"""
    cfg = _recover_activation_from_state(get_config())

    code = cfg.get("ACTIVATION_CODE", "").strip()
    status = _normalize_local_activation_status(cfg.get("ACTIVATION_STATUS", ""))
    expiry = cfg.get("ACTIVATION_EXPIRY", "").strip()

    if not code:
        return {"is_activated": False, "status": "未激活", "message": "请先激活"}

    if status != "activated":
        return {"is_activated": False, "status": status, "message": "状态异常"}

    _save_activation_state(code, status, expiry)

    remaining = get_remaining_days(expiry)

    if remaining < 0:
        return {
            "is_activated": False,
            "status": "已过期",
            "message": f"已过期{abs(remaining)}天",
        }

    return {
        "is_activated": True,
        "status": "已激活",
        "message": f"已激活，剩余{remaining}天",
        "remaining_days": remaining,
    }


def need_activation() -> bool:
    """检查是否需要激活"""
    return not check_local_activation_status()["is_activated"]


def clear_activation() -> None:
    """清除本地激活状态"""
    update_config(
        {
            "ACTIVATION_CODE": "",
            "ACTIVATION_STATUS": "",
            "ACTIVATION_EXPIRY": "",
        },
        persist=True,
    )
    _clear_activation_state()
