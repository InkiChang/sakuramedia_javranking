"""Run with SAKURA_BACKEND=/path/to/sakuramediabe python -m pytest tests_javranking."""
import importlib
import os
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def plugin(monkeypatch):
    backend = os.environ.get('SAKURA_BACKEND')
    if not backend:
        pytest.skip('Set SAKURA_BACKEND to test against Sakura Host API 18')
    monkeypatch.syspath_prepend(str(Path(backend).resolve()))
    # Load the real contracts without initializing the scheduler's runtime logging.
    if 'src.scheduler' not in sys.modules:
        scheduler = types.ModuleType('src.scheduler')
        scheduler.__path__ = [str(Path(backend).resolve() / 'src' / 'scheduler')]
        monkeypatch.setitem(sys.modules, 'src.scheduler', scheduler)
    return importlib.import_module('sakuramedia_javranking.plugin')


class Host:
    def __init__(self, plugin):
        self.data_dir = Path('/unused')
        self.movies = self
        self.imports = []
        self.calls = []
        self.registration = plugin.register(self)
        self.boards = {b.key: b for b in self.registration.extensions[0].data.boards}

    def find_by_numbers(self, numbers):
        return [numbers[0]]

    def import_movie_by_number(self, number):
        self.imports.append(number)
        raise RuntimeError('metadata unavailable')

    def sync_ranking_board(self, source, key, period):
        assert source == 'javranking_cc'
        self.calls.append((key, period, self.boards[key].fetch_numbers(period)))
        return {'stored_items': len(self.calls[-1][2])}

    def emit(self, **kwargs):
        pass


def test_scheduled_and_manual_full_sync(plugin, monkeypatch):
    downloads = []

    def fetch(key, period):
        downloads.append((key, period))
        return [f'AAA-{i:03}' for i in range(plugin.MIN_ITEMS[key])]

    monkeypatch.setattr(plugin, 'fetch', fetch)
    monkeypatch.setattr(plugin, 'fetch_awarded', lambda path: fetch('awarded', 'all'))
    host = Host(plugin)
    keys = ['dmm_weekly', 'weekly_hot', 'javlibrary', 'awarded']
    assert list(host.boards) == keys
    assert not downloads
    assert all(b.supported_periods == ('all',) and b.default_period == 'all'
               for b in host.boards.values())
    full, single = host.registration.jobs
    assert full.default_cron == '20 4 * * 1' and full.manual_trigger_allowed
    assert single.manual_only
    assert list(full.build_executor({})(host)) == keys
    assert downloads == [(key, 'all') for key in keys]
    assert [(key, period) for key, period, _ in host.calls] == downloads
    assert not host.imports
    host.boards[keys[0]].fetch_numbers('all')
    assert len(downloads) == len(keys) + 1  # snapshots are not shared across runs


def test_short_board_does_not_block_remaining_boards(plugin, monkeypatch):
    monkeypatch.setattr(plugin, 'fetch', lambda key, period: ['AAA-001'] if key == 'dmm_weekly'
                        else [f'AAA-{i:03}' for i in range(plugin.MIN_ITEMS[key])])
    monkeypatch.setattr(plugin, 'fetch_awarded', lambda path: plugin.fetch('awarded', 'all'))
    host = Host(plugin)
    with pytest.raises(RuntimeError, match='至少 70 个'):
        host.registration.jobs[0].build_executor({})(host)
    assert [key for key, _, _ in host.calls] == ['weekly_hot', 'javlibrary', 'awarded']


def test_metadata_probe_failure_preserves_board(plugin, monkeypatch):
    monkeypatch.setattr(plugin, 'fetch', lambda key, period: [f'AAA-{i:03}' for i in range(70)])
    host = Host(plugin)
    monkeypatch.setattr(host, 'find_by_numbers', lambda numbers: [])
    with pytest.raises(RuntimeError, match='保留旧榜单'):
        host.registration.jobs[1].build_executor({'board_key': 'dmm_weekly'})(host)
    assert host.imports == ['AAA-000', 'AAA-001', 'AAA-017', 'AAA-035', 'AAA-069']
    assert not host.calls


def test_removed_board_cannot_be_synced_manually(plugin):
    host = Host(plugin)
    with pytest.raises(ValueError, match='有效 board_key'):
        host.registration.jobs[1].build_executor({'board_key': 'ltx'})(host)
    assert not host.calls


def test_awarded_cache(plugin, monkeypatch, tmp_path):
    src = importlib.import_module('sakuramedia_javranking.source')
    cache = tmp_path / 'awarded.json'
    ids = list(range(1, 101))
    calls = []
    def download(url, accept):
        calls.append(url)
        if accept == 'text/markdown':
            return f'Canonical HTML: {src.SITE}{src.AWARDED}/\n' + '\n'.join(
                f'- [Name]({src.SITE}videos/{i}/)' for i in ids)
        return f'<p class="video-code">AAA-{int(url.rstrip("/").split("/")[-1]):03}</p>'
    monkeypatch.setattr(src, 'download', download)
    monkeypatch.setattr(src.time, 'sleep', lambda _: None)
    assert src.fetch_awarded(cache) == [f'AAA-{i:03}' for i in ids]
    assert len(calls) == 101
    ids[:] = [100, *range(1, 100)]
    assert src.fetch_awarded(cache)[0] == 'AAA-100'
    assert len(calls) == 102
    ids.pop()
    with pytest.raises(ValueError, match='链接数量异常'):
        src.fetch_awarded(cache)


def test_later_probe_succeeds(plugin, monkeypatch):
    host = Host(plugin)
    monkeypatch.setattr(host, 'find_by_numbers', lambda ns: [])
    monkeypatch.setattr(plugin, 'fetch', lambda k, p: [f'AAA-{i:03}' for i in range(70)])
    def probe(n):
        host.imports.append(n)
        if n.endswith('000'):
            raise RuntimeError('first title missing')
        return object()
    monkeypatch.setattr(host, 'import_movie_by_number', probe)
    result = host.registration.jobs[1].build_executor({'board_key':'dmm_weekly'})(host)
    assert result['stored_items'] == 70 and host.imports == ['AAA-000','AAA-001']


def test_unwritable_cache(plugin, monkeypatch, tmp_path, caplog):
    src = importlib.import_module('sakuramedia_javranking.source')
    def download(url, accept):
        if accept == 'text/markdown':
            return f'Canonical HTML: {src.SITE}{src.AWARDED}/\n' + '\n'.join(
                f'- [T]({src.SITE}videos/{i}/)' for i in range(100))
        return f'<p class="video-code">AAA-{url.split("/")[-2]}</p>'
    monkeypatch.setattr(src, 'download', download)
    monkeypatch.setattr(src.time, 'sleep', lambda _: None)
    def denied(**kwargs):
        raise PermissionError('read only')
    monkeypatch.setattr(src.tempfile, 'TemporaryDirectory', denied)
    assert len(src.fetch_awarded(tmp_path / 'cache')) == 100
    assert caplog.text.count('无法写入番号缓存') == 1


@pytest.mark.parametrize('kind,expected', [('eof',3), ('403',1), ('cert',1), ('oversize',1)])
def test_retry_policy(plugin, monkeypatch, kind, expected):
    src = importlib.import_module('sakuramedia_javranking.source')
    exc = {'eof': src.URLError(src.ssl.SSLEOFError('eof')),
           '403': src.HTTPError(src.BASE,403,'forbidden',{},None),
           'cert': src.URLError(src.ssl.SSLCertVerificationError('cert')),
           'oversize': ValueError('oversize')}[kind]
    calls, delays = [], []
    def once(*args):
        calls.append(args)
        if kind == 'eof' and len(calls) == 3:
            return 'OK'
        raise exc
    monkeypatch.setattr(src, '_download_once', once)
    monkeypatch.setattr(src.time, 'sleep', delays.append)
    if kind == 'eof':
        assert src.download(src.BASE, 'text/markdown') == 'OK'
    else:
        with pytest.raises(RuntimeError):
            src.download(src.BASE, 'text/markdown')
    assert len(calls) == expected
    assert delays == ([1, 2] if kind == 'eof' else [])
