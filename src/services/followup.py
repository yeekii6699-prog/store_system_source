from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Literal

import requests
from loguru import logger

from src.config.network import network_config


DecisionType = Literal["send", "skip"]


@dataclass
class FollowupCandidate:
    record_id: str
    wechat_id: str
    nickname: str
    phone: str
    last_visit_at: datetime | None
    last_consume_at: datetime | None
    last_consume_summary: str
    last_followup_at: datetime | None
    followup_status: str
    followup_snapshot_hash: str
    followup_attempts: int
    sleep_warning: str


@dataclass
class FollowupDecision:
    decision: DecisionType
    reason_code: str
    reason_detail: str


@dataclass
class FollowupMessageResult:
    text: str
    fallback_used: bool
    reason_code: str
    reason_detail: str


@dataclass
class FollowupRuntimeConfig:
    enabled: bool
    dry_run: bool
    poll_interval: int
    batch_limit: int
    visit_delay_days: int
    consume_delay_days: int
    cooldown_days: int
    daily_cap: int
    hourly_cap: int
    quiet_start_hour: int
    quiet_end_hour: int
    prompt_version: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout: int
    llm_max_tokens: int
    llm_retry_count: int


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _parse_simple_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _parse_simple_text(value[0] if value else "")
    if isinstance(value, dict):
        for key in ("text", "value", "id"):
            current = value.get(key)
            if current is not None:
                text = str(current).strip()
                if text:
                    return text
        return ""
    return str(value).strip()


def _parse_phone_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _parse_phone_text(value[0] if value else "")
    if isinstance(value, dict):
        for key in ("full_number", "national_number", "text", "value"):
            current = value.get(key)
            if current is not None:
                text = str(current).strip()
                if text:
                    return text
        return ""
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except Exception:
            return None

    if isinstance(value, list) and value:
        return _parse_datetime(value[0])

    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _dt_to_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_time(value: datetime | None) -> str:
    return _dt_to_text(value)


def load_followup_runtime_config(cfg: Dict[str, str]) -> FollowupRuntimeConfig:
    return FollowupRuntimeConfig(
        enabled=(cfg.get("FOLLOWUP_ENABLED") or "0") == "1",
        dry_run=(cfg.get("FOLLOWUP_DRY_RUN") or "0") == "1",
        poll_interval=max(60, _safe_int(cfg.get("FOLLOWUP_POLL_INTERVAL"), 300)),
        batch_limit=max(1, _safe_int(cfg.get("FOLLOWUP_BATCH_LIMIT"), 5)),
        visit_delay_days=max(0, _safe_int(cfg.get("FOLLOWUP_VISIT_DELAY_DAYS"), 7)),
        consume_delay_days=max(
            0, _safe_int(cfg.get("FOLLOWUP_CONSUME_DELAY_DAYS"), 10)
        ),
        cooldown_days=max(0, _safe_int(cfg.get("FOLLOWUP_COOLDOWN_DAYS"), 7)),
        daily_cap=max(1, _safe_int(cfg.get("FOLLOWUP_DAILY_CAP"), 50)),
        hourly_cap=max(1, _safe_int(cfg.get("FOLLOWUP_HOURLY_CAP"), 10)),
        quiet_start_hour=max(
            0, min(23, _safe_int(cfg.get("FOLLOWUP_QUIET_START_HOUR"), 22))
        ),
        quiet_end_hour=max(
            0, min(23, _safe_int(cfg.get("FOLLOWUP_QUIET_END_HOUR"), 8))
        ),
        prompt_version=(cfg.get("FOLLOWUP_PROMPT_VERSION") or "v1").strip() or "v1",
        llm_base_url=(cfg.get("LLM_BASE_URL") or "").strip(),
        llm_api_key=(cfg.get("LLM_API_KEY") or "").strip(),
        llm_model=(cfg.get("LLM_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini",
        llm_timeout=max(5, _safe_int(cfg.get("LLM_TIMEOUT"), 30)),
        llm_max_tokens=max(64, _safe_int(cfg.get("LLM_MAX_TOKENS"), 180)),
        llm_retry_count=max(0, _safe_int(cfg.get("LLM_RETRY_COUNT"), 2)),
    )


def make_followup_candidate(
    record: Dict[str, Any], fields: Dict[str, Any]
) -> FollowupCandidate:
    record_id = str(record.get("record_id") or record.get("recordId") or "").strip()
    return FollowupCandidate(
        record_id=record_id,
        wechat_id=_parse_simple_text(fields.get("微信号")),
        nickname=str(fields.get("昵称") or fields.get("姓名") or "").strip(),
        phone=_parse_phone_text(fields.get("followup_phone") or fields.get("手机号")),
        last_visit_at=_parse_datetime(
            fields.get("followup_last_visit") or fields.get("最近到店时间")
        ),
        last_consume_at=_parse_datetime(
            fields.get("followup_last_consume") or fields.get("最近消费时间")
        ),
        last_consume_summary=str(
            fields.get("followup_consume_summary") or fields.get("最近消费摘要") or ""
        ).strip(),
        last_followup_at=_parse_datetime(
            fields.get("followup_last_sent_at") or fields.get("回访发送时间")
        ),
        followup_status=str(
            fields.get("followup_status") or fields.get("回访状态") or ""
        ).strip(),
        followup_snapshot_hash=str(
            fields.get("followup_snapshot") or fields.get("回访快照指纹") or ""
        ).strip(),
        followup_attempts=_safe_int(
            fields.get("followup_attempts") or fields.get("回访尝试次数"), 0
        ),
        sleep_warning=str(
            fields.get("followup_sleep_warning") or fields.get("沉睡预警") or ""
        ).strip(),
    )


def build_snapshot_hash(candidate: FollowupCandidate, prompt_version: str) -> str:
    raw = "|".join(
        [
            candidate.wechat_id,
            _dt_to_text(candidate.last_visit_at),
            _dt_to_text(candidate.last_consume_at),
            candidate.last_consume_summary,
            prompt_version,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _is_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    hour = now.hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def evaluate_candidate(
    candidate: FollowupCandidate,
    runtime_cfg: FollowupRuntimeConfig,
    now: datetime,
    hour_sent_count: int,
    day_sent_count: int,
) -> FollowupDecision:
    if not candidate.record_id:
        return FollowupDecision("skip", "missing_record_id", "记录缺少record_id")

    if not candidate.phone:
        return FollowupDecision("skip", "missing_phone", "手机号为空")

    if candidate.followup_status == "发送中":
        return FollowupDecision("skip", "already_sending", "当前记录正在发送中")

    if candidate.last_followup_at and runtime_cfg.cooldown_days > 0:
        next_time = candidate.last_followup_at + timedelta(
            days=runtime_cfg.cooldown_days
        )
        if now < next_time:
            return FollowupDecision(
                "skip",
                "cooldown",
                f"冷却中，下次可发送时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}",
            )

    if _is_quiet_hours(now, runtime_cfg.quiet_start_hour, runtime_cfg.quiet_end_hour):
        return FollowupDecision("skip", "quiet_hours", "命中静默时段")

    if hour_sent_count >= runtime_cfg.hourly_cap:
        return FollowupDecision("skip", "hourly_cap_reached", "命中每小时发送上限")

    if day_sent_count >= runtime_cfg.daily_cap:
        return FollowupDecision("skip", "daily_cap_reached", "命中每日发送上限")

    if candidate.sleep_warning == "需回访":
        return FollowupDecision("send", "eligible_sleep_warning", "命中沉睡预警需回访")

    visit_ok = False
    consume_ok = False

    if candidate.last_visit_at is not None:
        visit_ok = (now - candidate.last_visit_at).days >= runtime_cfg.visit_delay_days

    if candidate.last_consume_at is not None:
        consume_ok = (
            now - candidate.last_consume_at
        ).days >= runtime_cfg.consume_delay_days

    if visit_ok:
        return FollowupDecision("send", "eligible_visit", "满足到店回访阈值")

    if consume_ok:
        return FollowupDecision("send", "eligible_consume", "满足消费回访阈值")

    if candidate.last_visit_at is None and candidate.last_consume_at is None:
        return FollowupDecision("skip", "missing_activity_data", "无到店/消费时间")

    return FollowupDecision("skip", "not_due_yet", "未达到回访触发阈值")


def _fallback_message(candidate: FollowupCandidate) -> str:
    title = candidate.nickname or "您好"
    consume_hint = (
        candidate.last_consume_summary[:30] if candidate.last_consume_summary else ""
    )
    if consume_hint:
        return f"{title}，您好！感谢您最近的到店与支持。我们已为您整理了更适合您的服务建议，如需我帮您安排下次到店时间，直接回复我即可。"
    return f"{title}，您好！感谢您近期到店，想了解您最近体验是否满意。若您方便，我可以根据您的偏好为您推荐更合适的服务。"


def _normalize_message_text(text: str) -> str:
    value = (text or "").strip().replace("\r\n", "\n")
    if not value:
        return ""
    if len(value) < 30:
        return ""
    if len(value) > 180:
        return value[:180]
    return value


def _extract_text_from_response(data: Dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        content = "\n".join(parts)

    if isinstance(content, dict):
        maybe_text = content.get("text")
        return str(maybe_text or "").strip()

    content_str = str(content).strip()
    if not content_str:
        return ""

    try:
        payload = json.loads(content_str)
        if isinstance(payload, dict):
            return str(payload.get("text") or "").strip()
    except Exception:
        pass
    return content_str


class LLMClient:
    def __init__(self, runtime_cfg: FollowupRuntimeConfig) -> None:
        self.cfg = runtime_cfg

    def _build_prompt(self, candidate: FollowupCandidate) -> str:
        visit_text = _dt_to_text(candidate.last_visit_at) or "未知"
        consume_text = _dt_to_text(candidate.last_consume_at) or "未知"
        consume_summary = candidate.last_consume_summary or "无"
        nickname = candidate.nickname or "客户"
        return (
            "你是门店客户运营助手，请生成一条中文微信回访消息。\n"
            "要求：语气自然、不过度营销、避免虚构信息、长度50-150字、包含轻量CTA。\n"
            "只返回可直接发送的纯文本消息本体；不要JSON、不要Markdown、不要代码块、不要前后解释。\n"
            f"客户昵称: {nickname}\n"
            f"最近到店时间: {visit_text}\n"
            f"最近消费时间: {consume_text}\n"
            f"最近消费摘要: {consume_summary}\n"
        )

    def compose(
        self, candidate: FollowupCandidate, prompt_override: str | None = None
    ) -> FollowupMessageResult:
        if not self.cfg.llm_base_url or not self.cfg.llm_api_key:
            fallback = _fallback_message(candidate)
            return FollowupMessageResult(
                text=fallback,
                fallback_used=True,
                reason_code="llm_config_missing",
                reason_detail="未配置LLM_BASE_URL或LLM_API_KEY，回退模板",
            )

        base = self.cfg.llm_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            url = base
        elif base.endswith("/v1"):
            url = base + "/chat/completions"
        else:
            url = base + "/v1/chat/completions"
        prompt = (prompt_override or "").strip() or self._build_prompt(candidate)

        payload = {
            "model": self.cfg.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是谨慎、专业的门店客户回访助手。仅返回可直接发送的中文纯文本，不要JSON或Markdown。",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.cfg.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.llm_api_key}",
            "Content-Type": "application/json",
        }

        retries = self.cfg.llm_retry_count
        last_error = ""
        for attempt in range(retries + 1):
            try:
                session = network_config.create_session()
                response = session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=(self.cfg.llm_timeout, self.cfg.llm_timeout),
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(
                        f"LLM可重试错误 status={response.status_code}",
                        response=response,
                    )
                response.raise_for_status()

                data = response.json()
                text = _normalize_message_text(_extract_text_from_response(data))
                if not text:
                    raise ValueError("LLM返回为空或不符合长度要求")
                return FollowupMessageResult(
                    text=text,
                    fallback_used=False,
                    reason_code="llm_ok",
                    reason_detail="LLM生成成功",
                )
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.HTTPError,
                ValueError,
            ) as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(2**attempt)
                    continue

        fallback = _fallback_message(candidate)
        logger.warning("回访LLM失败，使用模板降级: {}", last_error)
        return FollowupMessageResult(
            text=fallback,
            fallback_used=True,
            reason_code="llm_fallback",
            reason_detail=last_error or "LLM调用失败",
        )
