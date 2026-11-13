"""Insight reinforcement (spec docs/api-specs/insight-reinforcement.md; synthetic data only)."""
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.services.ai_advisor.insight_manager import check_promotion_gate
from src.services.ai_advisor.insight_merge import build_groups, merge_group, similar_groups
from src.services.ai_advisor.insight_reinforcement import (
    format_insight_library,
    resolve_assets,
    reverse_review,
    split_insight_items,
)
from src.services.ai_advisor.review_generator import ReviewGenerator, build_review_prompt_text


@pytest.fixture
def db_path(tmp_path):
    from src.database.connector import DatabaseConnector

    path = str(tmp_path / "insights.duckdb")
    with DatabaseConnector(path) as db:
        db.execute(Path("src/database/schema.sql").read_text())
        db.run_migrations()
    conn = duckdb.connect(path)
    conn.execute("INSERT INTO asset_registry (canonical_id, display_name) VALUES "
                 "('US_STK_SGOV', 'ISHARES 0-3 MONTH TREASURY BOND ETF'), ('ALTS_Paper_Gold', '纸黄金')")
    for rid, day in [(1, '2026-04-03'), (2, '2026-05-04'), (3, '2026-06-28'), (4, '2026-08-09')]:
        conn.execute("INSERT INTO ai_reports (id, report_type, title, content_json, created_at) "
                     "VALUES (?, 'review', 'r', '{}', ?)", [rid, day])
    conn.close()
    return path


def insert(path, title, report_id, status='raw', category='strategy', **extra):
    conn = duckdb.connect(path)
    cols = ['title', 'body', 'category', 'status', 'source_report_id', 'confidence'] + list(extra)
    vals = [title, '', category, status, report_id, 0.3] + list(extra.values())
    new_id = conn.execute(f"INSERT INTO ai_insights ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                          "RETURNING id", vals).fetchone()[0]
    conn.close()
    return new_id


def row(path, insight_id):
    conn = duckdb.connect(path, read_only=True)
    r = conn.execute("SELECT status, recurrence_count, validated_cases, validated_case_links, entity_refs "
                     "FROM ai_insights WHERE id = ?", [insight_id]).fetchone()
    conn.close()
    return {'status': r[0], 'recurrence': r[1], 'cases': r[2],
            'links': json.loads(r[3]) if r[3] else [], 'refs': r[4]}


def review(*items, section='rule_updates', key='suggestions'):
    return split_insight_items({section: {'narrative': '', key: list(items)}})


def test_items_are_stored_as_strings_with_links_beside_them():
    content = split_insight_items({
        'lessons_learned': {'lessons': [{'text': 'Keep the SGOV reserve', 'reinforces': ['#5', 5, 'x'],
                                         'assets': ['SGOV']}, 'plain lesson', ''],
                            'improvements': []},
        'rule_updates': {'suggestions': [{'text': 'No same-day round trips', 'reinforces': []}]},
    })
    assert content['lessons_learned']['lessons'] == ['Keep the SGOV reserve', 'plain lesson']
    assert content['rule_updates']['suggestions'] == ['No same-day round trips']
    assert [(x['category'], x['reinforces'], x['assets']) for x in content['insight_links']] == [
        ('process', [5], ['SGOV']), ('process', [], []), ('strategy', [], [])]
    assert split_insight_items(content) == content  # idempotent


def test_three_reinforcing_reviews_make_an_insight_promotable(db_path):
    target = insert(db_path, 'Keep 70% of SGOV for the SPX 6300 plan', report_id=1)
    gen = ReviewGenerator()
    for rid in (2, 3, 4):
        item = {'text': f'Ring-fence the SGOV reserve (review {rid})', 'reinforces': [target],
                'assets': ['us_stk_sgov', 'Unknown Fund']}
        gen.extract_insights(review(item), rid, db_path)
        gen.extract_insights(review(item), rid, db_path)  # re-processing counts nothing twice
    r = row(db_path, target)
    assert (r['status'], r['recurrence'], r['cases']) == ('recurring', 4, 3)
    assert [x['report_id'] for x in r['links']] == [2, 3, 4] and r['links'][0]['source'] == 'review'
    assert r['refs'] == 'US_STK_SGOV'
    check_promotion_gate(0.3, r['cases'])  # passes: 3 validated cases
    conn = duckdb.connect(db_path, read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0] == 1  # no near-copies
    conn.close()


def test_tickers_and_codes_resolve_to_registry_ids(db_path):
    conn = duckdb.connect(db_path)
    conn.execute("INSERT INTO asset_registry (canonical_id, display_name) VALUES "
                 "('US_STK_BRK-B', 'US_STK_BRK-B'), ('CN_FUND_110020', '易方达沪深300ETF联接A'), "
                 "('RSU_AMZN', 'Amazon RSU'), ('US_STK_AMZN', 'AMAZON.COM INC')")
    assert resolve_assets(conn, ['ISHARES 0-3 MONTH TREASURY BOND ETF (SGOV)', 'Amazon RSU (AMZN)', 'X（110020）']) == [
        'US_STK_SGOV', 'RSU_AMZN', 'CN_FUND_110020']
    assert resolve_assets(conn, ['SGOV', 'brk-b', '110020', 'AMZN', '纸黄金', 'Amazon RSU', '_', '%', 'Nope']) == [
        'US_STK_SGOV', 'US_STK_BRK-B', 'CN_FUND_110020', 'RSU_AMZN', 'US_STK_AMZN', 'ALTS_Paper_Gold']
    conn.close()


def test_the_creating_review_is_not_its_own_case_and_unknown_ids_create_new(db_path):
    target = insert(db_path, 'Old rule', report_id=2)
    gone = insert(db_path, 'Merged away', report_id=1, status='deprecated')
    ReviewGenerator().extract_insights(review({'text': 'Same idea', 'reinforces': [target]},
                                              {'text': 'Fresh idea', 'reinforces': [999, gone],
                                               'assets': ['纸黄金']}), 2, db_path)
    assert row(db_path, target)['cases'] == 0
    conn = duckdb.connect(db_path, read_only=True)
    fresh = conn.execute("SELECT status, source_report_id, entity_refs FROM ai_insights "
                         "WHERE title = 'Fresh idea'").fetchone()
    conn.close()
    assert fresh == ('raw', 2, 'ALTS_Paper_Gold')


def test_same_title_from_another_review_is_a_reinforcement(db_path):
    target = insert(db_path, '及时止损是关键', report_id=1, category='process')
    gen = ReviewGenerator()
    gen.extract_insights(review('及时止损是关键', section='lessons_learned', key='lessons'), 2, db_path)
    gen.extract_insights(review('及时止损是关键', section='lessons_learned', key='lessons'), None, db_path)
    r = row(db_path, target)
    assert (r['recurrence'], r['cases'], r['status']) == (2, 1, 'recurring')


def test_deleting_a_review_takes_its_cases_back(db_path):
    target = insert(db_path, 'Rule', report_id=1)
    gen = ReviewGenerator()
    for rid in (2, 3):
        gen.extract_insights(review({'text': 'again', 'reinforces': [target]}), rid, db_path)
    conn = duckdb.connect(db_path)
    assert reverse_review(conn, 2) == 1
    conn.close()
    r = row(db_path, target)
    assert (r['recurrence'], r['cases'], [x['report_id'] for x in r['links']]) == (2, 1, [3])
    assert r['status'] == 'recurring'  # review 3 still repeats it
    conn = duckdb.connect(db_path)
    reverse_review(conn, 3)
    conn.close()
    assert (row(db_path, target)['status'], row(db_path, target)['recurrence']) == ('raw', 1)


def test_merge_group_carries_each_review_once(db_path):
    primary = insert(db_path, 'SGOV reserve', report_id=1, status='principle')
    a = insert(db_path, 'SGOV ring-fence', report_id=2, tags='sgov')
    b = insert(db_path, 'Do not raid SGOV', report_id=2, entity_refs='US_STK_SGOV')
    c = insert(db_path, 'Physical separation of reserve', report_id=3,
               validated_case_links=json.dumps([{'link': 'memo 12', 'note': None, 'added_at': 'x'}]),
               validated_cases=1)
    conn = duckdb.connect(db_path)
    with pytest.raises(ValueError):
        merge_group(conn, primary, [primary])
    assert merge_group(conn, primary, [a, b, c], title='Keep 70% of SGOV for SPX 6300; never raid it') == 3
    with pytest.raises(ValueError, match='already merged'):
        merge_group(conn, primary, [a])
    with pytest.raises(LookupError):
        merge_group(conn, 999, [a])
    statuses = [s for (s,) in conn.execute(
        "SELECT status FROM ai_insights WHERE id IN (?, ?, ?) ORDER BY id", [a, b, c]).fetchall()]
    tags, title, merged = conn.execute(
        "SELECT tags, title, merged_from FROM ai_insights WHERE id = ?", [primary]).fetchone()
    conn.close()
    merged = json.loads(merged)
    assert title == 'Keep 70% of SGOV for SPX 6300; never raid it'
    assert [(e['id'], e['title'], e.get('replaced_wording', False)) for e in merged] == [
        (primary, 'SGOV reserve', True), (a, 'SGOV ring-fence', False),
        (b, 'Do not raid SGOV', False), (c, 'Physical separation of reserve', False)]
    r = row(db_path, primary)
    assert statuses == ['deprecated'] * 3
    assert (r['status'], r['recurrence'], r['cases'], r['refs'], tags) == ('principle', 3, 3, 'US_STK_SGOV', 'sgov')


def test_model_groups_are_checked_against_the_library(db_path):
    keep = insert(db_path, 'SGOV reserve', report_id=1, status='validated')
    newer = insert(db_path, 'SGOV ring-fence', report_id=2)
    other = insert(db_path, 'Out-of-competence cap', report_id=3)
    third = insert(db_path, 'Stop-loss for out-of-competence assets', report_id=4)
    gone = insert(db_path, 'Deprecated', report_id=4, status='deprecated')
    conn = duckdb.connect(db_path)
    groups = build_groups(conn, {'groups': [
        {'theme': 'SGOV 储备', 'rule': ' Keep  the SGOV reserve ', 'ids': [newer, keep, 999]},
        {'theme': 'dup', 'ids': [keep, other]},          # keep already used → one id left → dropped
        {'theme': '能力圈外', 'ids': [other, third, gone]},
        'junk']})
    conn.close()
    assert [(g['theme'], g['primary_id'], [m['id'] for m in g['members']]) for g in groups] == [
        ('SGOV 储备', keep, [keep, newer]), ('能力圈外', other, [other, third])]
    assert groups[0]['cases_after_merge'] == 1 and not groups[0]['promotable_after_merge']
    assert groups[0]['members'][1]['report_date'] == '2026-05-04'
    assert groups[0]['merged_title'] == 'Keep the SGOV reserve'
    assert groups[1]['merged_title'] == 'Out-of-competence cap'  # no rule given: the kept wording


def test_similar_groups_uses_the_model_answer(db_path):
    ids = [insert(db_path, f'rule {i}', report_id=i) for i in (1, 2, 3, 4)]

    class Fake:
        def complete(self, **kwargs):
            assert '#%d [raw/strategy] rule 1' % ids[0] in kwargs['user_prompt']
            duckdb.connect(db_path).close()  # the LLM client logs usage here: nothing may hold the file
            return SimpleNamespace(success=True, content_json={'groups': [{'theme': 't', 'ids': ids}]},
                                   model_used='fake', error=None)

    result = similar_groups(lambda: duckdb.connect(db_path, read_only=True), 'en', client=Fake())
    assert result['considered'] == 4 and result['model_used'] == 'fake'
    assert result['groups'][0]['cases_after_merge'] == 3 and result['groups'][0]['promotable_after_merge']


def test_library_block_reaches_the_review_prompt(db_path):
    insert(db_path, 'Newest raw', report_id=4)
    insert(db_path, 'A principle', report_id=1, status='principle')
    insert(db_path, 'Gone', report_id=1, status='deprecated')
    conn = duckdb.connect(db_path, read_only=True)
    block = format_insight_library(conn, 'en')
    conn.close()
    lines = block.splitlines()
    assert lines[0].startswith('## Insight library') and 'Gone' not in block
    assert lines[2].endswith('[principle] A principle') and lines[3].endswith('[raw] Newest raw')
    prompt = build_review_prompt_text('ctx', '2026-10-01', '2026-10-31', [], None, 'en', insights_text=block)
    assert block in prompt


def test_v206_resets_inflated_counts_and_keeps_the_old_values(tmp_path):
    from src.database.connector import DatabaseConnector

    conn = duckdb.connect()
    conn.execute("CREATE TABLE ai_insights (id INTEGER, title VARCHAR, category VARCHAR, status VARCHAR, "
                 "source_report_id INTEGER, recurrence_count INTEGER, updated_at TIMESTAMP)")
    conn.execute("""INSERT INTO ai_insights VALUES
        (1, '及时止损是关键', 'process', 'recurring', 7, 165, NULL),
        (2, '及时止损是关键', 'process', 'deprecated', 7, 1, NULL),
        (3, '及时止损是关键', 'process', 'deprecated', 11, 1, NULL),
        (4, '及时止损是关键', 'process', 'deprecated', 11, 1, NULL),
        (5, 'honest count', 'strategy', 'recurring', 20, 2, NULL),
        (6, 'honest count', 'strategy', 'deprecated', 21, 1, NULL)""")
    sql = Path('src/database/migrations/206_insight_count_reset.sql').read_text()
    body = "\n".join(x for x in sql.splitlines() if not x.lstrip().startswith('--'))
    for stmt in [s.strip() for s in body.split(';') if s.strip()]:
        conn.execute(stmt)
    assert conn.execute("SELECT id, recurrence_count FROM ai_insights WHERE id IN (1, 5) ORDER BY id"
                        ).fetchall() == [(1, 2), (5, 2)]
    assert conn.execute("SELECT insight_id, old_recurrence_count, new_recurrence_count "
                        "FROM ai_insight_count_resets").fetchall() == [(1, 165, 2)]
    with DatabaseConnector(str(tmp_path / 'fresh.duckdb')) as db:  # the runner applies it on a fresh DB
        db.execute(Path('src/database/schema.sql').read_text())
        db.run_migrations()
        assert db.execute("SELECT 1 FROM schema_version WHERE version = 206").fetchone()


@pytest.fixture
def client(db_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.dependencies import get_db, get_writable_db
    from src.api.routes import ai_advisor as routes
    from src.database.connector import DatabaseConnector

    def temp_db():
        with DatabaseConnector(db_path) as db:
            yield db

    monkeypatch.setattr(routes, "_DB_PATH", Path(db_path))  # never the real DB
    monkeypatch.setenv("UIS_DB_PATH", db_path)  # the env path wins over _DB_PATH
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = app.dependency_overrides[get_writable_db] = temp_db
    return TestClient(app)


def test_merging_without_new_wording_keeps_the_title_and_nests_earlier_merges(db_path):
    keep = insert(db_path, 'Rule A', report_id=1)
    mid = insert(db_path, 'Rule A again', report_id=2)
    old = insert(db_path, 'Rule A first copy', report_id=3)
    conn = duckdb.connect(db_path)
    merge_group(conn, mid, [old])
    merge_group(conn, keep, [mid], title='  Rule A ')
    title, merged = conn.execute("SELECT title, merged_from FROM ai_insights WHERE id = ?", [keep]).fetchone()
    conn.close()
    assert title == 'Rule A'
    assert [e['id'] for e in json.loads(merged)] == [mid, old]


def test_merge_group_route(client, db_path):
    primary = insert(db_path, 'SGOV reserve', report_id=1)
    members = [insert(db_path, f'SGOV variant {rid}', report_id=rid) for rid in (2, 3, 4)]
    assert client.post('/ai-advisor/insights/999/merge-group', json={'member_ids': members}).status_code == 404
    assert client.post(f'/ai-advisor/insights/{primary}/merge-group',
                       json={'member_ids': [primary]}).status_code == 422
    body = client.post(f'/ai-advisor/insights/{primary}/merge-group',
                       json={'member_ids': members, 'title': 'SGOV reserve, combined'}).json()
    assert body['title'] == 'SGOV reserve, combined' and len(json.loads(body['merged_from'])) == 4
    assert (body['cases_added'], body['validated_cases'], body['promote_eligible'], body['status']) == (
        3, 3, True, 'recurring')
    listed = client.get('/ai-advisor/insights').json()
    assert [i['id'] for i in listed] == [primary]


def test_similar_groups_route(client, db_path, monkeypatch):
    from src.api.routes import ai_advisor as routes

    ids = [insert(db_path, f'rule {i}', report_id=i) for i in (1, 2)]

    class Fake:
        def complete(self, **kwargs):
            return SimpleNamespace(success=True, content_json={'groups': [{'theme': 't', 'ids': ids}]},
                                   model_used='fake', error=None)

    class Broken:
        def complete(self, **kwargs):
            raise RuntimeError('provider down')

    monkeypatch.setattr(routes, 'llm_keys_configured', lambda: True)
    monkeypatch.setattr('src.services.llm_client.LLMClient', Fake)
    body = client.post('/ai-advisor/insights/similar-groups').json()
    assert body['groups'][0]['primary_id'] == ids[0] and body['considered'] == 2
    monkeypatch.setattr('src.services.llm_client.LLMClient', Broken)
    failed = client.post('/ai-advisor/insights/similar-groups')
    assert failed.status_code == 502 and failed.json()['error']['code'] == 'ERR_INSIGHT_GROUPS_LLM'


def test_deleting_a_review_through_the_route_reverses_its_cases(client, db_path):
    target = insert(db_path, 'Rule', report_id=1, status='validated')
    ReviewGenerator().extract_insights(review({'text': 'again', 'reinforces': [target]}), 2, db_path)
    assert row(db_path, target)['cases'] == 1
    assert client.delete('/ai-advisor/review/2').status_code == 204
    assert (row(db_path, target)['cases'], row(db_path, target)['recurrence']) == (0, 1)
