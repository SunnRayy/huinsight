"""Account-risk scope, failure and input-version contracts."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.api.routes.performance import get_risk_metrics
from src.services.investment_risk import build_investment_risk


@pytest.mark.asyncio
async def test_risk_metrics_ignores_household_filter_and_preserves_selected_window():
    expected = {'scope': 'investment_accounts', 'data_points': 12}
    with patch('src.services.investment_risk.build_investment_risk', return_value=expected) as calc:
        result = await get_risk_metrics(period='last_12m', exclude_non_balanceable=True,
                                       include_non_rebalanceable=False, db=MagicMock())
    assert result == expected
    assert calc.call_args.kwargs == {'period': 'last_12m'}


@pytest.mark.asyncio
async def test_risk_query_failure_is_http_error_not_missing_data():
    with patch('src.services.investment_risk.build_investment_risk',
               side_effect=RuntimeError('private/path')):
        result = await get_risk_metrics(period='all_time', db=MagicMock())
    assert result.status_code == 500
    assert 'error' in json.loads(result.body)
    assert 'private/path' not in result.body.decode()


def test_risk_rejects_mismatched_account_input_fingerprint():
    account = {'scope': 'investment_accounts', 'input_fingerprint': 'A',
               'investment_bridge': {'period_start': '2025-08-31', 'period_end': '2026-08-31'}}
    with patch('src.services.investment_risk.load_investment_return_inputs',
               return_value={'input_fingerprint': 'B', 'scope': 'investment_accounts'}) as loader:
        result = build_investment_risk(None, account_result=account)
    assert loader.call_args.args[1:] == ('2025-08-31', '2026-08-31')
    assert result['total_return'] is None
    assert result['quality'] == 'unavailable'
