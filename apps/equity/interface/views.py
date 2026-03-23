"""
个股分析模块 Interface 层视图

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
- 包含 API 视图（DRF）和页面视图（Django Views）
"""

from django.shortcuts import render
from django.db import OperationalError, ProgrammingError
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.equity.application.use_cases import (
    ScreenStocksUseCase,
    AnalyzeValuationUseCase,
    CalculateDCFUseCase,
    AnalyzeRegimeCorrelationUseCase,
    ComprehensiveValuationUseCase,
    ScreenStocksRequest,
    AnalyzeValuationRequest,
    CalculateDCFRequest,
    AnalyzeRegimeCorrelationRequest,
    ComprehensiveValuationRequest,
)
from apps.equity.application.use_cases_valuation_repair import (
    GetValuationRepairStatusUseCase,
    GetValuationRepairStatusRequest,
    GetValuationPercentileHistoryUseCase,
    GetValuationPercentileHistoryRequest,
    ScanValuationRepairsUseCase,
    ScanValuationRepairsRequest,
    ListValuationRepairsUseCase,
    ListValuationRepairsRequest,
)
from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationUseCase,
    SyncEquityValuationRequest,
    BackfillEquityValuationUseCase,
    BackfillEquityValuationRequest,
    ValidateEquityValuationQualityUseCase,
    ValidateEquityValuationQualityRequest,
    GetEquityValuationFreshnessUseCase,
    GetLatestEquityValuationQualityUseCase,
)
from apps.equity.infrastructure.repositories import (
    DjangoStockRepository,
    DjangoValuationRepairRepository,
    DjangoValuationDataQualityRepository,
)
from .serializers import (
    ScreenStocksRequestSerializer,
    ScreenStocksResponseSerializer,
    AnalyzeValuationRequestSerializer,
    AnalyzeValuationResponseSerializer,
    CalculateDCFRequestSerializer,
    CalculateDCFResponseSerializer,
    AnalyzeRegimeCorrelationRequestSerializer,
    AnalyzeRegimeCorrelationResponseSerializer,
    ComprehensiveValuationRequestSerializer,
    ComprehensiveValuationResponseSerializer,
    ValuationRepairStatusResponseSerializer,
    ValuationRepairHistoryResponseSerializer,
    ScanValuationRepairsRequestSerializer,
    ScanValuationRepairsResponseSerializer,
    ListValuationRepairsRequestSerializer,
    ListValuationRepairsResponseSerializer,
    SyncValuationDataRequestSerializer,
    SyncValuationDataResponseSerializer,
    ValidateValuationDataRequestSerializer,
    ValuationQualitySnapshotResponseSerializer,
    ValuationFreshnessResponseSerializer,
)


# ============================================================================
# 页面视图（前端）
# ============================================================================

@require_http_methods(["GET"])
def screen_page(request):
    """
    个股筛选页面

    GET /equity/screen/
    """
    return render(request, 'equity/screen.html')


@require_http_methods(["GET"])
def detail_page(request, stock_code):
    """
    个股详情页面

    GET /equity/detail/<stock_code>/
    """
    context = {
        'stock_code': stock_code
    }
    return render(request, 'equity/detail.html', context)


@require_http_methods(["GET"])
def pool_page(request):
    """
    股票池管理页面

    GET /equity/pool/
    """
    return render(request, 'equity/pool.html')


@require_http_methods(["GET"])
def valuation_repair_page(request):
    """
    估值修复跟踪页面

    GET /equity/valuation-repair/
    """
    from apps.equity.application.config import get_valuation_repair_config_summary

    return render(request, 'equity/valuation_repair.html', {
        'valuation_repair_config_summary': get_valuation_repair_config_summary(use_cache=False),
        'can_manage_valuation_repair_config': bool(
            getattr(request.user, "is_authenticated", False)
            and (getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))
        ),
    })


@require_http_methods(["GET"])
def valuation_repair_config_page(request):
    """
    估值修复配置管理页面

    GET /equity/valuation-repair/config/
    """
    return render(request, 'equity/config.html')


class EquityViewSet(viewsets.ViewSet):
    """个股分析 API"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock_repo = DjangoStockRepository()
        self.repair_repo = DjangoValuationRepairRepository()
        self.quality_repo = DjangoValuationDataQualityRepository()
        # 注入 regime_repo（使用适配器）
        from apps.equity.infrastructure.adapters import RegimeRepositoryAdapter
        self.regime_repo = RegimeRepositoryAdapter()
        # 注入 stock_pool_adapter（用于估值修复扫描）
        from apps.equity.infrastructure.adapters import StockPoolRepositoryAdapter
        self.pool_adapter = StockPoolRepositoryAdapter()

    @extend_schema(
        summary="筛选个股",
        description="基于 Regime 和财务指标筛选个股",
        request=ScreenStocksRequestSerializer,
        responses={200: ScreenStocksResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='screen')
    def screen_stocks(self, request):
        """
        POST /api/equity/screen/

        筛选个股

        Request Body:
        {
            "regime": "Recovery",  // 可选，不填则自动获取最新
            "custom_rule": {  // 可选，自定义规则
                "min_roe": 20.0,
                "max_pe": 25.0
            },
            "max_count": 20
        }

        Response:
        {
            "success": true,
            "regime": "Recovery",
            "stock_codes": ["600030.SH", "000001.SZ"],
            "screening_criteria": {
                "min_roe": 15.0,
                "max_pe": 30.0
            }
        }
        """
        # 1. 验证请求
        serializer = ScreenStocksRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = ScreenStocksRequest(
            regime=data.get('regime'),
            custom_rule=data.get('custom_rule'),
            max_count=data.get('max_count', 30)
        )

        # 3. 执行用例
        use_case = ScreenStocksUseCase(
            stock_repository=self.stock_repo,
            regime_repository=self.regime_repo
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ScreenStocksResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="估值分析（个股详情）",
        description="获取个股的完整估值分析数据，包括基本信息、估值指标、财务数据等",
        request=AnalyzeValuationRequestSerializer,
        responses={200: AnalyzeValuationResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation/(?P<stock_code>[^/]+)')
    def analyze_valuation(self, request, stock_code):
        """
        GET /api/equity/valuation/{stock_code}/

        估值分析（个股详情页完整数据）

        Response:
        {
            "success": true,
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "sector": "银行",
            "market": "SZ",
            "list_date": "1991-04-03",
            "current_pe": 5.2,
            "pe_percentile": 0.15,
            "current_pb": 0.55,
            "pb_percentile": 0.20,
            "is_undervalued": true,
            "latest_valuation": {
                "pe": 5.2,
                "pb": 0.55,
                "ps": 1.2,
                "pe_percentile": 0.15,
                "pb_percentile": 0.20,
                "total_mv": 250000000000,
                "circ_mv": 250000000000,
                "dividend_yield": 5.5,
                "price": 12.5,
                "trade_date": "2026-03-22"
            },
            "financial_data": {
                "roe": 10.5,
                "roa": 0.8,
                "revenue": 100000000000,
                "net_profit": 25000000000,
                "revenue_growth": 8.5,
                "net_profit_growth": 12.3,
                "debt_ratio": 95.0,
                "gross_margin": null,
                "report_date": "2025-12-31"
            }
        }
        """
        # 1. 验证请求
        serializer = AnalyzeValuationRequestSerializer(data={
            'stock_code': stock_code,
            'lookback_days': request.query_params.get('lookback_days', 252)
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeValuationRequest(
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 252)
        )

        # 3. 执行用例
        use_case = AnalyzeValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = AnalyzeValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="DCF 绝对估值",
        description="计算股票的内在价值",
        request=CalculateDCFRequestSerializer,
        responses={200: CalculateDCFResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='dcf')
    def calculate_dcf(self, request):
        """
        POST /api/equity/dcf/

        DCF 绝对估值

        Request Body:
        {
            "stock_code": "600030.SH",
            "growth_rate": 0.1,  // 可选，默认 0.1
            "discount_rate": 0.1,  // 可选，默认 0.1
            "terminal_growth": 0.03,  // 可选，默认 0.03
            "projection_years": 5  // 可选，默认 5
        }

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "intrinsic_value": 280000000000,
            "intrinsic_value_per_share": 28.5,
            "current_price": 23.5,
            "upside": 0.21  // 21% 上涨空间
        }
        """
        # 1. 验证请求
        serializer = CalculateDCFRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = CalculateDCFRequest(
            stock_code=data['stock_code'],
            growth_rate=data.get('growth_rate', 0.1),
            discount_rate=data.get('discount_rate', 0.1),
            terminal_growth=data.get('terminal_growth', 0.03),
            projection_years=data.get('projection_years', 5)
        )

        # 3. 执行用例
        use_case = CalculateDCFUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = CalculateDCFResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Regime 相关性分析",
        description="分析个股在不同宏观环境下的表现",
        request=AnalyzeRegimeCorrelationRequestSerializer,
        responses={200: AnalyzeRegimeCorrelationResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='regime-correlation/(?P<stock_code>[^/]+)')
    def analyze_regime_correlation(self, request, stock_code):
        """
        GET /api/equity/regime-correlation/{stock_code}/

        Regime 相关性分析

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "regime_performance": [
                {
                    "regime": "Recovery",
                    "avg_return": 0.0025,
                    "beta": 1.3,
                    "sample_days": 320
                },
                {
                    "regime": "Overheat",
                    "avg_return": 0.0018,
                    "beta": 1.1,
                    "sample_days": 280
                },
                {
                    "regime": "Stagflation",
                    "avg_return": -0.0012,
                    "beta": 0.9,
                    "sample_days": 310
                },
                {
                    "regime": "Deflation",
                    "avg_return": -0.0008,
                    "beta": 0.8,
                    "sample_days": 350
                }
            ],
            "best_regime": "Recovery",
            "worst_regime": "Stagflation"
        }
        """
        # 1. 验证请求
        serializer = AnalyzeRegimeCorrelationRequestSerializer(data={
            'stock_code': stock_code,
            'lookback_days': request.query_params.get('lookback_days', 1260)
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = AnalyzeRegimeCorrelationRequest(
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 1260)
        )

        # 3. 执行用例
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        use_case = AnalyzeRegimeCorrelationUseCase(
            stock_repository=self.stock_repo,
            regime_repository=DjangoRegimeRepository()
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 转换 regime_performance 为列表格式（用于序列化）
        if use_case_response.success:
            response_data = {
                'success': use_case_response.success,
                'stock_code': use_case_response.stock_code,
                'stock_name': use_case_response.stock_name,
                'regime_performance': [
                    {
                        'regime': rp.regime,
                        'avg_return': rp.avg_return,
                        'beta': rp.beta,
                        'sample_days': rp.sample_days
                    }
                    for rp in use_case_response.regime_performance.values()
                ],
                'best_regime': use_case_response.best_regime,
                'worst_regime': use_case_response.worst_regime
            }
        else:
            response_data = {
                'success': use_case_response.success,
                'stock_code': use_case_response.stock_code,
                'stock_name': '',
                'regime_performance': [],
                'best_regime': '',
                'worst_regime': '',
                'error': use_case_response.error
            }

        # 5. 返回响应
        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="综合估值分析",
        description="整合多种估值方法，提供综合的低估/高估判断",
        request=ComprehensiveValuationRequestSerializer,
        responses={200: ComprehensiveValuationResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='comprehensive-valuation')
    def comprehensive_valuation(self, request):
        """
        POST /api/equity/comprehensive-valuation/

        综合估值分析

        整合多种估值方法：
        1. PE/PB 百分位分析（权重 30%）
        2. 相对行业估值（权重 20%）
        3. PEG 估值（权重 20%）
        4. 质量评分（权重 15%）
        5. DCF 绝对估值（权重 15%）

        Request Body:
        {
            "stock_code": "600030.SH",
            "lookback_days": 252,  // 可选，默认 252
            "industry_avg_pe": 20.0,  // 可选，默认 20.0
            "industry_avg_pb": 2.0,  // 可选，默认 2.0
            "risk_free_rate": 0.03  // 可选，默认 0.03
        }

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "overall_score": 76.5,
            "overall_signal": "buy",
            "recommendation": "推荐买入。股票估值偏低，具有投资价值。",
            "confidence": 0.82,
            "scores": [
                {
                    "method": "PE/PB 百分位",
                    "score": 80,
                    "signal": "undervalued",
                    "details": {"pe_percentile": 0.25, "pb_percentile": 0.30}
                },
                {
                    "method": "相对行业",
                    "score": 70,
                    "signal": "undervalued",
                    "details": {"pe_ratio": 0.75, "pb_ratio": 0.80}
                },
                {
                    "method": "PEG",
                    "score": 85,
                    "signal": "undervalued",
                    "details": {"peg": 0.67}
                },
                {
                    "method": "质量评分",
                    "score": 65,
                    "signal": "fair",
                    "details": {"roe": 16.5, "revenue_growth": 18.0}
                }
            ]
        }
        """
        # 1. 验证请求
        serializer = ComprehensiveValuationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = ComprehensiveValuationRequest(
            stock_code=data['stock_code'],
            lookback_days=data.get('lookback_days', 252),
            industry_avg_pe=data.get('industry_avg_pe', 20.0),
            industry_avg_pb=data.get('industry_avg_pb', 2.0),
            risk_free_rate=data.get('risk_free_rate', 0.03)
        )

        # 3. 执行用例
        use_case = ComprehensiveValuationUseCase(stock_repository=self.stock_repo)
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        response_serializer = ComprehensiveValuationResponseSerializer(use_case_response)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='pool')
    def get_pool(self, request):
        """
        GET /equity/api/pool/

        获取当前股票池
        """
        from datetime import date
        from apps.equity.infrastructure.adapters import StockPoolRepositoryAdapter
        from apps.regime.application.current_regime import resolve_current_regime

        try:
            pool_adapter = StockPoolRepositoryAdapter()

            # 获取当前股票池
            stock_codes = pool_adapter.get_current_pool()

            # 获取股票池元数据
            pool_info = pool_adapter.get_latest_pool_info()

            # 获取当前 Regime
            latest_regime = resolve_current_regime()

            if not stock_codes:
                # 如果没有股票池，返回空结果
                return Response({
                    'success': True,
                    'regime': latest_regime.dominant_regime if latest_regime else 'Unknown',
                    'count': 0,
                    'update_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'stocks': []
                })

            # 获取股票详细信息
            stocks = []
            total_roe = 0
            total_pe = 0
            valid_pe_count = 0

            for stock_code in stock_codes[:100]:  # 限制最多返回 100 只
                stock_info = self.stock_repo.get_stock_info(stock_code)
                if not stock_info:
                    continue

                # 获取最新估值和财务数据
                from datetime import timedelta
                end_date = date.today()
                start_date = end_date - timedelta(days=7)

                valuations = self.stock_repo.get_valuation_history(
                    stock_code, start_date, end_date
                )
                latest_valuation = valuations[-1] if valuations else None

                financial = self.stock_repo.get_latest_financial_data(stock_code)

                stock_data = {
                    'code': stock_info.stock_code,
                    'name': stock_info.name,
                    'sector': stock_info.sector,
                    'roe': financial.roe if financial else 0,
                    'pe': latest_valuation.pe if latest_valuation and latest_valuation.pe > 0 else 0,
                    'pb': latest_valuation.pb if latest_valuation and latest_valuation.pb > 0 else 0,
                    'revenue_growth': financial.revenue_growth if financial else 0,
                    'profit_growth': financial.net_profit_growth if financial else 0,
                    'score': 0  # 暂时为 0，后续可添加评分逻辑
                }
                stocks.append(stock_data)

                if financial:
                    total_roe += financial.roe
                if latest_valuation and latest_valuation.pe > 0:
                    total_pe += latest_valuation.pe
                    valid_pe_count += 1

            avg_roe = total_roe / len(stocks) if stocks else 0
            avg_pe = total_pe / valid_pe_count if valid_pe_count > 0 else 0

            return Response({
                'success': True,
                'regime': pool_info.get('regime') if pool_info else (
                    latest_regime.dominant_regime if latest_regime else 'Unknown'
                ),
                'count': len(stocks),
                'update_time': pool_info.get('updated_at') if pool_info else timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                'avg_roe': round(avg_roe, 2),
                'avg_pe': round(avg_pe, 2),
                'stocks': stocks
            })

        except Exception as e:
            return Response({
                'success': False,
                'message': f'获取股票池失败: {str(e)}',
                'stocks': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='pool/refresh')
    def refresh_pool(self, request):
        """
        POST /equity/api/pool/refresh/

        刷新股票池

        基于当前 Regime 重新筛选股票池。
        """
        from apps.equity.infrastructure.adapters import StockPoolRepositoryAdapter
        from apps.regime.application.current_regime import resolve_current_regime

        try:
            # 获取当前 Regime
            latest_regime = resolve_current_regime()
            if not latest_regime:
                return Response({
                    'success': False,
                    'message': '无法获取当前 Regime，请先运行 Regime 判定'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            # 构造筛选请求
            screen_request = ScreenStocksRequest(
                regime=latest_regime.dominant_regime,
                max_count=50  # 默认筛选 50 只股票
            )

            # 执行筛选
            screen_use_case = ScreenStocksUseCase(
                stock_repository=self.stock_repo,
                regime_repository=self.regime_repo
            )
            screen_response = screen_use_case.execute(screen_request)

            if not screen_response.success:
                return Response({
                    'success': False,
                    'message': f'筛选失败: {screen_response.error}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 保存新的股票池
            pool_adapter = StockPoolRepositoryAdapter()
            pool_adapter.save_pool(
                stock_codes=screen_response.stock_codes,
                regime=latest_regime.dominant_regime,
                as_of_date=date.today()
            )

            return Response({
                'success': True,
                'message': '股票池已刷新',
                'regime': latest_regime.dominant_regime,
                'count': len(screen_response.stock_codes),
                'update_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            })

        except Exception as e:
            return Response({
                'success': False,
                'message': f'刷新股票池失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ==================== 估值修复跟踪 API ====================

    @extend_schema(
        summary="获取估值修复状态",
        description="获取单只股票的估值修复状态（实时计算）",
        responses={200: ValuationRepairStatusResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation-repair/(?P<stock_code>(?!scan|list)[^/]+)')
    def get_valuation_repair_status(self, request, stock_code):
        """
        GET /api/equity/valuation-repair/{stock_code}/

        获取估值修复状态

        实时计算估值修复状态，不依赖快照表。

        Response:
        {
            "success": true,
            "stock_code": "600030.SH",
            "stock_name": "中信证券",
            "as_of_date": "2026-03-10",
            "phase": "repairing",
            "signal": "hold",
            "current_pe": 12.5,
            "current_pb": 1.3,
            "pe_percentile": 0.25,
            "pb_percentile": 0.30,
            "composite_percentile": 0.28,
            "composite_method": "pb_weighted",
            "repair_start_date": "2026-02-01",
            "repair_start_percentile": 0.10,
            "lowest_percentile": 0.08,
            "lowest_percentile_date": "2026-01-15",
            "repair_progress": 0.45,
            "target_percentile": 0.50,
            "repair_speed_per_30d": 0.08,
            "estimated_days_to_target": 82,
            "is_stalled": false,
            "stall_start_date": null,
            "stall_duration_trading_days": 0,
            "repair_duration_trading_days": 30,
            "lookback_trading_days": 756,
            "confidence": 0.85,
            "description": "估值修复进行中，已从底部修复约45%"
        }
        """
        # 1. 获取并验证 lookback_days 参数
        try:
            lookback_days = int(request.query_params.get('lookback_days', 756))
            if lookback_days < 30 or lookback_days > 2520:
                return Response({
                    'success': False,
                    'error': 'lookback_days must be between 30 and 2520'
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'lookback_days must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. 构造请求对象
        use_case_request = GetValuationRepairStatusRequest(
            stock_code=stock_code,
            lookback_days=lookback_days
        )

        # 3. 执行用例
        use_case = GetValuationRepairStatusUseCase(
            stock_repository=self.stock_repo,
            valuation_repair_repository=self.repair_repo,
            valuation_quality_repository=self.quality_repo,
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        if use_case_response.success:
            return Response(use_case_response.data, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': use_case_response.error
            }, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="获取估值修复历史",
        description="获取估值百分位历史序列（实时计算）",
        responses={200: ValuationRepairHistoryResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation-repair/(?P<stock_code>(?!scan|list)[^/]+)/history')
    def get_valuation_repair_history(self, request, stock_code):
        """
        GET /api/equity/valuation-repair/{stock_code}/history/

        获取估值百分位历史

        实时计算百分位历史序列，用于绘制修复曲线。

        Response:
        {
            "stock_code": "600030.SH",
            "points": [
                {
                    "trade_date": "2026-01-01",
                    "pe_percentile": 0.15,
                    "pb_percentile": 0.20,
                    "composite_percentile": 0.18,
                    "composite_method": "pb_weighted"
                },
                ...
            ]
        }
        """
        # 1. 获取并验证 lookback_days 参数
        try:
            lookback_days = int(request.query_params.get('lookback_days', 252))
            if lookback_days < 30 or lookback_days > 2520:
                return Response({
                    'success': False,
                    'error': 'lookback_days must be between 30 and 2520'
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'lookback_days must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. 构造请求对象
        use_case_request = GetValuationPercentileHistoryRequest(
            stock_code=stock_code,
            lookback_days=lookback_days
        )

        # 3. 执行用例
        use_case = GetValuationPercentileHistoryUseCase(
            stock_repository=self.stock_repo
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        if use_case_response.success:
            latest_snapshot = self.quality_repo.get_latest_snapshot()
            return Response({
                'stock_code': stock_code,
                'points': use_case_response.data,
                'data_quality_flag': ("ok" if (latest_snapshot and latest_snapshot.is_gate_passed) else None),
                'data_source_provider': 'local_db',
                'data_as_of_date': (latest_snapshot.as_of_date.isoformat() if latest_snapshot else None),
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': use_case_response.error
            }, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="批量扫描估值修复",
        description="批量扫描股票池并保存快照",
        request=ScanValuationRepairsRequestSerializer,
        responses={200: ScanValuationRepairsResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='valuation-repair/scan')
    def scan_valuation_repairs(self, request):
        """
        POST /api/equity/valuation-repair/scan/

        批量扫描估值修复

        对指定股票池批量计算估值修复状态，并保存快照。

        Request Body:
        {
            "universe": "all_active",  // 或 "current_pool"
            "lookback_days": 756
        }

        Response:
        {
            "success": true,
            "universe": "all_active",
            "as_of_date": "2026-03-10",
            "scanned_count": 100,
            "saved_count": 45,
            "phase_counts": {
                "undervalued": 10,
                "repair_started": 15,
                "repairing": 18,
                "near_target": 2
            }
        }
        """
        # 1. 验证请求
        serializer = ScanValuationRepairsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 构造请求对象
        use_case_request = ScanValuationRepairsRequest(
            universe=data.get('universe', 'all_active'),
            lookback_days=data.get('lookback_days', 756),
            limit=None
        )

        # 3. 执行用例
        use_case = ScanValuationRepairsUseCase(
            stock_repository=self.stock_repo,
            valuation_repair_repository=self.repair_repo,
            stock_pool_adapter=self.pool_adapter,
            valuation_quality_repository=self.quality_repo,
        )
        use_case_response = use_case.execute(use_case_request)

        # 4. 返回响应
        if use_case_response.success:
            response_data = {
                'success': True,
                'universe': use_case_response.universe,
                'as_of_date': use_case_response.as_of_date.isoformat(),
                'scanned_count': use_case_response.scanned_count,
                'saved_count': use_case_response.saved_count,
                'phase_counts': use_case_response.phase_counts
            }
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': use_case_response.error
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="同步估值数据",
        description="从主备 provider 同步估值数据到本地估值表",
        request=SyncValuationDataRequestSerializer,
        responses={200: SyncValuationDataResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='valuation-data/sync')
    def sync_valuation_data(self, request):
        serializer = SyncValuationDataRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = SyncEquityValuationUseCase(stock_repository=self.stock_repo)
        response = use_case.execute(
            SyncEquityValuationRequest(
                stock_codes=data.get("stock_codes"),
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                days_back=data.get("days_back", 1),
                primary_source=data.get("primary_source", "akshare"),
                fallback_source=data.get("fallback_source", "tushare"),
            )
        )
        if response.success:
            return Response(response.data, status=status.HTTP_200_OK)
        return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="校验估值数据质量",
        description="对本地估值表生成质量快照并计算 gate 状态",
        request=ValidateValuationDataRequestSerializer,
        responses={200: ValuationQualitySnapshotResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='valuation-data/validate')
    def validate_valuation_data(self, request):
        serializer = ValidateValuationDataRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = ValidateEquityValuationQualityUseCase(
            stock_repository=self.stock_repo,
            quality_repository=self.quality_repo,
        )
        response = use_case.execute(
            ValidateEquityValuationQualityRequest(
                as_of_date=data.get("as_of_date"),
                primary_source=data.get("primary_source", "akshare"),
            )
        )
        if response.success:
            return Response(response.data, status=status.HTTP_200_OK)
        return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="获取估值数据新鲜度",
        description="返回本地估值表最新交易日和 freshness 状态",
        responses={200: ValuationFreshnessResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation-data/freshness')
    def valuation_data_freshness(self, request):
        use_case = GetEquityValuationFreshnessUseCase(
            stock_repository=self.stock_repo,
            quality_repository=self.quality_repo,
        )
        response = use_case.execute()
        if response.success:
            return Response(response.data, status=status.HTTP_200_OK)
        return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="获取最近估值数据质量快照",
        description="返回最近一次估值数据质量快照",
        responses={200: ValuationQualitySnapshotResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation-data/quality-latest')
    def valuation_data_quality_latest(self, request):
        use_case = GetLatestEquityValuationQualityUseCase(
            quality_repository=self.quality_repo,
        )
        response = use_case.execute()
        if response.success:
            return Response(response.data, status=status.HTTP_200_OK)
        return Response({"success": False, "error": response.error}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="列出估值修复快照",
        description="列出估值修复快照（不触发实时重算）",
        request=ListValuationRepairsRequestSerializer,
        responses={200: ListValuationRepairsResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='valuation-repair-list')
    def list_valuation_repairs(self, request):
        """
        GET /api/equity/valuation-repair-list/

        列出估值修复快照

        直接读取快照表，不触发实时重算。

        Query Parameters:
        - universe: all_active 或 current_pool（默认 all_active）
        - phase: 阶段过滤（可选）
        - limit: 返回数量限制（默认 50）

        Response:
        {
            "success": true,
            "results": [
                {
                    "stock_code": "600030.SH",
                    "stock_name": "中信证券",
                    "phase": "repairing",
                    "signal": "hold",
                    "composite_percentile": 0.28,
                    "repair_progress": 0.45,
                    "repair_speed_per_30d": 0.08,
                    "repair_duration_trading_days": 30,
                    "estimated_days_to_target": 82,
                    "is_stalled": false,
                    "as_of_date": "2026-03-10"
                },
                ...
            ]
        }
        """
        # 1. 验证并获取参数
        try:
            limit = int(request.query_params.get('limit', 50))
            if limit < 1 or limit > 200:
                return Response({
                    'success': False,
                    'error': 'limit must be between 1 and 200'
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'limit must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. 构造请求对象
        use_case_request = ListValuationRepairsRequest(
            universe=request.query_params.get('universe', 'all_active'),
            phase=request.query_params.get('phase'),
            limit=limit
        )

        # 2. 执行用例
        use_case = ListValuationRepairsUseCase(
            valuation_repair_repository=self.repair_repo
        )
        use_case_response = use_case.execute(use_case_request)

        # 3. 返回响应
        if use_case_response.success:
            return Response({
                'success': True,
                'results': use_case_response.data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': use_case_response.error
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== 多维度筛选 API（通用资产分析框架集成） ====================


class EquityMultiDimScreenAPIView(APIView):
    """个股多维度筛选 API

    POST /api/equity/multidim-screen/

    使用通用资产分析框架进行多维度评分筛选。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
        from apps.equity.application.services import EquityMultiDimScorer

        self.asset_repo = DjangoEquityAssetRepository()
        self.scorer = EquityMultiDimScorer(self.asset_repo)

    def post(self, request) -> Response:
        """
        多维度筛选个股

        请求体：
        {
            "filters": {
                "sector": "银行",
                "market": "SH",
                "min_market_cap": 50000000000,
                "max_pe": 15.0
            },
            "context": {
                "regime": "Recovery",
                "policy_level": "P0",
                "sentiment_index": 0.5
            },
            "max_count": 30
        }
        """
        # 1. 验证请求
        filters = request.data.get("filters", {})
        context_data = request.data.get("context", {})
        max_count = request.data.get("max_count", 30)

        # 2. 构建评分上下文
        from apps.asset_analysis.domain.value_objects import ScoreContext
        from apps.signal.infrastructure.repositories import DjangoSignalRepository

        # 获取激活的信号
        signal_repo = DjangoSignalRepository()
        active_signals = signal_repo.get_active_signals()

        context = ScoreContext(
            current_regime=context_data.get("regime", "Recovery"),
            policy_level=context_data.get("policy_level", "P0"),
            sentiment_index=context_data.get("sentiment_index", 0.0),
            active_signals=active_signals,
        )

        # 3. 执行筛选
        try:
            result = self.scorer.screen_stocks(
                filters=filters,
                context=context,
                max_count=max_count,
            )

            # 4. 返回响应
            return Response({
                "success": result["success"],
                "count": result["count"],
                "context": {
                    "regime": context.current_regime,
                    "policy_level": context.policy_level,
                    "sentiment_index": context.sentiment_index,
                    "active_signals_count": len(active_signals),
                },
                "stocks": result["stocks"],
            }, status=status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"筛选失败: {str(e)}",
                "stocks": [],
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============== 估值修复配置管理 API ==============

class ValuationRepairConfigViewSet(viewsets.ModelViewSet):
    """估值修复策略参数配置管理

    支持在线调参，包含版本控制、生效时间和审计。

    API 端点：
    - GET /api/equity/config/valuation-repair/ - 列出所有配置版本
    - GET /api/equity/config/valuation-repair/active/ - 获取当前激活的配置
    - POST /api/equity/config/valuation-repair/ - 创建新配置
    - POST /api/equity/config/valuation-repair/{id}/activate/ - 激活指定配置
    - POST /api/equity/config/valuation-repair/{id}/rollback/ - 回滚到指定版本
    """

    from apps.equity.infrastructure.models import ValuationRepairConfigModel
    queryset = ValuationRepairConfigModel.objects.all()
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        from apps.equity.interface.serializers import (
            ValuationRepairConfigSerializer,
            ValuationRepairConfigCreateSerializer,
        )
        if self.action in ['create', 'update', 'partial_update']:
            return ValuationRepairConfigCreateSerializer
        return ValuationRepairConfigSerializer

    @extend_schema(
        summary="获取当前激活配置",
        description="返回当前生效中的估值修复策略参数",
        responses={200: "ValuationRepairConfigSerializer"},
    )
    @action(detail=False, methods=['get'])
    def active(self, request):
        """GET /api/equity/config/valuation-repair/active/

        获取当前激活的配置
        """
        from apps.equity.application.config import get_valuation_repair_config
        from apps.equity.domain.entities_valuation_repair import DEFAULT_VALUATION_REPAIR_CONFIG

        runtime_config = get_valuation_repair_config(use_cache=False)
        try:
            config = self.queryset.filter(is_active=True).first()
        except (OperationalError, ProgrammingError):
            config = None
        if not config:
            source = "settings"
            if runtime_config == DEFAULT_VALUATION_REPAIR_CONFIG:
                source = "default"
            return Response({
                "success": True,
                "source": source,
                "data": {
                    "version": 0,
                    "is_active": False,
                    "min_history_points": runtime_config.min_history_points,
                    "default_lookback_days": runtime_config.default_lookback_days,
                    "confirm_window": runtime_config.confirm_window,
                    "min_rebound": runtime_config.min_rebound,
                    "stall_window": runtime_config.stall_window,
                    "stall_min_progress": runtime_config.stall_min_progress,
                    "target_percentile": runtime_config.target_percentile,
                    "undervalued_threshold": runtime_config.undervalued_threshold,
                    "near_target_threshold": runtime_config.near_target_threshold,
                    "overvalued_threshold": runtime_config.overvalued_threshold,
                    "pe_weight": runtime_config.pe_weight,
                    "pb_weight": runtime_config.pb_weight,
                    "confidence_base": runtime_config.confidence_base,
                    "confidence_sample_threshold": runtime_config.confidence_sample_threshold,
                    "confidence_sample_bonus": runtime_config.confidence_sample_bonus,
                    "confidence_blend_bonus": runtime_config.confidence_blend_bonus,
                    "confidence_repair_start_bonus": runtime_config.confidence_repair_start_bonus,
                    "confidence_not_stalled_bonus": runtime_config.confidence_not_stalled_bonus,
                    "repairing_threshold": runtime_config.repairing_threshold,
                    "eta_max_days": runtime_config.eta_max_days,
                }
            })

        serializer = self.get_serializer(config)
        return Response({
            "success": True,
            "source": "database",
            "data": serializer.data
        })

    @extend_schema(
        summary="激活指定配置",
        description="将指定版本的配置设置为激活状态（同时停用其他配置）",
        responses={200: "ValuationRepairConfigSerializer"},
    )
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """POST /api/equity/config/valuation-repair/{id}/activate/

        激活指定配置
        """
        config = self.get_object()
        config.is_active = True
        config.effective_from = timezone.now()
        config.save()

        # 清除缓存
        from apps.equity.application.config import clear_config_cache
        clear_config_cache()

        serializer = self.get_serializer(config)
        return Response({
            "success": True,
            "message": f"配置 v{config.version} 已激活",
            "data": serializer.data
        })

    @extend_schema(
        summary="回滚到指定版本",
        description="激活指定版本的配置（activate 的别名）",
        responses={200: "ValuationRepairConfigSerializer"},
    )
    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        """POST /api/equity/config/valuation-repair/{id}/rollback/

        回滚到指定版本（等同于 activate）
        """
        return self.activate(request, pk)

    @extend_schema(
        summary="清除配置缓存",
        description="强制清除配置缓存，下次请求将从数据库或 settings 重新加载",
        responses={200: dict},
    )
    @action(detail=False, methods=['post'])
    def clear_cache(self, request):
        """POST /api/equity/config/valuation-repair/clear_cache/

        清除配置缓存
        """
        from apps.equity.application.config import clear_config_cache
        clear_config_cache()
        return Response({
            "success": True,
            "message": "配置缓存已清除"
        })

    def perform_create(self, serializer):
        """创建时记录创建人"""
        serializer.save(
            created_by=self.request.user.username if self.request.user.is_authenticated else "api"
        )

    def perform_update(self, serializer):
        """更新后清缓存，避免激活配置或草稿配置读到旧值。"""
        serializer.save()
        from apps.equity.application.config import clear_config_cache
        clear_config_cache()

