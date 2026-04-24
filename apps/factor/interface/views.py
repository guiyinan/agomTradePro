"""DRF viewsets and page views for the factor module."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.factor.application import interface_services as factor_interface_services
from apps.factor.interface.serializers import (
    FactorDefinitionSerializer,
    FactorPortfolioConfigSerializer,
    FactorScoreRequestSerializer,
)


class FactorDefinitionViewSet(viewsets.GenericViewSet):
    """ViewSet for factor definition API endpoints."""

    serializer_class = FactorDefinitionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["category", "is_active"]
    search_fields = ["code", "name", "description"]
    ordering_fields = ["category", "code"]
    ordering = ["category", "code"]

    def list(self, request):
        """List factor definitions."""

        factors = factor_interface_services.list_factor_definitions(filters=request.query_params)
        page = self.paginate_queryset(factors)
        serializer = self.get_serializer(page if page is not None else factors, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve one factor definition."""

        factor = factor_interface_services.get_factor_definition(factor_id=int(pk))
        if factor is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(factor).data)

    def create(self, request):
        """Create one factor definition."""

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        factor = factor_interface_services.create_factor_definition(data=serializer.validated_data)
        return Response(
            self.get_serializer(factor).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
        """Update one factor definition."""

        return self._update(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        """Partially update one factor definition."""

        return self._update(request, pk, partial=True)

    def _update(self, request, pk, *, partial: bool):
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        factor = factor_interface_services.update_factor_definition(
            factor_id=int(pk),
            data=serializer.validated_data,
        )
        if factor is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(factor).data)

    def destroy(self, request, pk=None):
        """Delete one factor definition."""

        deleted = factor_interface_services.delete_factor_definition(factor_id=int(pk))
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def all_active(self, request):
        """Get active factor definition payloads."""

        return Response(factor_interface_services.get_active_factor_definition_payloads())

    @action(detail=True, methods=["post"], url_path="toggle-active")
    def toggle_active(self, request, pk=None):
        """Toggle one factor definition activation state."""

        factor = factor_interface_services.toggle_factor_definition_active(
            factor_id=int(pk),
        )
        if factor is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "success": True,
                "id": factor.id,
                "is_active": factor.is_active,
                "message": f'因子已{"启用" if factor.is_active else "禁用"}',
            }
        )


class FactorPortfolioConfigViewSet(viewsets.GenericViewSet):
    """ViewSet for factor portfolio configuration API endpoints."""

    serializer_class = FactorPortfolioConfigSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_active", "universe", "rebalance_frequency"]
    search_fields = ["name", "description"]
    ordering = ["-is_active", "-created_at"]

    def list(self, request):
        """List portfolio configurations."""

        configs = factor_interface_services.list_portfolio_configs(filters=request.query_params)
        page = self.paginate_queryset(configs)
        serializer = self.get_serializer(page if page is not None else configs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve one portfolio configuration."""

        config = factor_interface_services.get_portfolio_config(config_id=int(pk))
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(config).data)

    def create(self, request):
        """Create one portfolio configuration."""

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = factor_interface_services.create_portfolio_config(data=serializer.validated_data)
        return Response(
            self.get_serializer(config).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
        """Update one portfolio configuration."""

        return self._update(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        """Partially update one portfolio configuration."""

        return self._update(request, pk, partial=True)

    def _update(self, request, pk, *, partial: bool):
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        config = factor_interface_services.update_portfolio_config(
            config_id=int(pk),
            data=serializer.validated_data,
        )
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(config).data)

    def destroy(self, request, pk=None):
        """Delete one portfolio configuration."""

        deleted = factor_interface_services.delete_portfolio_config(config_id=int(pk))
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate one portfolio configuration."""

        config = factor_interface_services.set_portfolio_config_active(
            config_id=int(pk),
            is_active=True,
        )
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"status": "activated"})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate one portfolio configuration."""

        config = factor_interface_services.set_portfolio_config_active(
            config_id=int(pk),
            is_active=False,
        )
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"status": "deactivated"})

    @action(detail=True, methods=["post"])
    def generate_portfolio(self, request, pk=None):
        """Generate a portfolio for one configuration."""

        config = factor_interface_services.get_portfolio_config(config_id=int(pk))
        if config is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            portfolio = factor_interface_services.create_factor_portfolio(
                config_name=config.name,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if portfolio:
            return Response(portfolio)
        return Response(
            {"error": f"Portfolio config not found or generation failed: {config.name}"},
            status=status.HTTP_404_NOT_FOUND,
        )


class FactorScoreViewSet(viewsets.ViewSet):
    """ViewSet for factor score calculations."""

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def calculate_scores(self, request):
        """Calculate factor scores."""

        serializer = FactorScoreRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scores = factor_interface_services.calculate_factor_scores(
            universe=serializer.validated_data.get("universe", []),
            factor_weights=serializer.validated_data.get("factor_weights", {}),
            trade_date_value=serializer.validated_data.get("trade_date"),
            top_n=serializer.validated_data.get("top_n", 50),
        )
        return Response(
            {
                "trade_date": serializer.validated_data.get("trade_date"),
                "total_scores": len(scores),
                "scores": scores,
            }
        )

    @action(detail=False, methods=["post"])
    def explain_stock(self, request):
        """Explain one stock factor score."""

        stock_code = request.data.get("stock_code")
        factor_weights = request.data.get("factor_weights")

        if not stock_code or not factor_weights:
            return Response(
                {"error": "stock_code and factor_weights are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        explanation = factor_interface_services.explain_stock_score(
            stock_code=stock_code,
            factor_weights=factor_weights,
        )
        if explanation:
            return Response(explanation)
        return Response(
            {"error": "Failed to explain stock score"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class FactorActionViewSet(viewsets.ViewSet):
    """ViewSet for non-model factor actions."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Get available factor actions."""

        return Response(
            {
                "actions": {
                    "top_stocks": "POST /api/factor/top-stocks/ - Get top stocks by factors",
                    "create_portfolio": "POST /api/factor/create-portfolio/ - Create factor portfolio",
                    "explain_stock": "POST /api/factor/explain-stock/ - Explain stock factor score",
                }
            }
        )

    @action(detail=False, methods=["post"], url_path="top-stocks")
    def get_top_stocks(self, request):
        """Get top stocks by factor preferences."""

        factor_preferences = request.data.get("factor_preferences", {})
        top_n = request.data.get("top_n", 30)
        stocks = factor_interface_services.get_top_stocks(
            factor_preferences=factor_preferences,
            top_n=top_n,
        )
        return Response({"total_stocks": len(stocks), "stocks": stocks})

    @action(detail=False, methods=["post"], url_path="create-portfolio")
    def create_portfolio_action(self, request):
        """Create a factor portfolio from a config name."""

        config_name = request.data.get("config_name")
        trade_date_value = request.data.get("trade_date")

        if not config_name:
            return Response(
                {"error": "config_name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            portfolio = factor_interface_services.create_factor_portfolio(
                config_name=config_name,
                trade_date_value=trade_date_value,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if portfolio:
            return Response(portfolio)
        return Response(
            {"error": f"Portfolio config not found or generation failed: {config_name}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    @action(detail=False, methods=["post"], url_path="explain-stock")
    def explain_stock_action(self, request):
        """Explain one stock factor score breakdown."""

        stock_code = request.data.get("stock_code")
        factor_weights = request.data.get("factor_weights")

        if not stock_code or not factor_weights:
            return Response(
                {"error": "stock_code and factor_weights are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        explanation = factor_interface_services.explain_stock_score(
            stock_code=stock_code,
            factor_weights=factor_weights,
        )
        if explanation:
            return Response(explanation)
        return Response(
            {"error": "Failed to explain stock score"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @action(detail=False, methods=["get"], url_path="all-configs")
    def get_all_configs(self, request):
        """Get all portfolio configuration payloads."""

        return Response(factor_interface_services.get_all_portfolio_config_payloads())

    @action(detail=False, methods=["get"], url_path="all-factors")
    def get_all_factors(self, request):
        """Get all active factor definition payloads."""

        return Response(factor_interface_services.get_active_factor_definition_payloads())


@login_required
def factor_home_redirect(request):
    """Redirect root /factor/ to the manage page."""

    return redirect("factor:manage")


@login_required
def factor_manage_view(request):
    """Render the factor management page."""

    return render(
        request,
        "factor/manage.html",
        factor_interface_services.build_factor_manage_context(request.GET),
    )


@login_required
def portfolio_list_view(request):
    """Render the portfolio configuration page."""

    return render(
        request,
        "factor/portfolios.html",
        factor_interface_services.build_portfolio_list_context(request.GET),
    )


@login_required
def factor_calculate_view(request):
    """Render the factor calculation page."""

    return render(
        request,
        "factor/calculate.html",
        factor_interface_services.build_factor_calculation_context(request.GET),
    )


@require_http_methods(["POST"])
@login_required
def create_portfolio_config_view(request):
    """Create one portfolio configuration from the HTML form."""

    try:
        outcome = factor_interface_services.create_portfolio_config_from_form(request.POST)
        return JsonResponse(outcome, status=200 if outcome["success"] else 400)
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@require_http_methods(["POST", "DELETE"])
@login_required
def portfolio_config_action_view(request, config_id):
    """Perform actions on one portfolio configuration."""

    if request.method == "DELETE":
        outcome = factor_interface_services.delete_portfolio_config_with_message(
            config_id=config_id,
        )
        status_code = outcome.pop("status")
        return JsonResponse(outcome, status=status_code)

    outcome = factor_interface_services.handle_portfolio_config_action(
        config_id=config_id,
        action_type=request.POST.get("action"),
    )
    if outcome.get("success"):
        return JsonResponse(outcome)
    status_code = 500 if outcome.get("error") == "生成组合失败" else 400
    return JsonResponse(outcome, status=status_code)


@require_http_methods(["POST"])
@login_required
def calculate_scores_view(request):
    """Calculate factor scores for one stored configuration."""

    try:
        outcome = factor_interface_services.calculate_scores_for_config(post_data=request.POST)
        status_code = outcome.pop("status")
        return JsonResponse(outcome, status=status_code)
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


@require_http_methods(["GET"])
@login_required
def explain_stock_view(request, stock_code):
    """Get factor score explanation for one stock."""

    config_id = request.GET.get("config_id")
    if not config_id:
        return JsonResponse({"success": False, "error": "缺少 config_id 参数"}, status=400)

    try:
        outcome = factor_interface_services.explain_stock_for_config(
            stock_code=stock_code,
            config_id=int(config_id),
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    status_code = outcome.pop("status")
    return JsonResponse(outcome, status=status_code)
