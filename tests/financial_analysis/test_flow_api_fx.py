"""API decisions and FX transport use only memory DBs and stub responses."""
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.financial_analysis.test_flow_rules import web
from src.api.dependencies import get_db, get_writable_db
from src.api.routes.performance import router
from src.financial_analysis.fx_daily import cache_fred_fx, lookup_fx


def test_api_review_validation_and_reuse(reviewed_flow_db, monkeypatch):
    dirty = Mock()
    monkeypatch.setattr("src.api.routes.performance.mark_dirty", dirty)
    web(reviewed_flow_db, 'unrecognized')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: reviewed_flow_db
    app.dependency_overrides[get_writable_db] = lambda: reviewed_flow_db
    with TestClient(app) as client:
        item = client.get('/performance/flow-review').json()['items'][0]
        url = '/performance/flow-review/' + item['event_key']
        for body in [{'decision': 'invalid'}, {'decision': 'manual'},
                     {'decision': 'external_out', 'amount_cny': -1}]:
            assert client.put(url, json=body).status_code == 422
        assert client.put(url, json={'decision': 'internal'}).status_code == 200
        assert not client.get('/performance/flow-review').json()['items']
        assert client.put(url, json={'decision': 'internal'}).status_code == 200
        assert dirty.called
        assert client.put('/performance/flow-review/not-found', json={'decision': 'internal'}).status_code == 422
        assert client.put('/performance/flow-review/manual:2026-09-12:test', json={'decision': 'manual', 'amount_cny': 20}).status_code == 200


def test_fred_cache_no_fallback(flow_db, monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'synthetic')
    response = Mock()
    response.json.return_value = {'observations': [
        {'date': '2026-09-09', 'value': '7.1'}, {'date': '2026-09-10', 'value': '.'}]}
    request = Mock(return_value=response)
    monkeypatch.setattr('src.financial_analysis.fx_daily.http_get', request)
    assert cache_fred_fx(flow_db, '2026-09-10', '2026-09-10') == 1
    assert lookup_fx(flow_db, '2026-09-10')[1] == 7.1
    request.side_effect = RuntimeError('synthetic network failure')
    assert cache_fred_fx(flow_db, '2026-10-01', '2026-10-01') == 0
    assert lookup_fx(flow_db, '2026-10-01') is None
    assert request.call_args.kwargs['params']['series_id'] == 'DEXCHUS'
