from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.views import serve
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import Client, RequestFactory


def test_favicon_route_redirects_to_brand_icon() -> None:
    response = Client().get("/favicon.ico")

    assert response.status_code == 302
    assert response["Location"] == static("img/brand/agomtradepro.ico")
    assert response["Content-Type"] == "text/html; charset=utf-8"


def test_favicon_static_response_is_a_public_icon() -> None:
    request = RequestFactory().get("/static/img/brand/agomtradepro.ico")
    response = serve(request, "img/brand/agomtradepro.ico", insecure=True)
    try:
        assert response.status_code == 200
        assert response["Content-Type"] in {"image/x-icon", "image/vnd.microsoft.icon"}
    finally:
        response.close()


@pytest.mark.parametrize("template_name", ["base.html", "terminal/tui_workbench.html"])
def test_page_shell_declares_the_brand_favicon(template_name: str) -> None:
    html = render_to_string(template_name, {"user": AnonymousUser()})
    assert (
        f'<link rel="icon" type="image/x-icon" ' f'href="{static("img/brand/agomtradepro.ico")}">'
    ) in html


def test_favicon_asset_contains_common_browser_sizes() -> None:
    path = finders.find("img/brand/agomtradepro.ico")
    assert isinstance(path, str)
    content = Path(path).read_bytes()

    assert content[:4] == b"\x00\x00\x01\x00"
    count = int.from_bytes(content[4:6], "little")
    sizes = {
        (content[6 + index * 16] or 256, content[7 + index * 16] or 256) for index in range(count)
    }
    assert {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)} <= sizes
