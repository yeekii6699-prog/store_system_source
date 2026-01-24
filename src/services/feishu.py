"""
飞书相关接口封装，统一管理 token 获取、表格数据查询与更新。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple, cast
from urllib.parse import parse_qs, urlparse

import requests
from loguru import logger

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

    # ========================= 业务方法 =========================
    def search_by_field(self, field_name: str, value: Any) -> List[Dict[str, Any]]:
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
        data = self._request("POST", self.profile_table_url + "/search", json=payload)
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

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> None:
        """
        通用记录更新方法，更新指定记录的指定字段。

        Args:
            record_id: 记录ID
            fields: 要更新的字段字典
        """
        url = f"{self.profile_table_url}/{record_id}"
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
