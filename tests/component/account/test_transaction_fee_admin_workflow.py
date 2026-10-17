"""Real Admin workflow checks for transaction fee availability and correction."""

from decimal import Decimal

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.account.infrastructure.models import PortfolioModel, TransactionModel


class TransactionFeeAdminWorkflowTests(TestCase):
    """Exercise the registered Admin through authenticated HTTP requests."""

    def setUp(self) -> None:
        self.owner = User.objects.create_superuser(
            username="fee_admin_owner",
            email="fee-admin-owner@example.com",
            password="Pass123!@#",
        )
        self.portfolio = PortfolioModel.objects.create(
            user=self.owner,
            name="Owned fee-test portfolio",
        )
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)

    @staticmethod
    def _csrf_token(client: Client) -> str:
        """Return the token cookie created by a real Admin GET request."""
        cookie = client.cookies.get("csrftoken")
        if cookie is None:
            raise AssertionError("Admin GET did not establish a CSRF cookie")
        return str(cookie.value)

    @staticmethod
    def _add_payload(portfolio_id: int) -> dict[str, str]:
        """Build only the eight fields exposed by the transaction add form."""
        return {
            "portfolio": str(portfolio_id),
            "position": "",
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": "5",
            "price": "10.25",
            "traded_at_0": "2026-10-17",
            "traded_at_1": "09:30:00",
            "notes": "Admin fee availability workflow",
        }

    def _create_transaction(
        self,
        *,
        portfolio: PortfolioModel,
        commission: Decimal = Decimal("0.00"),
        commission_known: bool | None = False,
        slippage: Decimal = Decimal("0.00"),
        slippage_known: bool | None = False,
        stamp_duty: Decimal = Decimal("0.00"),
        stamp_duty_known: bool | None = False,
        transfer_fee: Decimal = Decimal("0.00"),
        transfer_fee_known: bool | None = False,
        estimated_cost: Decimal | None = None,
        cost_variance: Decimal | None = None,
        cost_variance_pct: float | None = None,
    ) -> TransactionModel:
        """Seed a persisted transaction for display and correction requests."""
        return TransactionModel.objects.create(
            portfolio=portfolio,
            action="buy",
            asset_code="600000.SH",
            shares=5.0,
            price=Decimal("10.2500"),
            notional=Decimal("51.25"),
            commission=commission,
            commission_known=commission_known,
            slippage=slippage,
            slippage_known=slippage_known,
            stamp_duty=stamp_duty,
            stamp_duty_known=stamp_duty_known,
            transfer_fee=transfer_fee,
            transfer_fee_known=transfer_fee_known,
            estimated_cost=estimated_cost,
            cost_variance=cost_variance,
            cost_variance_pct=cost_variance_pct,
            traded_at=timezone.now(),
            notes="Admin fee workflow seed",
        )

    def test_add_uses_eight_field_form_application_and_one_admin_log(self) -> None:
        """A real CSRF-checked add creates one unknown-cost ledger row."""
        add_url = reverse("admin:account_transactionmodel_add")
        page = self.client.get(add_url)

        self.assertEqual(page.status_code, 200)
        self.assertIsNotNone(page.context)
        admin_form = page.context["adminform"].form
        self.assertEqual(
            tuple(admin_form.fields),
            (
                "portfolio",
                "position",
                "action",
                "asset_code",
                "shares",
                "price",
                "traded_at",
                "notes",
            ),
        )
        for fee_field in (
            "commission",
            "slippage",
            "stamp_duty",
            "transfer_fee",
            "commission_known",
            "slippage_known",
            "stamp_duty_known",
            "transfer_fee_known",
            "estimated_cost",
        ):
            self.assertNotIn(fee_field, admin_form.fields)

        response = self.client.post(
            add_url,
            self._add_payload(self.portfolio.pk),
            HTTP_X_CSRFTOKEN=self._csrf_token(self.client),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(TransactionModel.objects.filter(portfolio=self.portfolio).count(), 1)
        transaction = TransactionModel.objects.get(portfolio=self.portfolio)
        for field in ("commission", "slippage", "stamp_duty", "transfer_fee"):
            self.assertEqual(getattr(transaction, field), Decimal("0.00"))
            self.assertFalse(getattr(transaction, f"{field}_known"))
        self.assertEqual(
            LogEntry.objects.filter(
                user=self.owner,
                content_type__app_label="account",
                content_type__model="transactionmodel",
                object_id=str(transaction.pk),
                action_flag=ADDITION,
            ).count(),
            1,
        )

    def test_admin_add_rejects_a_post_without_csrf_token(self) -> None:
        """The real Admin middleware rejects a session-authenticated forged POST."""
        add_url = reverse("admin:account_transactionmodel_add")
        self.assertEqual(self.client.get(add_url).status_code, 200)

        response = self.client.post(add_url, self._add_payload(self.portfolio.pk))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(TransactionModel.objects.filter(portfolio=self.portfolio).count(), 0)
        self.assertEqual(
            LogEntry.objects.filter(
                user=self.owner,
                content_type__app_label="account",
                content_type__model="transactionmodel",
                action_flag=ADDITION,
            ).count(),
            0,
        )

    def test_add_rejects_fee_and_estimate_overpost_with_valid_widget_fields_and_csrf(
        self,
    ) -> None:
        """Fee fields stay rejected after accepting the real split datetime names."""
        add_url = reverse("admin:account_transactionmodel_add")
        page = self.client.get(add_url)

        self.assertEqual(page.status_code, 200)
        csrf_token = self._csrf_token(self.client)
        for forbidden_field in ("commission", "estimated_cost"):
            with self.subTest(field=forbidden_field):
                payload = self._add_payload(self.portfolio.pk)
                payload[forbidden_field] = "0.00"
                response = self.client.post(
                    add_url,
                    payload,
                    HTTP_X_CSRFTOKEN=csrf_token,
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    "提交包含交易创建表单不接受的字段",
                )
                self.assertEqual(
                    TransactionModel.objects.filter(portfolio=self.portfolio).count(),
                    0,
                )
                self.assertEqual(
                    LogEntry.objects.filter(
                        user=self.owner,
                        content_type__app_label="account",
                        content_type__model="transactionmodel",
                        action_flag=ADDITION,
                    ).count(),
                    0,
                )

    def test_list_and_detail_show_unknown_fees_without_zero_claims(self) -> None:
        """Legacy NULL availability and zero storage remain visibly unknown."""
        transaction = self._create_transaction(
            portfolio=self.portfolio,
            commission_known=None,
            slippage_known=None,
            stamp_duty_known=None,
            transfer_fee_known=None,
        )

        list_response = self.client.get(reverse("admin:account_transactionmodel_changelist"))
        detail_response = self.client.get(
            reverse(
                "admin:account_transactionmodel_change",
                args=[transaction.pk],
            )
        )

        for response in (list_response, detail_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "手续费 未知/未采集")
            self.assertContains(response, "滑点 未知/未采集")
            self.assertContains(response, "印花税 未知/未采集")
            self.assertContains(response, "过户费 未知/未采集")
            self.assertNotContains(response, "手续费 0.00")

    def test_partial_correction_preserves_blanks_and_recomputes_full_variance(self) -> None:
        """Blank components persist, explicit zero is known, and all fees are summed."""
        transaction = self._create_transaction(
            portfolio=self.portfolio,
            commission=Decimal("1.00"),
            commission_known=True,
            slippage=Decimal("0.00"),
            slippage_known=False,
            stamp_duty=Decimal("3.00"),
            stamp_duty_known=True,
            transfer_fee=Decimal("4.00"),
            transfer_fee_known=True,
            estimated_cost=Decimal("10.00"),
            cost_variance=Decimal("99.00"),
            cost_variance_pct=9.9,
        )
        correction_url = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[transaction.pk],
        )
        page = self.client.get(correction_url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "留空表示保留当前值")
        response = self.client.post(
            correction_url,
            {
                "commission": "",
                "slippage": "0",
                "stamp_duty": "",
                "transfer_fee": "",
            },
            HTTP_X_CSRFTOKEN=self._csrf_token(self.client),
        )

        self.assertEqual(response.status_code, 302)
        transaction.refresh_from_db()
        self.assertEqual(transaction.commission, Decimal("1.00"))
        self.assertEqual(transaction.slippage, Decimal("0.00"))
        self.assertEqual(transaction.stamp_duty, Decimal("3.00"))
        self.assertEqual(transaction.transfer_fee, Decimal("4.00"))
        self.assertTrue(transaction.commission_known)
        self.assertTrue(transaction.slippage_known)
        self.assertTrue(transaction.stamp_duty_known)
        self.assertTrue(transaction.transfer_fee_known)
        self.assertEqual(transaction.cost_variance, Decimal("-2.00"))
        self.assertIsNotNone(transaction.cost_variance_pct)
        self.assertAlmostEqual(transaction.cost_variance_pct, -0.2)
        self.assertEqual(
            LogEntry.objects.filter(
                user=self.owner,
                content_type__app_label="account",
                content_type__model="transactionmodel",
                object_id=str(transaction.pk),
                action_flag=CHANGE,
            ).count(),
            1,
        )

    def test_foreign_owner_add_and_correction_are_denied_and_change_permission_is_required(
        self,
    ) -> None:
        """Owner checks and Admin model permission protect both write paths."""
        foreign_owner = User.objects.create_user(
            username="fee_foreign_owner",
            email="fee-foreign-owner@example.com",
            password="Pass123!@#",
        )
        foreign_portfolio = PortfolioModel.objects.create(
            user=foreign_owner,
            name="Foreign fee-test portfolio",
        )
        add_url = reverse("admin:account_transactionmodel_add")
        self.assertEqual(self.client.get(add_url).status_code, 200)
        add_response = self.client.post(
            add_url,
            self._add_payload(foreign_portfolio.pk),
            HTTP_X_CSRFTOKEN=self._csrf_token(self.client),
        )

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(TransactionModel.objects.count(), 0)

        foreign_transaction = self._create_transaction(portfolio=foreign_portfolio)
        correction_url = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[foreign_transaction.pk],
        )
        self.assertEqual(self.client.get(correction_url).status_code, 200)
        correction_response = self.client.post(
            correction_url,
            {
                "commission": "9.00",
                "slippage": "",
                "stamp_duty": "",
                "transfer_fee": "",
            },
            HTTP_X_CSRFTOKEN=self._csrf_token(self.client),
        )

        self.assertEqual(correction_response.status_code, 403)
        foreign_transaction.refresh_from_db()
        self.assertEqual(foreign_transaction.commission, Decimal("0.00"))
        self.assertFalse(foreign_transaction.commission_known)
        self.assertEqual(TransactionModel.objects.count(), 1)

        staff_without_change = User.objects.create_user(
            username="fee_staff_without_change",
            password="Pass123!@#",
            is_staff=True,
        )
        no_change_client = Client(enforce_csrf_checks=True)
        no_change_client.force_login(staff_without_change)
        denied_response = no_change_client.get(correction_url)
        self.assertEqual(denied_response.status_code, 403)
