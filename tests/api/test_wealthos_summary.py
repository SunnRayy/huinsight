
import pytest
from unittest.mock import MagicMock, patch
from src.api.routes.data import get_wealthos_summary
import asyncio

@pytest.fixture
def mock_db():
    return MagicMock()

def test_wealthos_summary_with_xirr(mock_db):
    """Test get_wealthos_summary includes valid XIRR and Lifetime Gain."""
    
    mock_db.execute.return_value.fetchone.return_value = (50,) # total count
    
    with patch('src.api.routes.performance.get_performance_summary') as mock_perf_summary:
        mock_perf_summary.return_value = {
            "total_lifetime_pl": 125000.0,
            "net_worth": 225000.0,
            "total_cost_basis": 100000.0,
            "asset_count": 10
        }
        with patch('src.api.routes.data.build_investment_returns') as mock_xirr:
            mock_xirr.return_value = {"mwr_xirr": 15.5, "scope": "investment_accounts"}  # 15.5%
            
            result = asyncio.run(get_wealthos_summary(include_non_rebalanceable=False, db=mock_db))
            
            assert result['total_lifetime_gain'] == 125000.0
            assert result['remaining_cost_basis_cny'] == 100000.0
            assert 'lifetime_gain_pct' not in result
            assert result['annualized_return'] == 15.5
            assert result['active_asset_count'] == 10
            assert result['total_asset_count'] == 50

def test_wealthos_summary_no_xirr(mock_db):
    """Test get_wealthos_summary handles missing XIRR gracefully."""
    
    mock_db.execute.return_value.fetchone.return_value = (50,) # total count
    
    with patch('src.api.routes.performance.get_performance_summary') as mock_perf_summary:
        mock_perf_summary.return_value = {
            "total_lifetime_pl": 125000.0,
            "net_worth": 200000.0,
            "total_cost_basis": 100000.0,
            "asset_count": 10
        }
        with patch('src.api.routes.data.build_investment_returns') as mock_xirr:
            mock_xirr.return_value = {"mwr_xirr": None, "scope": "investment_accounts"}
            
            result = asyncio.run(get_wealthos_summary(include_non_rebalanceable=False, db=mock_db))
            
            assert result['annualized_return'] is None


def test_wealthos_summary_calls_performance_summary_with_db_kwarg(mock_db):
    """Regression: get_wealthos_summary must pass db as keyword, not positional period."""

    observed = {"args": None, "kwargs": None}

    async def _fake_get_performance_summary(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {
            "net_worth": 1000.0,
            "total_cost_basis": 900.0,
            "total_lifetime_pl": 100.0,
            "asset_count": 3,
        }

    mock_db.execute.return_value.fetchone.return_value = (10,)

    with patch('src.api.routes.performance.get_performance_summary', side_effect=_fake_get_performance_summary):
        with patch('src.api.routes.data.build_investment_returns') as mock_xirr:
            mock_xirr.return_value = {"mwr_xirr": 12.0, "scope": "investment_accounts"}
            result = asyncio.run(get_wealthos_summary(include_non_rebalanceable=False, db=mock_db))

    assert observed["args"] == ()
    assert observed["kwargs"] == {
        "period": "all_time",
        "exclude_non_balanceable": False,
        "include_non_rebalanceable": False,
        "db": mock_db
    }
    assert result["total_lifetime_gain"] == 100.0
    assert result["active_asset_count"] == 3

def test_account_return_metadata_is_exposed_without_legacy_fallback(mock_db):
    mock_db.execute.return_value.fetchone.return_value = (10,)
    with patch('src.api.routes.performance.get_performance_summary', return_value={}), patch(
        'src.api.routes.data.build_investment_returns', return_value={"mwr_xirr": None, "scope": "investment_accounts"}
    ):
        result = asyncio.run(get_wealthos_summary(include_non_rebalanceable=False, db=mock_db))
    assert 'account_returns' in result
    assert result['account_returns']['scope'] == 'investment_accounts'
    assert result['annualized_return'] == result['account_returns']['mwr_xirr']
