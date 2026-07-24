import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_alpha_admin_train_page_requires_superuser():
    staff_user = get_user_model().objects.create_user(
        username="alpha_staff_only",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )

    client = Client()
    client.force_login(staff_user)
    response = client.get(reverse("admin:alpha_qlibmodelregistry_train"))

    assert response.status_code == 302
    assert response["Location"].endswith("/admin/")
