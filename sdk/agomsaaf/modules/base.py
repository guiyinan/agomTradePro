"""
AgomSAAF SDK 模块基类

所有业务模块的基类，提供统一的请求封装。
"""

from abc import ABC
from typing import Any, Optional

from agomsaaf.client import AgomSAAFClient


class BaseModule(ABC):
    """
    所有模块的基类

    提供统一的 HTTP 请求封装，子类只需要定义 API 前缀和业务方法。
    """

    def __init__(self, client: "AgomSAAFClient", prefix: str) -> None:
        """
        初始化模块

        Args:
            client: AgomSAAF 客户端实例
            prefix: API 路径前缀（如 "/api/regime"）
        """
        self._client = client
        self._prefix = prefix.rstrip("/")

    def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict:
        """
        发送 GET 请求

        Args:
            endpoint: 端点路径（相对于模块前缀）
            params: URL 查询参数

        Returns:
            响应 JSON 数据
        """
        url = f"{self._prefix}/{endpoint.lstrip('/')}"
        return self._client.get(url, params=params)

    def _post(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 POST 请求

        Args:
            endpoint: 端点路径（相对于模块前缀）
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        url = f"{self._prefix}/{endpoint.lstrip('/')}"
        return self._client.post(url, data=data, json=json)

    def _put(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 PUT 请求

        Args:
            endpoint: 端点路径（相对于模块前缀）
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        url = f"{self._prefix}/{endpoint.lstrip('/')}"
        return self._client.put(url, data=data, json=json)

    def _patch(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 PATCH 请求

        Args:
            endpoint: 端点路径（相对于模块前缀）
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        url = f"{self._prefix}/{endpoint.lstrip('/')}"
        return self._client.patch(url, data=data, json=json)

    def _delete(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict:
        """
        发送 DELETE 请求

        Args:
            endpoint: 端点路径（相对于模块前缀）
            params: URL 查询参数

        Returns:
            响应 JSON 数据
        """
        url = f"{self._prefix}/{endpoint.lstrip('/')}"
        return self._client.delete(url, params=params)
