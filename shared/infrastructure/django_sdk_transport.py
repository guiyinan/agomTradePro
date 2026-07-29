"""Django in-process transport for repository-local SDK execution."""

from __future__ import annotations

import json as json_module
import mimetypes
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, HttpResponseBase
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from shared.infrastructure.async_runtime import run_sync_compatible


class DjangoSdkResponse:
    """Adapt a Django response to the response subset consumed by the SDK."""

    def __init__(self, response: HttpResponseBase) -> None:
        if not isinstance(response, HttpResponse):
            raise ValueError("Streaming SDK responses are not supported")
        self._response = response
        self.status_code = response.status_code

    @property
    def text(self) -> str:
        """Return decoded response content for SDK error reporting."""

        return self._response.content.decode(
            getattr(self._response, "charset", None) or "utf-8",
            errors="replace",
        )

    def json(self) -> Any:
        """Decode the Django response as JSON."""

        return json_module.loads(self.text)


class DjangoSdkTransport:
    """Route SDK requests through Django's URL stack without a network socket."""

    def __init__(self, *, actor: dict[str, Any] | None = None) -> None:
        raw_actor = actor or {}
        user_id = raw_actor.get("user_id")
        if user_id is not None and (
            isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
        ):
            raise ValueError("Local SDK actor user_id must be a positive integer")
        self._actor: dict[str, int] = {"user_id": user_id} if user_id is not None else {}

    def _build_client(self) -> Client:
        client = Client()
        user_id = self._actor.get("user_id")
        if user_id is not None:
            user = get_user_model()._default_manager.filter(pk=user_id).first()
            if user is None:
                raise ValueError("Local SDK actor does not exist")
            client.force_login(user)
        return client

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        json: dict[str, Any] | None,
        files: dict[str, Any] | None,
        timeout: int,
    ) -> DjangoSdkResponse:
        """Execute one SDK request against the local Django application."""

        return run_sync_compatible(
            lambda: self._request_sync(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                json=json,
                files=files,
                timeout=timeout,
            )
        )

    def _request_sync(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        json: dict[str, Any] | None,
        files: dict[str, Any] | None,
        timeout: int,
    ) -> DjangoSdkResponse:
        """Execute the Django request from a synchronous execution context."""

        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ValueError("timeout must be an integer between 1 and 3600")
        normalized_method = method.strip().upper()
        if normalized_method not in {"DELETE", "GET", "PATCH", "POST", "PUT"}:
            raise ValueError("Unsupported local SDK HTTP method")
        if len(headers) > 100 or any(
            not key or len(key) > 256 or len(value) > 16_384 or "\x00" in key or "\x00" in value
            for key, value in headers.items()
        ):
            raise ValueError("Local SDK headers exceed bounded text limits")

        parsed = urlsplit(url)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Local SDK URL has an invalid port") from exc
        if (
            parsed.scheme not in {"", "http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.hostname not in {None, "localhost", "testserver", "127.0.0.1", "::1"}
        ):
            raise ValueError("Local SDK URL must target an approved loopback host")
        if len(parsed.path) > 4096:
            raise ValueError("Local SDK request path is too long")
        query_items = list(parse_qsl(parsed.query, keep_blank_values=True))
        if params:
            for key, value in params.items():
                if isinstance(value, list | tuple):
                    query_items.extend((str(key), self._query_value(item)) for item in value)
                elif value is not None:
                    query_items.append((str(key), self._query_value(value)))
        if len(query_items) > 1000:
            raise ValueError("Local SDK query exceeds the 1000 item limit")
        request_path = urlunsplit(
            ("", "", parsed.path or "/", urlencode(query_items, doseq=True), "")
        )
        if len(request_path) > 16_384:
            raise ValueError("Local SDK request URL exceeds the 16384 character limit")

        request_headers = dict(headers)
        content_type = headers.get("Content-Type", "application/json")
        request_body: str | bytes = b""
        if files:
            request_body = self._encode_multipart(data=data, files=files)
            content_type = MULTIPART_CONTENT
            request_headers = {
                key: value
                for key, value in request_headers.items()
                if key.lower() != "content-type"
            }
        elif json is not None:
            try:
                request_body = json_module.dumps(json, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError("Local SDK JSON body must contain finite JSON values") from exc
            content_type = "application/json"
        elif data is not None:
            request_body = urlencode(data, doseq=True)
            content_type = "application/x-www-form-urlencoded"

        max_request_bytes = self._positive_setting(
            "DATA_UPLOAD_MAX_MEMORY_SIZE",
            default=2_621_440,
        )
        request_size = (
            len(request_body)
            if isinstance(request_body, bytes)
            else len(request_body.encode("utf-8"))
        )
        if request_size > max_request_bytes:
            raise ValueError("Local SDK request body exceeds the configured size limit")

        response = self._build_client().generic(
            normalized_method,
            request_path,
            data=request_body,
            content_type=content_type,
            secure=parsed.scheme == "https",
            headers=request_headers,
        )
        return DjangoSdkResponse(response)

    @staticmethod
    def _positive_setting(name: str, *, default: int) -> int:
        """Return one positive integer Django upload limit."""

        value = getattr(settings, name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return default
        return value

    @staticmethod
    def _query_value(value: object) -> str:
        """Return one finite, bounded query scalar."""

        if not isinstance(value, str | int | float | bool):
            raise ValueError("Local SDK query values must be scalar")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("Local SDK query values must be finite")
        if isinstance(value, str) and (len(value) > 16_384 or "\x00" in value):
            raise ValueError("Local SDK query value exceeds bounded text limits")
        return str(value)

    @staticmethod
    def _encode_multipart(
        *,
        data: dict[str, Any] | None,
        files: dict[str, Any],
    ) -> bytes:
        """Encode bounded requests-style file tuples for Django's multipart parser."""

        max_files = DjangoSdkTransport._positive_setting(
            "DATA_UPLOAD_MAX_NUMBER_FILES", default=100
        )
        max_file_bytes = DjangoSdkTransport._positive_setting(
            "FILE_UPLOAD_MAX_MEMORY_SIZE", default=2_621_440
        )
        max_request_bytes = DjangoSdkTransport._positive_setting(
            "DATA_UPLOAD_MAX_MEMORY_SIZE", default=max_file_bytes
        )
        if len(files) > max_files:
            raise ValueError("Multipart file count exceeds local limit")

        multipart_data: dict[str, Any] = dict(data or {})
        for field_name, file_spec in files.items():
            if not isinstance(file_spec, tuple) or len(file_spec) not in {2, 3}:
                raise ValueError(
                    "Multipart files must use (filename, content) or "
                    "(filename, content, content_type) tuples"
                )
            raw_filename, raw_content = file_spec[:2]
            filename = Path(str(raw_filename)).name.strip()
            if not filename or "\x00" in filename:
                raise ValueError("Invalid multipart filename")

            if hasattr(raw_content, "read"):
                try:
                    content = raw_content.read(max_file_bytes + 1)
                except TypeError as exc:
                    raise ValueError("Multipart stream must support bounded reads") from exc
            else:
                content = raw_content
            if isinstance(content, str):
                content = content.encode("utf-8")
            elif isinstance(content, bytearray | memoryview):
                content = bytes(content)
            if not isinstance(content, bytes):
                raise ValueError("Unsupported multipart content")
            if len(content) > max_file_bytes:
                raise ValueError("Multipart file exceeds local multipart limit")

            explicit_content_type = file_spec[2] if len(file_spec) == 3 else None
            content_type = str(
                explicit_content_type
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
            multipart_data[str(field_name)] = SimpleUploadedFile(
                name=filename,
                content=content,
                content_type=content_type,
            )

        encoded = encode_multipart(BOUNDARY, multipart_data)
        if len(encoded) > max_request_bytes:
            raise ValueError("Multipart request exceeds local multipart limit")
        return encoded
