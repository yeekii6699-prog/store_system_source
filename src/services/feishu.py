"""
飞书相关接口封装，统一管理 token 获取、表格数据查询与更新。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple, cast
from urllib.parse import parse_qs, urlparse

import requests  # pyright: ignore[reportMissingModuleSource]
from loguru import logger  # pyright: ignore[reportMissingImports]

from src.config.settings import get_config
from src.config.network import network_config


class FeishuClient:
    """
    封装飞书多维表格 API 的常用操作。
    FEISHU_TABLE_URL 与 FEISHU_PROFILE_TABLE_URL 需填记录接口地址:
    https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        task_table_url: str | None = None,
        profile_table_url: str | None = None,
        activation_table_url: str | None = None,
    ) -> None:
        # 先初始化 token 相关字段，避免后续 normalize 过程中调用 get_token 时未定义
        self._tenant_access_token: str | None = None
        self._token_expire_at: float = 0.0

        # API请求频率控制
        self._last_request_time = 0.0
        self._min_request_interval = 0.5  # 最小请求间隔（秒），避免触发频率限制
        self._max_retries = 3  # 最大重试次数
        self._retry_backoff_factor = 2.0  # 重试退避因子

        cfg = get_config()
        self._min_request_interval = float(cfg.get("FEISHU_RATE_LIMIT_COOLDOWN") or 0.5)
        self.app_id = app_id or cfg["FEISHU_APP_ID"]
        self.app_secret = app_secret or cfg["FEISHU_APP_SECRET"]
        self._wiki_token_cache: Dict[str, str] = {}
        task_url = task_table_url or cfg["FEISHU_TABLE_URL"]
        profile_url = profile_table_url or cfg["FEISHU_PROFILE_TABLE_URL"]
        self.task_table_url = self._normalize_table_url(task_url)
        self.profile_table_url = self._normalize_table_url(profile_url)
        self.profile_field_phone = cfg.get("FEISHU_FIELD_PHONE", "") or "手机号"
        self.profile_field_name = cfg.get("FEISHU_FIELD_NAME", "") or "姓名"
        self.profile_field_remark = cfg.get("FEISHU_FIELD_REMARK", "") or "微信备注"
        self.followup_field_last_visit = (
            cfg.get("FEISHU_FIELD_LAST_VISIT", "") or "最近到店时间"
        )
        self.followup_field_last_consume = (
            cfg.get("FEISHU_FIELD_LAST_CONSUME", "") or "最近消费时间"
        )
        self.followup_field_consume_summary = (
            cfg.get("FEISHU_FIELD_CONSUME_SUMMARY", "") or "最近消费摘要"
        )
        self.followup_field_status = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_STATUS", "") or "回访状态"
        )
        self.followup_field_last_sent_at = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_LAST_SENT_AT", "") or "回访发送时间"
        )
        self.followup_field_reason = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_REASON", "") or "回访原因"
        )
        self.followup_field_snapshot = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_SNAPSHOT", "") or "回访快照指纹"
        )
        self.followup_field_message = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_MESSAGE", "") or "回访消息"
        )
        self.followup_field_attempts = (
            cfg.get("FEISHU_FIELD_FOLLOWUP_ATTEMPTS", "") or "回访尝试次数"
        )
        self.followup_field_sleep_warning = "沉睡预警"
        self.followup_need_value = "需回访"
        self._followup_status_candidates: Tuple[str, ...] = (
            "回访状态",
            "回访发送状态",
            "跟进状态",
            "回访进度",
            "状态",
            "followup_status",
            "FollowupStatus",
        )
        self._followup_last_sent_at_candidates: Tuple[str, ...] = (
            "回访发送时间",
            "回访时间",
            "最近回访时间",
            "followup_last_sent_at",
            "FollowupLastSentAt",
        )
        self._profile_field_names_cache: List[str] = []
        self._profile_field_names_cache_at: float = 0.0
        self._profile_field_cache_ttl: float = 300.0
        # 激活码表URL
        activation_url = (
            activation_table_url or cfg.get("ACTIVATION_TABLE_URL", "").strip()
        )
        self.activation_table_url = (
            self._normalize_table_url(activation_url) if activation_url else None
        )
        self.activation_field_code = cfg.get("ACTIVATION_FIELD_CODE", "") or "激活码"

    # ========================= 基础请求 =========================
    def get_token(self) -> str:
        """
        获取租户 token，自动刷新并缓存，避免频繁请求。
        """
        now = time.time()
        if self._tenant_access_token and now < self._token_expire_at - 60:
            return self._tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}

        # 使用网络配置的请求方法
        try:
            session = network_config.create_session()
            logger.debug(
                "获取飞书访问令牌: 网络配置 {}", network_config.get_network_info()
            )
            resp = session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

        except requests.exceptions.SSLError as ssl_err:
            logger.error(
                "飞书API SSL连接失败: {} - 可能是网络环境问题或证书问题", ssl_err
            )
            raise RuntimeError(f"无法连接到飞书服务器，SSL错误: {ssl_err}")
        except requests.exceptions.ConnectionError as conn_err:
            logger.error("飞书API连接失败: {} - 请检查网络连接", conn_err)
            raise RuntimeError(f"无法连接到飞书服务器，网络错误: {conn_err}")
        except requests.exceptions.Timeout as timeout_err:
            logger.error("飞书API请求超时: {} - 请检查网络状态", timeout_err)
            raise RuntimeError(f"飞书服务器响应超时: {timeout_err}")
        except Exception as e:
            logger.error("获取飞书访问令牌时发生未知错误: {}", e)
            raise

        token = data["tenant_access_token"]
        expire = int(data.get("expire", 0))
        self._tenant_access_token = token
        self._token_expire_at = now + expire
        logger.debug(
            "刷新飞书 tenant_access_token 成功，过期时间 {}", self._token_expire_at
        )
        return token

    def _headers(self) -> Dict[str, str]:
        token = self.get_token()
        return {"Authorization": f"Bearer {token}"}

    def _extract_record_id(self, record: Dict[str, Any]) -> str:
        """
        从飞书记录对象中提取 record_id，兼容不同的字段名格式。

        Args:
            record: 飞书 API 返回的记录对象

        Returns:
            record_id 字符串，如果未找到则返回空字符串
        """
        if not record:
            return ""

        # 尝试两种可能的字段名
        record_id = record.get("record_id") or record.get("recordId")
        return record_id or ""

    def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        """
        简化请求发送与错误检查，包含频率限制和重试机制。

        Args:
            method: HTTP方法
            url: 请求URL
            **kwargs: 其他请求参数

        Returns:
            API响应数据

        Raises:
            requests.HTTPError: HTTP请求错误
            RuntimeError: API业务错误
        """
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        # 使用网络配置创建会话
        session = kwargs.pop("session", None) or network_config.create_session()

        # 频率限制：确保最小请求间隔
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            logger.debug("API频率限制，等待 {:.2f} 秒", sleep_time)
            time.sleep(sleep_time)

        last_exception: Exception | None = None
        resp: requests.Response | None = None

        # 重试机制
        for attempt in range(self._max_retries + 1):
            try:
                self._last_request_time = time.time()
                response = cast(
                    requests.Response,
                    session.request(method, url, headers=headers, **kwargs),
                )
                resp = response
                response.raise_for_status()

                data = response.json()
                if data.get("code") not in (0,):
                    raise RuntimeError(
                        f"飞书接口返回异常 code={data.get('code')} msg={data.get('msg')} data={data}"
                    )

                logger.debug(
                    "API请求成功: {} {} (尝试次数: {})", method, url, attempt + 1
                )
                return data

            except requests.HTTPError as http_err:
                last_exception = http_err
                if resp is None:
                    raise
                resp = cast(requests.Response, resp)
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text

                # 根据错误类型决定是否重试
                if (
                    resp.status_code in (429, 502, 503, 504)
                    and attempt < self._max_retries
                ):
                    # 429 Too Many Requests 或 5xx 服务器错误，适合重试
                    wait_time = self._retry_backoff_factor ** (attempt + 1)
                    logger.warning(
                        "API请求失败 (可重试), 将在 {:.1f} 秒后重试: {} | 状态码: {} | 响应: {}",
                        wait_time,
                        http_err,
                        resp.status_code,
                        str(body)[:200],
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # 4xx 客户端错误或超过重试次数，直接抛出
                    logger.error(
                        "飞书 HTTP 错误: {} | 状态码: {} | 响应: {}",
                        http_err,
                        resp.status_code,
                        str(body)[:500],
                    )
                    raise

            except (requests.ConnectionError, requests.Timeout) as conn_err:
                last_exception = conn_err
                # 网络连接错误，适合重试
                if attempt < self._max_retries:
                    wait_time = self._retry_backoff_factor ** (attempt + 1)
                    logger.warning(
                        "网络连接错误, 将在 {:.1f} 秒后重试: {}", wait_time, conn_err
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error("网络连接错误，已达到最大重试次数: {}", conn_err)
                    raise

        # 所有重试都失败了
        logger.error("API请求失败，已达到最大重试次数: {}", last_exception)
        if last_exception is None:
            raise RuntimeError("API请求失败，未捕获具体异常")
        assert last_exception is not None
        raise last_exception

    # ========================= 辅助工具 =========================
    def _normalize_table_url(self, table_url: str) -> str:
        """
        支持正常 Bitable API URL 也支持 Wiki 链接。
        - 如果链接来自 Wiki (/wiki/<token>?table=tblxxx)，先换算为 Base obj_token
        - 最终输出格式: https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
        """
        parsed = urlparse(table_url)
        parts = [p for p in parsed.path.split("/") if p]

        # Wiki 链接：需要先通过 API 换索引 token
        if "wiki" in parts:
            wiki_index = parts.index("wiki")
            if wiki_index + 1 >= len(parts):
                raise ValueError("Wiki 链接缺少 token")
            wiki_token = parts[wiki_index + 1]
            table_id = self._extract_table_id(parsed)
            base_token = self._resolve_wiki_token(wiki_token)
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records"
            logger.debug(
                "Wiki 链接已换算为表格: wiki_token={} -> base_token={}",
                wiki_token,
                base_token,
            )
            return url.rstrip("/")

        # 正常 API 路径：直接解析 app_token 和 table_id 再重构
        if "apps" in parts and "tables" in parts:
            app_token, table_id = self._parse_table_info_from_api_path(parts)
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
            return url.rstrip("/")

        raise ValueError("不支持的表格链接格式，请使用 Bitable 或 Wiki 链接")

    def _extract_table_id(self, parsed_url) -> str:
        query = {k.lower(): v for k, v in parse_qs(parsed_url.query).items()}
        for key in ("table", "table_id", "tableid"):
            if key in query and query[key]:
                return query[key][0]
        raise ValueError("没有从 URL 参数中找到 table_id，请检查链接的 table= 参数")

    def _parse_table_info_from_api_path(self, parts: List[str]) -> Tuple[str, str]:
        if "apps" not in parts or "tables" not in parts:
            raise ValueError("表格 URL 格式异常，缺少 apps/tables 段")
        app_token = parts[parts.index("apps") + 1]
        table_id = parts[parts.index("tables") + 1]
        if not app_token or not table_id:
            raise ValueError("无法从表格 URL 解析 app_token 或 table_id")
        return app_token, table_id

    def _parse_table_info(self, table_url: str) -> Tuple[str, str]:
        """
        从表格链接提取 app_token 和 table_id，无论是 API 链接还是 Wiki 链接。
        """
        normalized = self._normalize_table_url(table_url)
        parts = [p for p in urlparse(normalized).path.split("/") if p]
        return self._parse_table_info_from_api_path(parts)

    def _resolve_wiki_token(self, wiki_token: str) -> str:
        """
        通过 Wiki token 获取其对应的 Bitable obj_token（Base token）。
        结果会缓存，防止重复请求。
        """
        if wiki_token in self._wiki_token_cache:
            return self._wiki_token_cache[wiki_token]

        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
        params = {"obj_type": "wiki", "token": wiki_token}
        data = self._request("GET", url, params=params)
        obj_token = data.get("data", {}).get("node", {}).get("obj_token")
        if not obj_token:
            raise RuntimeError(f"无法将 Wiki token 换算为 Base token：{data}")

        self._wiki_token_cache[wiki_token] = obj_token
        return obj_token

    def list_fields(self, table_url: str) -> List[Dict[str, Any]]:
        """
        获取表格字段列表，便于调试。
        """
        app_token, table_id = self._parse_table_info(table_url)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        data = self._request("GET", url)
        return data.get("data", {}).get("items", [])

    def list_records(self, table_url: str, page_size: int = 5) -> List[Dict[str, Any]]:
        params = {"page_size": page_size}
        normalized = self._normalize_table_url(table_url)
        data = self._request("GET", normalized, params=params)
        return data.get("data", {}).get("items", [])

    def _search_records_paginated(
        self,
        table_url: str,
        conditions: List[Dict[str, Any]],
        page_size: int = 200,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token = ""
        normalized_page_size = max(1, min(page_size, 500))

        while True:
            payload: Dict[str, Any] = {
                "filter": {
                    "conjunction": "and",
                    "conditions": conditions,
                },
                "page_size": normalized_page_size,
            }
            if page_token:
                payload["page_token"] = page_token

            data = self._request("POST", table_url + "/search", json=payload)
            data_block = data.get("data", {})
            batch = data_block.get("items", [])
            if isinstance(batch, list):
                items.extend(batch)

            has_more = bool(data_block.get("has_more"))
            page_token = str(data_block.get("page_token") or "").strip()
            if not has_more or not page_token:
                break

        return items

    def _list_records_paginated(
        self,
        table_url: str,
        page_size: int = 200,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token = ""
        normalized = self._normalize_table_url(table_url)
        normalized_page_size = max(1, min(page_size, 500))

        while True:
            params: Dict[str, Any] = {"page_size": normalized_page_size}
            if page_token:
                params["page_token"] = page_token

            data = self._request("GET", normalized, params=params)
            data_block = data.get("data", {})
            batch = data_block.get("items", [])
            if isinstance(batch, list):
                items.extend(batch)

            has_more = bool(data_block.get("has_more"))
            page_token = str(data_block.get("page_token") or "").strip()
            if not has_more or not page_token:
                break

        return items

    @staticmethod
    def _dedupe_records_by_id(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("record_id") or item.get("recordId") or "").strip()
            if not record_id:
                continue
            if record_id in seen:
                continue
            seen.add(record_id)
            deduped.append(item)
        return deduped

    @staticmethod
    def _timestamp_to_text(ts: int) -> str:
        if ts <= 0:
            return ""
        value = float(ts)
        if value > 1e12:
            value /= 1000.0
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
        except Exception:
            return ""

    def _normalize_followup_record(self, item: Dict[str, Any]) -> Dict[str, Any]:
        record_id = self._extract_record_id(item)
        fields = item.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}

        sent_ts = self._extract_followup_sent_ts(fields)
        return {
            "record_id": record_id,
            "customer": self._safe_get_first_str(
                fields.get("昵称")
                or fields.get("姓名")
                or fields.get(self.profile_field_name)
            ),
            "wechat_id": self._safe_get_first_str(fields.get("微信号")),
            "phone": self._extract_phone_text(
                fields.get(self.profile_field_phone) or fields.get("手机号")
            ),
            "sleep_warning": self._safe_get_first_str(
                fields.get(self.followup_field_sleep_warning)
            ),
            "followup_status": self._extract_followup_status_text(fields),
            "followup_message": self._safe_get_first_str(
                fields.get(self.followup_field_message)
            ),
            "followup_reason": self._safe_get_first_str(
                fields.get(self.followup_field_reason)
            ),
            "followup_last_sent_ts": sent_ts,
            "followup_last_sent_text": self._timestamp_to_text(sent_ts),
        }

    def _search_followup_by_status(
        self,
        status_value: str,
        page_size: int = 200,
    ) -> List[Dict[str, Any]]:
        candidates: List[str] = []
        resolved = self._resolve_followup_status_field()
        for name in [resolved, *self._followup_status_candidates]:
            field_name = (name or "").strip()
            if field_name and field_name not in candidates:
                candidates.append(field_name)

        for index, field_name in enumerate(candidates):
            try:
                records = self._search_records_paginated(
                    self.profile_table_url,
                    conditions=[
                        {
                            "field_name": field_name,
                            "operator": "is",
                            "value": [status_value],
                        }
                    ],
                    page_size=page_size,
                )
                if self.followup_field_status != field_name:
                    self.followup_field_status = field_name
                return records
            except Exception as exc:
                if self._is_invalid_filter_error(exc):
                    if index == 0:
                        self._resolve_followup_status_field(force_refresh=True)
                    continue
                raise

        all_records = self._list_records_paginated(
            self.profile_table_url, page_size=page_size
        )
        filtered: List[Dict[str, Any]] = []
        for record in all_records:
            fields = record.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if self._extract_followup_status_text(fields) == status_value:
                filtered.append(record)
        return filtered

    def fetch_followup_record_groups(
        self, page_size: int = 200
    ) -> Dict[str, List[Dict[str, Any]]]:
        pending_items = self._search_records_paginated(
            self.profile_table_url,
            conditions=[
                {
                    "field_name": self.followup_field_sleep_warning,
                    "operator": "is",
                    "value": [self.followup_need_value],
                }
            ],
            page_size=page_size,
        )

        completed_items: List[Dict[str, Any]] = []
        for status_value in ("已回访", "已发送"):
            completed_items.extend(
                self._search_followup_by_status(status_value, page_size=page_size)
            )

        pending_normalized = [
            self._normalize_followup_record(item) for item in pending_items
        ]
        pending_normalized = [
            item for item in pending_normalized if str(item.get("phone") or "").strip()
        ]
        completed_normalized = [
            self._normalize_followup_record(item)
            for item in self._dedupe_records_by_id(completed_items)
        ]
        return {
            "pending": pending_normalized,
            "completed": completed_normalized,
        }

    @staticmethod
    def _safe_get_first_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            value = value[0] if value else ""
        return str(value).strip()

    @staticmethod
    def _extract_phone_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return FeishuClient._extract_phone_text(value[0] if value else "")
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

    @staticmethod
    def _normalize_field_name(value: str) -> str:
        return (value or "").strip().replace(" ", "").replace("_", "").lower()

    @staticmethod
    def _extract_field_names(field_items: List[Dict[str, Any]]) -> List[str]:
        names: List[str] = []
        for item in field_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("field_name") or "").strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _is_invalid_filter_error(exc: Exception) -> bool:
        text = str(exc)
        return "InvalidFilter" in text and "field_name" in text

    def _get_profile_field_names(self, force_refresh: bool = False) -> List[str]:
        now = time.time()
        if (
            not force_refresh
            and self._profile_field_names_cache
            and now - self._profile_field_names_cache_at < self._profile_field_cache_ttl
        ):
            return self._profile_field_names_cache

        try:
            fields = self.list_fields(self.profile_table_url)
            names = self._extract_field_names(fields)
            if names:
                self._profile_field_names_cache = names
                self._profile_field_names_cache_at = now
                return names
        except Exception as exc:
            logger.debug("读取客户表字段失败，跳过字段缓存刷新: {}", exc)

        return self._profile_field_names_cache

    def _resolve_field_from_candidates(
        self,
        configured_field: str,
        candidates: Tuple[str, ...],
        force_refresh: bool = False,
    ) -> str:
        all_candidates: List[str] = []
        for candidate in [configured_field, *candidates]:
            name = (candidate or "").strip()
            if name and name not in all_candidates:
                all_candidates.append(name)

        if not all_candidates:
            return configured_field

        field_names = self._get_profile_field_names(force_refresh=force_refresh)
        if not field_names:
            return all_candidates[0]

        # 优先精确匹配
        for candidate in all_candidates:
            if candidate in field_names:
                return candidate

        # 再做归一化匹配
        normalized_map = {
            self._normalize_field_name(name): name
            for name in field_names
            if self._normalize_field_name(name)
        }
        for candidate in all_candidates:
            mapped = normalized_map.get(self._normalize_field_name(candidate))
            if mapped:
                return mapped

        return all_candidates[0]

    def _resolve_followup_status_field(self, force_refresh: bool = False) -> str:
        resolved = self._resolve_field_from_candidates(
            configured_field=self.followup_field_status,
            candidates=self._followup_status_candidates,
            force_refresh=force_refresh,
        )
        self.followup_field_status = resolved
        return resolved

    def _extract_followup_status_text(self, fields: Dict[str, Any]) -> str:
        keys: List[str] = []
        for key in [self.followup_field_status, *self._followup_status_candidates]:
            name = (key or "").strip()
            if name and name not in keys:
                keys.append(name)

        for key in keys:
            if key in fields:
                return self._safe_get_first_str(fields.get(key))

        return ""

    def _extract_followup_sent_ts(self, fields: Dict[str, Any]) -> int:
        keys: List[str] = []
        for key in [
            self.followup_field_last_sent_at,
            *self._followup_last_sent_at_candidates,
        ]:
            name = (key or "").strip()
            if name and name not in keys:
                keys.append(name)

        for key in keys:
            raw_ts = fields.get(key)
            if isinstance(raw_ts, (int, float)):
                return int(raw_ts)
            if isinstance(raw_ts, str):
                raw_text = raw_ts.strip()
                if raw_text.isdigit():
                    return int(raw_text)

        return 0

    # ========================= 业务方法 =========================
    def search_by_field(
        self, field_name: str, value: Any, table_url: str | None = None
    ) -> List[Dict[str, Any]]:
        """
        通用字段搜索方法，根据指定字段和值查询记录。

        Args:
            field_name: 字段名称
            value: 要搜索的值

        Returns:
            匹配的记录列表
        """
        payload = {
            "filter": {
                "conditions": [
                    {
                        "field_name": field_name,
                        "operator": "is",
                        "value": [value],
                    }
                ],
                "conjunction": "and",
            }
        }
        logger.debug("搜索字段 [{}] = {}", field_name, value)

        # 默认查询客户表，可显式指定目标表
        target_url = table_url or self.profile_table_url

        data = self._request("POST", target_url + "/search", json=payload)
        return data.get("data", {}).get("items", [])

    def search_customer(self, phone: str) -> Tuple[bool, str, str]:
        """
        在客户表按手机号查询，返回 (是否存在, 状态, 姓名)。
        """
        if not isinstance(phone, str):
            phone = str(phone)

        items = self.search_by_field(self.profile_field_phone, phone)
        if not items:
            return False, "", ""

        record = items[0].get("fields", {})
        status = record.get("微信绑定状态", "")
        name = record.get("姓名", "")
        return True, status, name

    def search_by_nickname(self, nickname: str) -> List[Dict[str, Any]]:
        """
        按昵称查询客户表记录，用于被动监控时匹配"已通过"的好友。

        Args:
            nickname: 昵称字符串

        Returns:
            匹配的记录列表
        """
        if not nickname or not nickname.strip():
            return []
        return self.search_by_field("昵称", nickname.strip())

    def fetch_new_tasks(self) -> List[Dict[str, Any]]:
        """
        获取客户表中“微信绑定状态”为“待添加”的记录，作为待处理任务。
        """
        return self.fetch_tasks_by_status(["待添加"])

    def fetch_tasks_by_status(self, statuses: List[str]) -> List[Dict[str, Any]]:
        """按状态拉取任务，支持单选字段多状态查询（多次查询合并结果）。"""
        values = [status for status in statuses if status]
        if not values:
            return []

        # 如果只有一个状态，直接查询
        if len(values) == 1:
            payload = {
                "filter": {
                    "conditions": [
                        {
                            "field_name": "微信绑定状态",
                            "operator": "is",
                            "value": values,
                        }
                    ],
                    "conjunction": "and",
                }
            }
            logger.debug("按状态拉取任务，payload={}", payload)
            data = self._request(
                "POST", self.profile_table_url + "/search", json=payload
            )
            return data.get("data", {}).get("items", [])

        # 多个状态：分别查询后合并（飞书单选字段不支持一次查多个值）
        all_items: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for status in values:
            payload = {
                "filter": {
                    "conditions": [
                        {
                            "field_name": "微信绑定状态",
                            "operator": "is",
                            "value": [status],
                        }
                    ],
                    "conjunction": "and",
                }
            }
            logger.debug("按状态拉取任务 [{}]，payload={}", status, payload)
            try:
                data = self._request(
                    "POST", self.profile_table_url + "/search", json=payload
                )
                items = data.get("data", {}).get("items", [])
                for item in items:
                    record_id = self._extract_record_id(item)
                    if record_id and record_id not in seen_ids:
                        seen_ids.add(record_id)
                        all_items.append(item)
            except Exception as e:
                logger.warning("查询状态 [{}] 失败: {}", status, e)
                continue
        return all_items

    def mark_processed(self, record_id: str) -> None:
        """
        将客户表记录标记为“已添加”，避免重复处理。
        """
        url = f"{self.profile_table_url}/{record_id}"
        payload = {"fields": {"微信绑定状态": "已添加"}}
        logger.debug("标记任务已处理(已添加): {}", record_id)
        self._request("PUT", url, json=payload)

    def mark_failed(self, record_id: str) -> None:
        """
        将客户表记录标记为“添加失败”，方便后续人工处理。
        """
        url = f"{self.profile_table_url}/{record_id}"
        payload = {"fields": {"微信绑定状态": "添加失败"}}
        logger.debug("标记任务添加失败: {}", record_id)
        self._request("PUT", url, json=payload)

    def update_status(self, record_id: str, status: str) -> None:
        """
        通用状态更新入口，便于双队列流程设置"已申请""已绑定"等值。
        """
        self.update_record(record_id, {"微信绑定状态": status})

    def fetch_followup_candidates(self, page_size: int = 20) -> List[Dict[str, Any]]:
        """拉取可用于自动回访的候选记录（沉睡预警=需回访）。"""
        resolved_followup_status = self._resolve_followup_status_field()
        items = self._search_records_paginated(
            self.profile_table_url,
            conditions=[
                {
                    "field_name": self.followup_field_sleep_warning,
                    "operator": "is",
                    "value": [self.followup_need_value],
                }
            ],
            page_size=max(1, min(page_size, 200)),
        )
        normalized: List[Dict[str, Any]] = []
        for item in items:
            fields = item.get("fields", {})
            phone = self._extract_phone_text(
                fields.get(self.profile_field_phone) or fields.get("手机号")
            )
            if not phone:
                continue
            merged_fields = dict(fields)
            merged_fields["followup_phone"] = phone
            merged_fields["followup_sleep_warning"] = fields.get(
                self.followup_field_sleep_warning
            )
            merged_fields["followup_last_visit"] = fields.get(
                self.followup_field_last_visit
            )
            merged_fields["followup_last_consume"] = fields.get(
                self.followup_field_last_consume
            )
            merged_fields["followup_consume_summary"] = fields.get(
                self.followup_field_consume_summary
            )
            merged_fields["followup_status"] = fields.get(resolved_followup_status)
            if merged_fields["followup_status"] is None:
                merged_fields["followup_status"] = self._extract_followup_status_text(
                    fields
                )
            merged_fields["followup_last_sent_at"] = fields.get(
                self.followup_field_last_sent_at
            )
            if merged_fields["followup_last_sent_at"] is None:
                merged_fields["followup_last_sent_at"] = self._extract_followup_sent_ts(
                    fields
                )
            merged_fields["followup_snapshot"] = fields.get(
                self.followup_field_snapshot
            )
            merged_fields["followup_attempts"] = fields.get(
                self.followup_field_attempts
            )

            normalized.append(
                {
                    "record_id": self._extract_record_id(item),
                    "recordId": self._extract_record_id(item),
                    "fields": merged_fields,
                }
            )
        return normalized

    def update_followup_state(self, record_id: str, fields: Dict[str, Any]) -> None:
        """更新回访状态相关字段（自动映射配置化字段名）。"""
        resolved_followup_status = self._resolve_followup_status_field()
        mapped: Dict[str, Any] = {}
        for key, value in fields.items():
            if key == "followup_status":
                mapped[resolved_followup_status] = value
            elif key == "followup_last_sent_at":
                mapped[self.followup_field_last_sent_at] = value
            elif key == "followup_reason":
                mapped[self.followup_field_reason] = value
            elif key == "followup_snapshot":
                mapped[self.followup_field_snapshot] = value
            elif key == "followup_message":
                mapped[self.followup_field_message] = value
            elif key == "followup_attempts":
                mapped[self.followup_field_attempts] = value
            else:
                mapped[key] = value
        self.update_record(record_id, mapped)

    def count_followup_sent_since(self, start_ts: int, end_ts: int) -> int:
        """统计给定时间窗口内已发送回访记录数（按发送时间字段）。"""

        def _count_from_items(items: List[Dict[str, Any]]) -> int:
            count = 0
            for item in items:
                fields = item.get("fields", {})
                if not isinstance(fields, dict):
                    continue
                ts = self._extract_followup_sent_ts(fields)
                if start_ts <= ts <= end_ts:
                    count += 1
            return count

        def _search_by_status_field(field_name: str) -> int:
            payload = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {
                            "field_name": field_name,
                            "operator": "is",
                            "value": ["已发送"],
                        }
                    ],
                },
                "page_size": 200,
            }
            data = self._request(
                "POST", self.profile_table_url + "/search", json=payload
            )
            items = data.get("data", {}).get("items", [])
            return _count_from_items(items)

        candidates: List[str] = []
        resolved = self._resolve_followup_status_field()
        for name in [resolved, *self._followup_status_candidates]:
            field_name = (name or "").strip()
            if field_name and field_name not in candidates:
                candidates.append(field_name)

        for index, field_name in enumerate(candidates):
            try:
                count = _search_by_status_field(field_name)
                if self.followup_field_status != field_name:
                    logger.info(
                        "回访状态字段自动切换: {} -> {}",
                        self.followup_field_status,
                        field_name,
                    )
                    self.followup_field_status = field_name
                return count
            except Exception as exc:
                if self._is_invalid_filter_error(exc):
                    if index == 0:
                        # 首次失败时，刷新字段缓存后再继续候选字段
                        self._resolve_followup_status_field(force_refresh=True)
                    logger.warning(
                        "回访状态字段不可用 [{}]，尝试下一个候选字段", field_name
                    )
                    continue
                raise

        logger.warning("回访状态字段过滤全部失败，回退为全表扫描统计已发送记录")
        records = self.list_records(self.profile_table_url, page_size=500)
        filtered: List[Dict[str, Any]] = []
        for record in records:
            fields = record.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if self._extract_followup_status_text(fields) == "已发送":
                filtered.append(record)
        return _count_from_items(filtered)

    def update_record(
        self, record_id: str, fields: Dict[str, Any], table_url: str | None = None
    ) -> None:
        """
        通用记录更新方法，更新指定记录的指定字段。

        Args:
            record_id: 记录ID
            fields: 要更新的字段字典
            table_url: 表格URL（可选，默认使用profile_table_url）
        """
        target_url = table_url or self.profile_table_url
        url = f"{target_url}/{record_id}"
        payload = {"fields": fields}
        logger.debug("更新记录 {}: {}", record_id, fields)
        self._request("PUT", url, json=payload)

    def batch_update_status(self, record_ids: List[str], status: str) -> int:
        """
        批量更新记录状态。

        Args:
            record_ids: 记录ID列表
            status: 要设置的状态值

        Returns:
            成功更新的记录数
        """
        success_count = 0
        for record_id in record_ids:
            try:
                self.update_status(record_id, status)
                success_count += 1
            except Exception as e:
                logger.warning("批量更新状态失败 [{}]: {}", record_id, e)
        logger.info("批量更新状态完成: 成功 {}/{}", success_count, len(record_ids))
        return success_count

    # ========================= 被动写入资料 =========================
    def _find_profile_by_phone(self, phone: str) -> str | None:
        """按手机号搜索客户表，返回 record_id（若存在）。"""
        items = self.search_by_field(self.profile_field_phone, phone)
        if not items:
            return None
        return self._extract_record_id(items[0])

    def upsert_contact_profile(
        self,
        wechat_id: str,
        nickname: str | None = None,
        phone: str | None = None,
        remark: str | None = None,
        status: str | None = None,
    ) -> str:
        """
        将微信号/手机号写入飞书，若已存在则更新，否则创建记录。
        若指定 status，则同时更新"微信绑定状态"字段。

        搜索优先级：
        1. 先按手机号搜索
        2. 找不到则按昵称搜索（用于被动加好友时匹配主动添加的记录）
        3. 都找不到才新建

        Args:
            wechat_id: 微信号（存入微信号字段）
            nickname: 昵称（存入昵称字段）
            phone: 手机号（存入手机号字段）
            remark: 备注（存入微信备注字段）
            status: 状态值（如"已绑定"），用于直接设置微信绑定状态

        Returns:
            record_id: 记录 ID（存在或新建）
        """
        wechat_id = (wechat_id or "").strip()
        if not wechat_id:
            raise ValueError("wechat_id is required for upsert_contact_profile")

        # 构建字段
        fields: Dict[str, Any] = {"微信号": wechat_id}
        if nickname:
            fields["昵称"] = nickname
        if phone:
            fields["手机号"] = phone
        if remark:
            fields[self.profile_field_remark] = remark
        if status:
            fields["微信绑定状态"] = status

        # 1. 先按手机号搜索（如果传入了手机号）
        if phone:
            record_id = self._find_profile_by_phone(phone)
            if record_id:
                # 更新微信号和状态，保留其他字段
                update_fields = {"微信号": wechat_id}
                if status:
                    update_fields["微信绑定状态"] = status
                self.update_record(record_id, update_fields)
                logger.debug(
                    "被动写入：按手机号找到并更新记录 {} -> {}",
                    record_id,
                    update_fields,
                )
                return record_id

        # 2. 按昵称搜索（用于被动加好友时匹配主动添加的记录）
        if nickname:
            items = self.search_by_field("昵称", nickname)
            if items:
                record_id = self._extract_record_id(items[0])
                # 只更新微信号和状态
                update_fields = {"微信号": wechat_id}
                if phone:
                    update_fields["手机号"] = phone
                if status:
                    update_fields["微信绑定状态"] = status
                self.update_record(record_id, update_fields)
                logger.debug(
                    "被动写入：按昵称找到并更新记录 {} -> {}", record_id, update_fields
                )
                return record_id

        # 3. 都找不到，新建记录
        record_id = self.create_record(fields)
        logger.debug("被动写入：新增记录 {} -> {}", record_id, fields)
        return record_id

    def create_record(self, fields: Dict[str, Any]) -> str:
        """
        在客户表创建新记录。

        Args:
            fields: 要创建的字段字典

        Returns:
            record_id: 新创建的记录 ID
        """
        data = self._request("POST", self.profile_table_url, json={"fields": fields})
        record = data.get("data", {}).get("record", {})
        return self._extract_record_id(record)

    # ========================= 激活码操作 =========================
    def search_activation_code(self, code: str) -> List[Dict[str, Any]]:
        """按激活码搜索记录"""
        if not self.activation_table_url:
            raise ValueError("未配置激活码表URL")
        return self.search_by_field(
            self.activation_field_code, code, self.activation_table_url
        )

    def update_activation_status(
        self, record_id: str, status: str, machine_id: str | None = None
    ) -> None:
        """更新激活码状态，并可选写入机器ID"""
        if not self.activation_table_url:
            raise ValueError("未配置激活码表URL")

        fields: Dict[str, Any] = {"使用状态": status}
        if machine_id:
            fields["机器ID"] = machine_id

        try:
            self.update_record(record_id, fields, self.activation_table_url)
            return
        except RuntimeError as exc:
            if "FieldNameNotFound" not in str(exc):
                raise

        # 兼容历史字段名“状态”
        fallback_fields: Dict[str, Any] = {"状态": status}
        if machine_id:
            fallback_fields["机器ID"] = machine_id
        self.update_record(record_id, fallback_fields, self.activation_table_url)

    def get_activation_record(self, code: str) -> Dict[str, Any] | None:
        """获取激活码记录详情"""
        items = self.search_activation_code(code)
        return items[0] if items else None

    def activate_code_record(
        self,
        record_id: str,
        machine_id: str,
        activated_at: int,
        expires_at: int,
        phone: str | None = None,
    ) -> None:
        """标记激活码为已使用（日期参数为Unix时间戳毫秒）"""
        if not self.activation_table_url:
            raise ValueError("未配置激活码表URL")

        fields: Dict[str, Any] = {
            "使用状态": "已激活",
            "机器ID": machine_id,
            "激活时间": activated_at,
            "到期时间": expires_at,
        }

        if phone:
            fields["联系电话"] = phone

        self.update_record(record_id, fields, self.activation_table_url)

    def create_activation_code_record(
        self,
        code: str,
        validity_days: int,
        customer_name: str | None = None,
        remark: str | None = None,
    ) -> str:
        """创建新的激活码记录"""
        if not self.activation_table_url:
            raise ValueError("未配置激活码表URL")

        fields: Dict[str, Any] = {
            "激活码": code,
            "时长（天）": validity_days,
            "状态": "未使用",
        }

        if customer_name:
            fields["客户名称"] = customer_name

        if remark:
            fields["备注"] = remark

        data = self._request("POST", self.activation_table_url, json={"fields": fields})
        record = data.get("data", {}).get("record", {})
        return self._extract_record_id(record)

    def batch_create_activation_codes(
        self,
        count: int,
        validity_days: int,
        customer_name: str | None = None,
        remark: str | None = None,
    ) -> List[str]:
        """批量创建激活码"""
        import secrets
        import string

        def _generate_activation_code(length: int = 16) -> str:
            alphabet = string.ascii_uppercase + string.digits
            code = "".join(secrets.choice(alphabet) for _ in range(length))
            return "-".join(code[i : i + 4] for i in range(0, length, 4))

        record_ids = []
        for _ in range(count):
            code = _generate_activation_code()
            record_id = self.create_activation_code_record(
                code=code,
                validity_days=validity_days,
                customer_name=customer_name,
                remark=remark,
            )
            record_ids.append(record_id)

        return record_ids
