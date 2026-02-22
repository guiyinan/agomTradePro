from datetime import date
from unittest.mock import Mock, patch

import pytest

from apps.regime.application.use_cases import HighFrequencySignalUseCase


@pytest.mark.django_db
def test_term_spread_signal_uses_config_threshold():
    use_case = HighFrequencySignalUseCase(repository=Mock())

    # 当前值 80BP，配置阈值 50BP -> 应判定为 BULLISH
    with patch("apps.macro.infrastructure.repositories.DjangoMacroRepository") as repo_cls, \
         patch("apps.regime.application.use_cases.ConfigHelper.get_float", return_value=50.0):
        repo = repo_cls.return_value
        repo.get_latest_observation.return_value = Mock(value=80.0)

        result = use_case._evaluate_term_spread(date.today())

    assert result["success"] is True
    assert result["signal"] == "BULLISH"


@pytest.mark.django_db
def test_term_spread_signal_respects_higher_config_threshold():
    use_case = HighFrequencySignalUseCase(repository=Mock())

    # 当前值 80BP，配置阈值 120BP -> 应判定为 NEUTRAL
    with patch("apps.macro.infrastructure.repositories.DjangoMacroRepository") as repo_cls, \
         patch("apps.regime.application.use_cases.ConfigHelper.get_float", return_value=120.0):
        repo = repo_cls.return_value
        repo.get_latest_observation.return_value = Mock(value=80.0)

        result = use_case._evaluate_term_spread(date.today())

    assert result["success"] is True
    assert result["signal"] == "NEUTRAL"
