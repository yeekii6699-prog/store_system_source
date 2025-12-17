"""
网络配置管理模块
处理VPN、代理、SSL等网络相关配置
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Any, Optional, Tuple
from loguru import logger

try:
    import requests
    from requests.adapters import HTTPAdapter
    import urllib.parse
except ImportError:
    requests = None

from .settings import get_config


class NetworkConfig:
    """网络配置管理类，处理代理、SSL等设置"""

    def __init__(self):
        self._load_config()
        self._detect_network_environment()

    def _load_config(self) -> None:
        """加载网络配置"""
        config = get_config()

        self.proxy_url = config.get("NETWORK_PROXY", "").strip()
        self.verify_ssl = config.get("NETWORK_VERIFY_SSL", "1") == "1"
        self.timeout = int(config.get("NETWORK_TIMEOUT", "15"))
        self.use_system_proxy = config.get("NETWORK_USE_SYSTEM_PROXY", "0") == "1"

    def _detect_network_environment(self) -> None:
        """自动检测网络环境"""
        self.system_proxy = self._get_system_proxy()
        self.has_vpn = self._detect_vpn()

        if self.has_vpn:
            logger.info("🟡 检测到VPN或代理环境，将调整网络配置")

        if self.system_proxy:
            logger.info("🔵 检测到系统代理: {}", self.system_proxy)

    def _get_system_proxy(self) -> Dict[str, str]:
        """获取系统代理设置"""
        try:
            import urllib.request
            proxies = urllib.request.getproxies()
            return {k: v for k, v in proxies.items() if v and k.lower() in ('http', 'https')}
        except Exception as e:
            logger.debug("获取系统代理失败: {}", e)
            return {}

    def _detect_vpn(self) -> bool:
        """检测是否在使用VPN"""
        vpn_indicators = [
            self.system_proxy,  # 系统代理
            os.getenv("HTTP_PROXY"),
            os.getenv("HTTPS_PROXY"),
            os.getenv("ALL_PROXY"),
            os.getenv("http_proxy"),
            os.getenv("https_proxy"),
            self.proxy_url  # 配置的代理
        ]

        return any(indicator for indicator in vpn_indicators if indicator)

    def get_proxies(self) -> Optional[Dict[str, str]]:
        """获取请求使用的代理配置"""
        proxies = {}

        # 优先使用手动配置的代理
        if self.proxy_url:
            parsed = urllib.parse.urlparse(self.proxy_url)
            if parsed.scheme:
                proxies['http'] = self.proxy_url
                proxies['https'] = self.proxy_url
                logger.info("使用配置的代理: {}", self.proxy_url)
                return proxies

        # 其次使用系统代理（如果启用）
        if self.use_system_proxy and self.system_proxy:
            proxies.update(self.system_proxy)
            logger.info("使用系统代理: {}", self.system_proxy)
            return proxies

        return None

    def get_ssl_config(self) -> Dict[str, Any]:
        """获取SSL配置"""
        if not self.verify_ssl:
            logger.warning("⚠️ SSL证书验证已禁用，连接可能不安全")
            return {"verify": False}

        # 检测到VPN环境时使用更宽松的SSL配置
        if self.has_vpn:
            logger.info("VPN环境下使用宽松SSL配置")
            return {
                "verify": True,
                # 可以在这里添加SSL上下文配置
            }

        return {"verify": True}

    def get_timeout_config(self) -> Tuple[int, int]:
        """获取超时配置（连接超时，读取超时）"""
        base_timeout = max(5, self.timeout)  # 最少5秒
        # VPN环境下增加超时时间
        if self.has_vpn:
            return (base_timeout, base_timeout * 2)
        return (base_timeout, base_timeout * 1.5)

    def get_session_config(self) -> Dict[str, Any]:
        """获取完整的session配置"""
        return {
            "timeout": self.get_timeout_config(),
            "proxies": self.get_proxies(),
            **self.get_ssl_config()
        }

    def create_session(self) -> "requests.Session":
        """创建预配置的requests.Session"""
        if not requests:
            raise ImportError("requests模块未安装")

        session = requests.Session()

        # 设置超时
        session.timeout = self.get_timeout_config()

        # 设置代理
        proxies = self.get_proxies()
        if proxies:
            session.proxies.update(proxies)

        # 设置SSL
        ssl_config = self.get_ssl_config()
        session.verify = ssl_config.get("verify", True)

        # 配置适配器
        adapter = HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10,
            pool_block=False
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        logger.debug("创建网络会话: 超时={}, 代理={}, SSL验证={}",
                    session.timeout, bool(proxies), session.verify)

        return session

    def test_connection(self, url: str = "https://open.feishu.cn") -> bool:
        """测试网络连接"""
        try:
            session = self.create_session()
            response = session.get(url, timeout=10)
            response.raise_for_status()
            logger.info("✅ 网络连接测试成功: {} (状态码: {})", url, response.status_code)
            return True
        except Exception as e:
            logger.error("❌ 网络连接测试失败: {} - {}", url, e)
            return False

    def get_network_info(self) -> Dict[str, Any]:
        """获取当前网络环境信息"""
        return {
            "has_vpn": self.has_vpn,
            "system_proxy": self.system_proxy,
            "configured_proxy": self.proxy_url,
            "verify_ssl": self.verify_ssl,
            "timeout": self.timeout,
            "use_system_proxy": self.use_system_proxy
        }


# 全局网络配置实例
network_config = NetworkConfig()