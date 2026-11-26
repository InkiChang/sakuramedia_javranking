"""Read public ranking metadata, without fetching images or media."""
import json
import logging
import ssl
from pathlib import Path
import re
import time
from html.parser import HTMLParser
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


SITE = 'https://javranking.cc/zh-hans/'
BASE = SITE + 'rankings/'
AWARDED = 'most-awarded-videos'
TOP_COUNT = 100
AWARDED_LINK = re.compile(r'^- \[.+\]\(' + re.escape(SITE) + r'videos/([0-9]{1,12})/\)\s*$')
AWARDED_CODE = re.compile(r'[A-Z0-9][A-Z0-9._+ -]{0,63}')
LIMIT = 2 * 1024 * 1024
UA = 'SakuraMedia-JavRanking/1.0'
# Conservative lower bounds based on the public catalogue. These fail closed on
# a partial response while allowing DMM boards (which are shorter than TOP250).
MIN_ITEMS = {
    'dmm_weekly': 70,
    'weekly_hot': 200,
    'javlibrary': 200,
    'awarded': TOP_COUNT,
}
# Local declarations: registration and UI discovery never depend on the network.
BOARDS = {
    'dmm_weekly': ('DMM 本周热销', 'dmm-weekly'),
    'weekly_hot': ('JavRanking 本周热播', 'javranking-hottest-top250-weekly'),
    'javlibrary': ('JavLibrary TOP250', 'javlibrary-top250'),
    'awarded': ('全站神作总榜 TOP 100', AWARDED),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TransientDownloadError(OSError):
    pass


def download(url, accept):
    for attempt in range(3):
        try:
            return _download_once(url, accept)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            transient = isinstance(reason, (TimeoutError, ConnectionResetError,
                                           ssl.SSLEOFError, TransientDownloadError))
            if isinstance(exc, HTTPError):
                transient = exc.code in (502, 503, 504)
            if not transient or attempt == 2:
                raise RuntimeError(f'JavRanking 请求失败 {url}: {exc}') from exc
            time.sleep(2 ** attempt)


def _download_once(url, accept):
    curl = shutil.which('curl')
    try:
        if curl:
            # Stream stdout and enforce LIMIT while receiving. curl's
            # --max-filesize depends on Content-Length and is not a hard cap for
            # chunked/unknown-length responses.
            with tempfile.TemporaryFile() as error_output:
                proc = subprocess.Popen(
                    [curl, '-q', '--fail', '--silent', '--show-error',
                     '--max-time', '25', '--user-agent', UA,
                     '-H', f'Accept: {accept}', url],
                    stdout=subprocess.PIPE, stderr=error_output,
                )
                chunks = []
                size = 0
                try:
                    assert proc.stdout is not None
                    while True:
                        chunk = proc.stdout.read(min(64 * 1024, LIMIT + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > LIMIT:
                            proc.kill()
                            raise ValueError('响应超过 2 MiB 上限')
                    return_code = proc.wait(timeout=30)
                except Exception:
                    proc.kill()
                    proc.wait()
                    raise
                if return_code:
                    error_output.seek(0)
                    detail = error_output.read(1024).decode(errors='replace').strip()
                    if return_code in (28, 52, 55, 56):
                        raise TransientDownloadError(detail or f'curl {return_code}')
                    raise OSError(detail or f'curl 请求失败（退出码 {return_code}）')
            raw = b''.join(chunks)
        else:
            req = Request(url, headers={'User-Agent': UA, 'Accept': accept})
            with build_opener(NoRedirect()).open(req, timeout=25) as r:
                raw = r.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('响应过大')
        return raw.decode('utf-8-sig')
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('curl 请求超时') from exc


def parse_table(doc, slug):
    lines = doc.splitlines()
    if 'Canonical HTML: ' + BASE + slug + '/' not in lines:
        raise ValueError(f'{slug}: 未收到该榜的 Markdown 页面')
    header = next((i for i, line in enumerate(lines) if
                   [c.strip() for c in line.strip('| ').split('|')][:2] == ['Rank', 'Code']), None)
    if header is None or header + 1 >= len(lines) or not re.match(r'^\|\s*:?-+:?\s*\|', lines[header+1]):
        raise ValueError(f'{slug}: 未找到 Rank / Code 榜单表')
    rows = []
    skipped = 0
    for line in lines[header+2:]:
        if not line.strip():
            break
        cells = line.strip().split('|', 3)
        if len(cells) != 4 or cells[0] or not cells[1].strip().isascii() or not cells[1].strip().isdigit() or not cells[3].strip().endswith('|'):
            raise ValueError(f'{slug}: 榜单行格式变化')
        rank, code = int(cells[1]), cells[2].strip().upper()
        if rank < 1:
            raise ValueError(f'{slug}: 非法名次')
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9._+ -]{0,63}', code) or not any(c.isdigit() for c in code):
            # Some DMM products have a descriptive name instead of an identifier.
            skipped += 1
            continue
        rows.append((rank, code))
    if not rows:
        raise ValueError(f'{slug}: 榜单为空，取消更新')
    if skipped * 10 > len(rows) + skipped:
        raise ValueError(f'{slug}: 无效番号超过一成，取消更新')
    return list(dict.fromkeys(code for _, code in sorted(rows, key=lambda row: row[0])))


class VideoCodeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = None
        self.codes = []

    def handle_starttag(self, tag, attrs):
        if tag == 'p' and 'video-code' in (dict(attrs).get('class') or '').split():
            self.capture = []

    def handle_data(self, data):
        if self.capture is not None:
            self.capture.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self.capture is not None:
            self.codes.append(''.join(self.capture).strip().upper())
            self.capture = None


def valid_code(code):
    return isinstance(code, str) and AWARDED_CODE.fullmatch(code) and any(c.isdigit() for c in code)


def parse_awarded_ids(doc):
    lines = doc.splitlines()
    if f'Canonical HTML: {SITE}{AWARDED}/' not in lines:
        raise ValueError('未收到全站神作总榜的 Markdown 页面')
    ids = [m[1] for line in lines if (m := AWARDED_LINK.fullmatch(line))]
    if len(ids) != TOP_COUNT or len(set(ids)) != TOP_COUNT:
        raise ValueError(f'神作榜链接数量异常（{len(ids)} 条），保留旧榜')
    return ids


def fetch_awarded(cache_path):
    ids = parse_awarded_ids(download(f'{SITE}{AWARDED}.md', 'text/markdown'))
    cache = {}
    if cache_path is not None:
        try:
            saved = json.loads(cache_path.read_text('utf-8'))
            if isinstance(saved, dict):
                cache = {key: saved[key] for key in ids if key in saved and valid_code(saved[key])}
        except (FileNotFoundError, ValueError):
            pass
        except OSError as exc:
            logging.getLogger(__name__).warning('无法读取番号缓存，本次使用内存：%s', exc)
            cache_path = None
    for key in ids:
        if key in cache:
            continue
        parser = VideoCodeParser()
        parser.feed(download(f'{SITE}videos/{key}/', 'text/html'))
        parser.close()
        if len(parser.codes) != 1 or not valid_code(parser.codes[0]):
            raise ValueError(f'神作榜影片 {key} 缺少唯一有效番号，保留旧榜')
        cache[key] = parser.codes[0]
        if cache_path is not None:
            # Checkpoint resolved IDs, so a transient error does not force a full restart.
            try:
                with tempfile.TemporaryDirectory(dir=cache_path.parent) as tmp:
                    pending = Path(tmp) / 'numbers.json'
                    pending.write_text(json.dumps(cache), encoding='utf-8')
                    pending.replace(cache_path)
            except OSError as exc:
                logging.getLogger(__name__).warning('无法写入番号缓存，本次使用内存：%s', exc)
                cache_path = None
        time.sleep(0.35)
    numbers = [cache[key] for key in ids]
    if len(set(numbers)) != TOP_COUNT:
        raise ValueError('神作榜番号有重复，保留旧榜')
    return numbers


def fetch(board_key, period=''):
    _, slug = BOARDS[board_key]
    return parse_table(download(BASE + slug + '.md', 'text/markdown'), slug)
