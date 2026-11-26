import json
from contextvars import ContextVar
import logging
from functools import partial
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator
from src.plugins import (
    PluginExtension,
    PluginRankingBoard,
    PluginRankingSource,
    PluginRegistration,
    RANKING_SOURCE_EXTENSION_KEY,
)
from src.scheduler.contracts import JobDefinition

from .source import BOARDS, MIN_ITEMS, fetch, fetch_awarded

M = json.loads(Path(__file__).with_name('manifest.json').read_text('utf-8'))
SOURCE = 'javranking_cc'


class SingleBoard(BaseModel):
    model_config = ConfigDict(extra='forbid')
    board_key: str

    @field_validator('board_key')
    @classmethod
    def known_board(cls, key):
        if key not in BOARDS:
            raise ValueError('有效 board_key: ' + ', '.join(BOARDS))
        return key


def register(context):
    # The SDK synchronously invokes the registered fetch callback from sync_ranking_board.
    # Keep this run's validated list isolated from other threads and runs.
    snapshot = ContextVar('javranking_snapshot', default=None)

    def fetch_checked(key, period):
        current = snapshot.get()
        if current is not None and current[:2] == (key, period):
            return list(current[2])
        if key == 'awarded':
            try:
                cache_path = context.data_dir / 'awarded-numbers.json'
            except OSError as exc:
                logging.getLogger(__name__).warning('缓存目录不可用，本次仅使用内存：%s', exc)
                cache_path = None
            numbers = fetch_awarded(cache_path)
        else:
            numbers = fetch(key, period)
        # Fail closed on a truncated-but-well-formed response before the host
        # replaces old rows. Site boards have different catalogue sizes.
        minimum = MIN_ITEMS[key]
        if len(numbers) < minimum:
            raise RuntimeError(
                f'{BOARDS[key][0]} 仅抓到 {len(numbers)} 个番号（至少 {minimum} 个），拒绝覆盖已有榜单'
            )

        return numbers

    def sync_one(reporter, params):
        key = SingleBoard.model_validate(params).board_key
        period = 'all'
        reporter.emit(text='抓取 ' + BOARDS[key][0])
        numbers = fetch_checked(key, period)

        # Avoid replacing existing rankings if none of the candidates can resolve.
        probes = list(dict.fromkeys(numbers[i] for i in
                      (0, 1, len(numbers) // 4, len(numbers) // 2, len(numbers) - 1)))
        if not context.movies.find_by_numbers(probes):
            failures = []
            for number in probes:
                try:
                    context.import_movie_by_number(number)
                except PermissionError as exc:
                    raise RuntimeError('元数据源目录权限不足，保留旧榜单') from exc
                except Exception as exc:
                    failures.append(f'{number}: {type(exc).__name__}')
                else:
                    break
            else:
                raise RuntimeError('候选影片均未解析，保留旧榜单；检查元数据源：' + ', '.join(failures))

        # Sakura 客户端对每个榜单都会携带 period；固定榜统一使用 all。
        token = snapshot.set((key, period, tuple(numbers)))
        try:
            result = context.sync_ranking_board(SOURCE, key, period=period)
        finally:
            snapshot.reset(token)
        reporter.emit(text=str(result))
        return result

    def sync_all(reporter, params):
        results, errors = {}, []
        for key in BOARDS:
            try:
                results[key] = sync_one(reporter, {'board_key': key})
            except Exception as exc:
                errors.append(f'{key}: {exc}')
        if errors:
            raise RuntimeError('; '.join(errors))
        return results

    boards = tuple(PluginRankingBoard(
        key=k, name=name, supported_periods=('all',), default_period='all',
        fetch_numbers=partial(fetch_checked, k),
    ) for k, (name, _) in BOARDS.items())
    source = PluginRankingSource(source_key=SOURCE, name='JavRanking', boards=boards)
    return PluginRegistration(plugin_id=M['plugin_id'], version=M['version'],
        host_api_version=M['host_api_version'], display_name=M['display_name'],
        extensions=(PluginExtension(key=RANKING_SOURCE_EXTENSION_KEY, data=source),),
        jobs=(JobDefinition(task_key='javranking_weekly', log_name='javranking-weekly',
                cli_name='javranking-weekly', cli_help='同步 JavRanking 全部四个榜单',
                default_cron='20 4 * * 1', handler=sync_all),
              JobDefinition(task_key='javranking_board', log_name='javranking-board',
                cli_name='javranking-board', cli_help='同步 JavRanking 指定榜单',
                manual_only=True, params_schema=SingleBoard, handler=sync_one)))
