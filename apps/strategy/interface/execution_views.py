"""Strategy execution and sandbox-testing JSON endpoints.

Interface层:
- 承载策略立即执行、执行评估、脚本/策略模拟测试等端点
- 只做输入验证和输出格式化，禁止业务逻辑
"""

import json
import logging

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from apps.strategy.application.interface_services import (
    build_strategy_executor,
    list_active_assignments_for_strategy,
)
from apps.strategy.domain.services import (
    DecisionPolicyEngine,
    PreTradeRiskGate,
    SizingEngine,
)
from apps.strategy.interface.serializers import (
    ExecutionEvaluateInputSerializer,
    ExecutionEvaluateOutputSerializer,
)

StrategyModel = django_apps.get_model("strategy", "StrategyModel")


@login_required
def strategy_execute(request, strategy_id):
    """
    立即执行策略

    支持两种模式:
    1. 单个投资组合执行 (portfolio_id 参数)
    2. 所有绑定投资组合执行 (无参数)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})


    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    try:
        # 解析请求参数
        data = json.loads(request.body) if request.body else {}
        portfolio_id = data.get('portfolio_id')

        # 初始化策略执行引擎
        executor = build_strategy_executor()

        # 执行策略
        results = []
        total_signals = 0
        failed_rules = []
        execution_ids = []

        if portfolio_id:
            # 单个投资组合执行
            result = executor.execute_strategy(strategy_id, portfolio_id)
            results.append(result)
            total_signals += len(result.signals)
            execution_ids.append(result.execution_time.isoformat())

            # 收集失败的规则（从上下文中推断）
            if not result.is_success:
                failed_rules.append({
                    'portfolio_id': portfolio_id,
                    'error': result.error_message
                })

        else:
            # 执行所有绑定的投资组合
            assignments = list_active_assignments_for_strategy(strategy.id)

            for assignment in assignments:
                portfolio = assignment.portfolio
                result = executor.execute_strategy(strategy_id, portfolio.id)
                results.append(result)
                total_signals += len(result.signals)
                execution_ids.append(result.execution_time.isoformat())

                if not result.is_success:
                    failed_rules.append({
                        'portfolio_id': portfolio.id,
                        'portfolio_name': portfolio.account_name,
                        'error': result.error_message
                    })

        # 计算总执行时长
        duration_ms = sum(r.execution_duration_ms for r in results) if results else 0

        # 构建响应
        return JsonResponse({
            'success': all(r.is_success for r in results) if results else True,
            'execution_id': execution_ids[0] if len(execution_ids) == 1 else execution_ids,
            'generated_signals': total_signals,
            'signals_count': total_signals,
            'failed_rules': failed_rules,
            'duration_ms': duration_ms,
            'executed_portfolios': len(results),
            'message': f'策略执行完成，生成 {total_signals} 个信号'
        })

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Strategy execution failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'execution_id': None,
            'generated_signals': 0,
            'signals_count': 0,
            'failed_rules': [{'error': str(e)}],
            'duration_ms': 0
        })


@login_required
def execution_evaluate(request):
    """执行评估 API：返回 decision/sizing/risk 的静态评估结果，不提交真实订单。"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'}, status=405)


    try:
        payload = json.loads(request.body.decode('utf-8') if request.body else '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '无效 JSON'}, status=400)

    input_serializer = ExecutionEvaluateInputSerializer(data=payload)
    if not input_serializer.is_valid():
        return JsonResponse(
            {'success': False, 'errors': input_serializer.errors},
            status=400
        )

    data = input_serializer.validated_data

    decision_engine = DecisionPolicyEngine(
        signal_threshold=getattr(settings, 'DECISION_SIGNAL_THRESHOLD', 0.6),
        confidence_threshold=getattr(settings, 'DECISION_CONFIDENCE_THRESHOLD', 0.7),
        regime_alignment_required=getattr(settings, 'DECISION_REGIME_ALIGNMENT_REQUIRED', True),
        max_daily_loss_pct=getattr(settings, 'RISK_MAX_DAILY_LOSS_PCT', 5.0),
        max_daily_trades=getattr(settings, 'RISK_MAX_DAILY_TRADES', 10),
    )
    sizing_engine = SizingEngine(
        default_method=getattr(settings, 'SIZING_DEFAULT_METHOD', 'fixed_fraction'),
        risk_per_trade_pct=getattr(settings, 'SIZING_RISK_PER_TRADE_PCT', 1.0),
        max_position_pct=getattr(settings, 'SIZING_MAX_POSITION_PCT', 20.0),
        min_qty=getattr(settings, 'SIZING_MIN_QTY', 1),
    )
    risk_gate = PreTradeRiskGate(
        max_single_position_pct=getattr(settings, 'RISK_MAX_SINGLE_POSITION_PCT', 20.0),
        max_daily_trades=getattr(settings, 'RISK_MAX_DAILY_TRADES', 10),
        max_daily_loss_pct=getattr(settings, 'RISK_MAX_DAILY_LOSS_PCT', 5.0),
        min_volume=getattr(settings, 'RISK_MIN_VOLUME', 100000),
    )

    signal_direction = data.get('signal_direction') or ('bullish' if data['side'] == 'buy' else 'bearish')
    current_price = data.get('current_price') or 100.0

    decision_action, reason_codes, reason_text, valid_until_seconds = decision_engine.evaluate(
        signal_strength=data['signal_strength'],
        signal_direction=signal_direction,
        signal_confidence=data['signal_confidence'],
        regime=data.get('target_regime') or 'Unknown',
        regime_confidence=0.8,
        daily_pnl_pct=data['daily_pnl_pct'],
        daily_trade_count=data['daily_trade_count'],
        volatility_z=data.get('volatility_z'),
        target_regime=data.get('target_regime'),
    )

    target_notional, qty, expected_risk_pct, sizing_method, sizing_explain = sizing_engine.calculate(
        method=data.get('sizing_method') or getattr(settings, 'SIZING_DEFAULT_METHOD', 'fixed_fraction'),
        account_equity=data['account_equity'],
        current_price=current_price,
        stop_loss_price=data.get('stop_loss_price'),
        atr=data.get('atr'),
        current_position_value=data['current_position_value'],
    )

    passed, violations, warnings, _ = risk_gate.check(
        symbol=data['symbol'],
        side=data['side'],
        qty=qty,
        price=current_price,
        account_equity=data['account_equity'],
        current_position_value=data['current_position_value'],
        daily_trade_count=data['daily_trade_count'],
        daily_pnl_pct=data['daily_pnl_pct'],
        avg_volume=data.get('avg_volume'),
    )

    risk_snapshot = {
        'daily_trade_count': data['daily_trade_count'],
        'daily_pnl_pct': data['daily_pnl_pct'],
        'violations': violations,
        'warnings': warnings,
    }

    output = {
        'decision_action': decision_action,
        'decision_reasons': reason_codes,
        'decision_text': reason_text,
        'decision_confidence': data['signal_confidence'],
        'valid_until_seconds': valid_until_seconds,
        'target_notional': target_notional,
        'qty': qty,
        'expected_risk_pct': expected_risk_pct,
        'sizing_method': sizing_method,
        'sizing_explain': sizing_explain,
        'risk_snapshot': risk_snapshot,
        'can_execute': decision_action == 'allow' and passed,
        'requires_confirmation': decision_action == 'watch',
    }
    output_serializer = ExecutionEvaluateOutputSerializer(data=output)
    output_serializer.is_valid(raise_exception=True)
    return JsonResponse({'success': True, 'data': output_serializer.validated_data})


@login_required
def test_script(request):
    """测试脚本执行（沙箱环境）"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    import time

    from apps.strategy.application.script_engine import (
        ScriptAPI,
        ScriptExecutionEnvironment,
        SecurityMode,
    )

    try:
        data = json.loads(request.body)
        script_code = data.get('script_code', '')

        if not script_code or not script_code.strip():
            return JsonResponse({'success': False, 'error': '脚本代码不能为空'})

        # 创建模拟的 API 提供者
        class MockMacroProvider:
            def get_indicator(self, code):
                mock_data = {
                    'CN_PMI_MANUFACTURING': 50.8,
                    'CN_CPI_YOY': 2.1,
                    'CN_PPI_YOY': -2.8,
                }
                return mock_data.get(code)

            def get_all_indicators(self):
                return {
                    'CN_PMI_MANUFACTURING': 50.8,
                    'CN_CPI_YOY': 2.1,
                    'CN_PPI_YOY': -2.8,
                }

        class MockRegimeProvider:
            def get_current_regime(self):
                return {
                    'dominant_regime': 'HG',
                    'confidence': 0.75,
                    'growth_momentum_z': 1.2,
                    'inflation_momentum_z': 0.8,
                }

        class MockAssetPoolProvider:
            def get_investable_assets(self, min_score=60, limit=50):
                return []

        class MockSignalProvider:
            def get_valid_signals(self):
                return []

        class MockPortfolioProvider:
            def get_positions(self, portfolio_id):
                return []

            def get_cash(self, portfolio_id):
                return 100000.0

        # 创建脚本 API
        script_api = ScriptAPI(
            macro_provider=MockMacroProvider(),
            regime_provider=MockRegimeProvider(),
            asset_pool_provider=MockAssetPoolProvider(),
            signal_provider=MockSignalProvider(),
            portfolio_provider=MockPortfolioProvider(),
            portfolio_id=1
        )

        # 创建沙箱执行环境
        env = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED)

        # 记录开始时间
        start_time = time.time()

        # 执行脚本
        try:
            signals = env.execute(
                script_code=script_code,
                script_api=script_api,
                script_name='<test>'
            )

            execution_time = int((time.time() - start_time) * 1000)

            return JsonResponse({
                'success': True,
                'execution_time': execution_time,
                'signals_count': len(signals),
                'signals': signals,
                'output': f'脚本执行成功，生成 {len(signals)} 个信号'
            })

        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'脚本执行错误: {str(e)}'
            })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '无效的 JSON 数据'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def test_strategy(request, strategy_id):
    """测试策略执行（模拟数据）"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '只支持 POST 请求'})

    import time

    strategy = get_object_or_404(StrategyModel, id=strategy_id, created_by=request.user.account_profile)

    try:
        data = json.loads(request.body)
        portfolio_id = data.get('portfolio_id')

        if not portfolio_id:
            return JsonResponse({'success': False, 'error': '缺少 portfolio_id 参数'})

        # 模拟策略执行（使用模拟数据）
        start_time = time.time()

        # 测试模式不再注入任何模拟证券代码；仅返回真实执行结果或空列表。
        mock_signals = []

        if strategy.strategy_type in ['rule_based', 'hybrid']:
            mock_signals = []

        elif strategy.strategy_type in ['script_based', 'hybrid']:
            # 脚本驱动策略：模拟脚本执行结果
            try:
                from apps.strategy.application.script_engine import (
                    ScriptAPI,
                    ScriptExecutionEnvironment,
                    SecurityMode,
                )

                # 创建模拟 API 提供者
                class MockMacroProvider:
                    def get_indicator(self, code):
                        mock_data = {
                            'CN_PMI_MANUFACTURING': 50.8,
                            'CN_CPI_YOY': 2.1,
                        }
                        return mock_data.get(code)

                class MockRegimeProvider:
                    def get_current_regime(self):
                        return {'dominant_regime': 'HG'}

                class MockAssetPoolProvider:
                    def get_investable_assets(self, min_score=60, limit=50):
                        return []

                class MockSignalProvider:
                    def get_valid_signals(self):
                        return []

                class MockPortfolioProvider:
                    def get_positions(self, portfolio_id):
                        return []
                    def get_cash(self, portfolio_id):
                        return 100000.0

                # 如果有脚本配置，执行脚本
                if strategy.script_config:
                    script_api = ScriptAPI(
                        macro_provider=MockMacroProvider(),
                        regime_provider=MockRegimeProvider(),
                        asset_pool_provider=MockAssetPoolProvider(),
                        signal_provider=MockSignalProvider(),
                        portfolio_provider=MockPortfolioProvider(),
                        portfolio_id=portfolio_id
                    )
                    env = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED)
                    mock_signals = env.execute(
                        script_code=strategy.script_config.script_code,
                        script_api=script_api,
                        script_name=f'test_{strategy.id}'
                    )
            except Exception:
                mock_signals = []

        elif strategy.strategy_type == 'ai_driven':
            mock_signals = []

        execution_time = int((time.time() - start_time) * 1000)

        return JsonResponse({
            'success': True,
            'execution_time': execution_time,
            'signals_count': len(mock_signals),
            'signals': mock_signals
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


__all__ = [
    "execution_evaluate",
    "strategy_execute",
    "test_script",
    "test_strategy",
]
