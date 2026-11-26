"""Run inside the disposable test app, for one completed DMM-only run/log."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.config.config import settings
from src.model import BackgroundTaskRun, RankingItem, init_database


def reason(msg):
    s = msg.lower()
    for token, label in [('network is unreachable', 'network_unreachable'),
                         ('connection refused', 'connection_refused'), ('timed out', 'timeout'),
                         ('timeout', 'timeout'), ('permission denied', 'permission_denied'),
                         ('403', '403'), ('429', '429'), ('404', '404'), ('ssl', 'tls'),
                         ('not found', 'not_found'), ('未找到', 'not_found')]:
        if token in s:
            return label
    return 'other'


def main():
    init_database(settings.database)
    run = BackgroundTaskRun.get_by_id(int(sys.argv[1]))
    summary = run.result_summary
    assert run.state == 'completed' and summary['board_key'] == 'dmm_weekly'
    assert summary['source_key'] == 'javranking_cc' and summary['period'] == 'all'
    saved = {r.rank for r in RankingItem.select(RankingItem.rank).where(
        (RankingItem.source_key == 'javranking_cc') & (RankingItem.period == 'all') &
        (RankingItem.board_key == 'dmm_weekly'))}
    events = defaultdict(dict)
    missing = {}
    starts = 0
    with Path('/data/logs/javranking-board.log').open(errors='replace') as f:
        for line in f:
            if 'Scheduler task started' in line:
                starts += 1
            m = re.search(r'元数据插件失败 plugin=sakuramedia_(\w+)_metadata movie_number=(\S+) detail=(.*)',line)
            if m:
                events[m[2]][m[1]] = reason(m[3])
            m = re.search(r'(AVMOO|JavBus) metadata not found movie_number=(\S+)', line,re.I)
            if m:
                events[m[2]][m[1].lower()] = 'not_found'
            m = re.search(r'Ranking sync item skipped source_key=javranking_cc board_key=dmm_weekly period=all rank=(\d+) movie_number=(\S+) detail=(.*)',line)
            if m:
                rank = int(m[1]); assert rank not in missing
                missing[rank] = dict(javbus=events[m[2]].get('javbus','not_logged'),
                                     avmoo=events[m[2]].get('avmoo','not_logged'),
                                     final_detail=reason(m[3]))
    assert starts == 1, 'requires a clean single-run log'
    assert len(missing) == summary['skipped_movies'] and len(saved) == summary['stored_items']
    assert saved.isdisjoint(missing)
    assert saved.union(missing) == set(range(1,summary['fetched_numbers'] + 1))
    rows = [dict(rank=i, status='stored') if i in saved else dict(rank=i,status='skipped',**missing[i])
            for i in range(1, summary['fetched_numbers'] + 1)]
    counts = Counter(f"javbus={m['javbus']};avmoo={m['avmoo']};final={m['final_detail']}" for m in missing.values())
    print(json.dumps(dict(run=run.id, summary=summary, failed_combinations=counts, rows=rows),indent=2))


if __name__ == '__main__':
    main()
