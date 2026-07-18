"""Django in-process transport for repository-local SDK execution."""

from __future__ import annotations

import json as json_module
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponseBase
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from shared.infrastructure.async_runtime import run_sync_compatible


class DjangoSdkResponse:
    """Adapt a Django response to the response subset consumed by the SDK."""

    def __init__(self, response: HttpResponseBase) -> None:
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
        self._actor = dict(actor or {})

    def _build_client(self) -> Client:
        client = Client()
        user_id = self._actor.get("user_id")
        if user_id is not None:
            user = get_user_model()._default_manager.filter(pk=user_id).first()
            if user is None:
                raise ValueError(f"Local SDK actor does not exist: user_id={user_id}")
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

        del timeout

        parsed = urlsplit(url)
        query_items = list(parse_qsl(parsed.query, keep_blank_values=True))
        if params:
            for key, value in params.items():
                if isinstance(value, (list, tuple)):
                    query_items.extend((str(key), item) for item in value)
                elif value is not None:
                    query_items.append((str(key), value))
        request_path = urlunsplit(
            ("", "", parsed.path or "/", urlencode(query_items, doseq=True), "")
        )

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
            request_body = json_module.dumps(json, ensure_ascii=False)
            content_type = "application/json"
        elif data is not None:
            request_body = urlencode(data, doseq=True)
            content_type = "application/x-www-form-urlencoded"

        response = self._build_client().generic(
            method.upper(),
            request_path,
            data=request_body,
            content_type=content_type,
            secure=parsed.scheme == "https",
            headers=request_headers,
        )
        return DjangoSdkResponse(response)

    @staticmethod
    def _encode_multipart(
        *,
        data: dict[str, Any] | None,
        files: dict[str, Any],
    ) -> bytes:
        """Encode bounded requests-style file tuples for Django's multipart parser."""

        max_files = int(getattr(settings, "DATA_UPLOAD_MAX_NUMBER_FILES", 100) or 100)
        max_file_bytes = int(
            getattr(settings, "FILE_UPLOAD_MAX_MEMORY_SIZE", 2_621_440) or 2_621_440
        )
        max_request_bytes = int(
            getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", max_file_bytes) or max_file_bytes
        )
        if len(files) > max_files:
            raise ValueError(
                f"Multipart file count exceeds local limit: {len(files)} > {max_files}"
            )

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
                raise ValueError(f"Invalid multipart filename for field: {field_name}")

            if hasattr(raw_content, "read"):
                try:
                    content = raw_content.read(max_file_bytes + 1)
                except TypeError as exc:
                    raise ValueError(
                        f"Multipart stream must support bounded reads: {field_name}"
                    ) from exc
            else:
                content = raw_content
            if isinstance(content, str):
                content = content.encode("utf-8")
            elif isinstance(content, (bytearray, memoryview)):
                content = bytes(content)
            if not isinstance(content, bytes):
                raise ValueError(f"Unsupported multipart content for field: {field_name}")
            if len(content) > max_file_bytes:
                raise ValueError(
                    f"Multipart file exceeds local multipart limit: "
                    f"{filename} ({len(content)} > {max_file_bytes} bytes)"
                )

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
            raise ValueError(
                f"Multipart request exceeds local multipart limit: "
                f"{len(encoded)} > {max_request_bytes} bytes"
            )
        return encoded
