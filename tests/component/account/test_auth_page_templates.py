import pytest


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "expected_title"),
    [
        ("/account/login/", "AgomTradePro 登录"),
        ("/account/register/", "注册 AgomTradePro"),
    ],
)
def test_auth_pages_use_lightweight_shell(client, path: str, expected_title: str):
    response = client.get(path)

    assert response.status_code == 200
    assert expected_title.encode("utf-8") in response.content
    assert b"floating-widget.css" not in response.content
    assert b'hx-ext="sse,remove-me,morph-swap"' not in response.content
    assert b'class="top-nav"' not in response.content
