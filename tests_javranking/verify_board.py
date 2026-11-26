"""Run inside an isolated Sakura test instance, with its disposable bootstrap user.

docker exec -i -u app TEST_APP python - RUN_ID BOARD < tests_javranking/verify_board.py
Prints only aggregate evidence; no credentials, URLs with signatures, or titles.
"""
import json
import sys
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from src.config.config import settings
from src.model import BackgroundTaskRun, RankingItem, init_database


def main():
    run_id, key = int(sys.argv[1]), sys.argv[2]
    source, period = 'javranking_cc', 'all'
    init_database(settings.database)
    run = BackgroundTaskRun.get_by_id(run_id)
    if run.state != 'completed':
        raise SystemExit(f'run {run_id} is {run.state}; no passing verdict')
    if run.task_key == 'javranking_board':
        summary = run.result_summary
    elif run.task_key == 'javranking_weekly':
        summary = run.result_summary[key]
    else:
        raise SystemExit('unexpected task key')
    assert (summary['source_key'], summary['board_key'], summary['period']) == (source, key, period)
    db_rows = list(RankingItem.select(RankingItem.rank, RankingItem.movie_number).where(
        (RankingItem.source_key == source) & (RankingItem.board_key == key) &
        (RankingItem.period == period)).order_by(RankingItem.rank).tuples())
    assert len(db_rows) == summary['stored_items'] > 0
    assert summary['fetched_numbers'] == summary['skipped_movies'] + summary['stored_items']
    opener = build_opener(ProxyHandler({}))
    base = 'http://127.0.0.1:8000'
    login = Request(base + '/auth/tokens', data=json.dumps({
        'username': settings.auth.username, 'password': settings.auth.password,
    }).encode(), headers={'Content-Type':'application/json'})
    with opener.open(login, timeout=10) as response:
        auth = {'Authorization':'Bearer ' + json.load(response)['access_token']}
    def get(path):
        with opener.open(Request(base + path, headers=auth), timeout=15) as response:
            return json.load(response)
    assert source in {s['source_key'] for s in get('/ranking-sources')}
    board = next(b for b in get(f'/ranking-sources/{source}/boards') if b['board_key'] == key)
    assert board['default_period'] == period and period in board['supported_periods']
    api_rows = []
    for page in range(1, (len(db_rows) + 23) // 24 + 1):
        query = urlencode({'period':period,'page':page,'page_size':24})
        data = get(f'/ranking-sources/{source}/boards/{key}/items?{query}')
        assert data['total'] == len(db_rows)
        api_rows.extend((item['rank'], item['movie_number']) for item in data['items'])
    assert db_rows == api_rows
    print(json.dumps(dict(run_id=run_id, result=summary, db_rows=len(db_rows),
                          api_rows=len(api_rows), pages=page, rank_and_number_match=True)))


if __name__ == '__main__':
    main()
