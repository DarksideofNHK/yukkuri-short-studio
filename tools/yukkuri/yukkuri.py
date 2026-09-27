#!/usr/bin/python3
"""Local AquesTalkPlayer CLI and HTTP adapter (Python 3.9+, standard library)."""
import argparse
import csv
import hashlib
import re
import contextlib
import fcntl
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
ENGINE = Path('/Applications/AquesTalkPlayer.app/Contents/MacOS/AquesTalkPlayer')
VOICES = {'reimu': 'れいむ', 'marisa': 'まりさ', 'koishi': 'こいし', 'satori': 'さとり', 'reimu-fast': 'れいむ速', 'marisa-fast': 'まりさ速'}
PORT = 8767
MAX_TEXT = 4000
MAX_BODY = 32768

from features import (VoiceError, FAST, PARAMS, check_speed, atomic_json, speed_preset,
                      validate_readings, load_readings, apply_readings, kana_preview,
                      phonetic_preview, trim_wav)


def runtime():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.chmod(0o700)


@contextlib.contextmanager
def lock(name, wait=65):
    runtime()
    with (RUNTIME / name).open('a') as f:
        until = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise VoiceError('処理中です。少し待って再実行してください。')
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def token():
    runtime()
    p = RUNTIME / 'token'
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(32))
    value = p.read_text().strip()
    if not value:
        raise VoiceError('APIトークンファイルが空です。')
    return value


def validate(text, voice, preset=None):
    if not isinstance(text, str) or not text.strip():
        raise VoiceError('text に空でない文章を指定してください。')
    if len(text) > MAX_TEXT:
        raise VoiceError('文章は4000文字以内に分割してください。')
    if '\x00' in text:
        raise VoiceError('NULL文字は使用できません。')
    if preset is not None:
        if not isinstance(preset, str) or not preset.strip() or len(preset) > 100:
            raise VoiceError('preset は1〜100文字で指定してください。')
        return preset
    if not isinstance(voice, str):
        raise VoiceError('voice は文字列で指定してください。')
    if voice in VOICES:
        return VOICES[voice]
    if voice in VOICES.values():
        return voice
    raise VoiceError('voice は reimu / marisa / koishi / satori（または日本語名）です。')


def wav_info(data):
    with wave.open(io.BytesIO(data), 'rb') as w:
        if w.getnframes() == 0:
            raise VoiceError('空のWAVが返されました。')
        return {'sample_rate': w.getframerate(), 'channels': w.getnchannels(),
                'bits': w.getsampwidth() * 8,
                'duration_seconds': round(w.getnframes() / w.getframerate(), 3),
                'bytes': len(data)}


def describe():
    """Machine-readable discovery for agents that can execute local commands."""
    return {
        'service': 'yukkuri-local', 'interface_version': '1.0',
        'engine': 'AquesTalkPlayer (installed separately)',
        'cli': 'yukkuri（install.sh が ~/.local/bin/yukkuri に入れる）／ python3 ' + str(ROOT / 'yukkuri.py'),
        'guide': str(ROOT / 'AIからの呼び出しガイド.md'),
        'voices': VOICES,
        'speed': {'type': 'integer', 'minimum': 50, 'maximum': 300,
                  'omitted': 'Use selected preset; fast aliases use 180.'},
        'text': {'max_characters': MAX_TEXT, 'encoding': 'UTF-8',
                 'stdin': ['--file', '-']},
        'audio': {'format': 'WAV', 'sample_rate': 48000, 'channels': 1, 'bits': 16},
        'commands': {
            'say': {
                'argv_example': ['say', '--file', '-', '--voice', 'marisa',
                                 '--speed', '180', '--trim', '--output', '/absolute/path/voice.wav'],
                'stdout': 'JSON: output (absolute path), duration_seconds, sample_rate, channels, bits, bytes',
                'requires_server': False,
            },
            'batch': {
                'argv_example': ['batch', '/absolute/path/script.tsv', '--outdir',
                                 '/absolute/path/audio', '--speed', '180', '--trim'],
                'tsv_columns': ['番号', '声', 'セリフ', '速度 (optional)'],
                'stdout': 'JSON: manifest (absolute path), count, total_duration_seconds',
                'checkpoint': 'manifest.json is saved after each completed row.',
                'resume': 'Repeat the same command with --resume; matching completed rows are reused.',
            },
            'kana': {
                'argv_example': ['kana', '--file', '-', '--json'],
                'stdout': 'JSON: kana, tokens, unknown, engine, matches_aquestalk_analysis, note',
                'limitation': 'MeCab/IPADIC reference reading, not the AquesTalk internal analysis.',
                'fixed_reading': 'Use --phonetic instead of --json; pass its stdout to say --file -.',
            },
        },
        'readings': {'options': ['--reading', '三郷=みさと'],
                     'repeatable': True, 'dictionary_option': '--reading-dict',
                     'dictionary_formats': ['JSON object', 'two-column TSV']},
        'execution': {
            'success_exit_code': 0, 'failure_exit_code': 1, 'usage_error_exit_code': 2,
            'interrupt_exit_code': 130, 'errors': 'Human-readable stderr, not JSON.',
            'progress': 'stderr', 'overwrite': 'Disabled unless --force is explicitly supplied.',
            'concurrency': 'Submit sequentially; synthesis is serialized.',
        },
        'http': {'base_url': 'http://127.0.0.1:8767', 'startup': ['start'],
                 'authentication': 'Bearer token obtained with yukkuri token; keep it private.',
                 'endpoints': {'GET /health': 'JSON', 'GET /voices': 'JSON',
                               'POST /synthesize': 'WAV bytes', 'POST /kana': 'JSON'},
                 'synthesize_fields': ['text', 'voice', 'preset', 'speed', 'trim', 'readings'],
                 'batch': 'Use the CLI batch command.'},
    }


def synthesize(text, voice='reimu', preset=None, speed=None, trim=False, readings=None):
    """Return 48 kHz, mono, PCM16 WAV bytes. No network or shell execution."""
    selected = validate(text, voice, preset)
    check_speed(speed)
    if type(trim) is not bool:
        raise VoiceError('trim はtrueまたはfalseです。')
    text = apply_readings(text, readings)
    validate(text, voice, preset)
    if not ENGINE.is_file():
        raise VoiceError('AquesTalkPlayerが /Applications にありません。')
    with lock('synthesis.lock'), tempfile.TemporaryDirectory(prefix='yukkuri-') as tmp:
        selected = speed_preset(selected, speed, RUNTIME)
        tmp = Path(tmp)
        source, raw, result = tmp/'input.txt', tmp/'raw.wav', tmp/'result.wav'
        source.write_text(text, encoding='utf-8')
        try:
            p = subprocess.run([str(ENGINE), '-P', selected, '-F', str(source), '-W', str(raw)],
                               capture_output=True, timeout=60)
            if p.returncode:
                hint = 'プリセット名を確認してください。' if p.returncode == 29 else '文章を短くし、読みや記号を確認してください。'
                raise VoiceError('AquesTalkPlayerエラー {}: {}'.format(p.returncode, hint))
            if not raw.is_file():
                raise VoiceError('音声ファイルが生成されませんでした。')
            p = subprocess.run(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16@48000',
                                '-c', '1', str(raw), str(result)], capture_output=True, timeout=20)
            if p.returncode:
                raise VoiceError('48kHz WAVへの変換に失敗しました。')
        except subprocess.TimeoutExpired:
            raise VoiceError('音声生成がタイムアウトしました。文章を短くしてください。')
        data = result.read_bytes()
        info = wav_info(data)
        if (info['sample_rate'], info['bits'], info['channels']) != (48000, 16, 1):
            raise VoiceError('生成された音声の形式が不正です。')
        return trim_wav(data) if trim else data


def save(data, path, force=False):
    dest = Path(path).expanduser().absolute()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.yukkuri-', dir=str(dest.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        if force:
            os.replace(temp, dest)
        else:
            try:
                os.link(temp, dest)
            except FileExistsError:
                raise VoiceError('出力先が既にあります。別名か --force を指定してください。')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(dest)


def api(path, payload=None, port=PORT):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:{}{}'.format(port, path), data=body,
                                 headers={'Authorization': 'Bearer '+token(), 'Content-Type': 'application/json'})
    # Do not send loopback requests via an environment-configured proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=150 if path == '/synthesize' else 3) as r:
        return r.read()


def health(port):
    try:
        return json.loads(api('/health', port=port))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def serve(port):
    access_token = token()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)
        def log_message(self, fmt, *args):
            # Do not log text, headers, tokens, or URLs from clients.
            pass
        def reply(self, status, value, content_type='application/json; charset=utf-8'):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
        def authorized(self):
            if self.headers.get('Origin'):
                self.reply(403, {'error': 'ブラウザのクロスオリジン呼び出しは許可していません。'})
                return False
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied.encode(), ('Bearer '+access_token).encode()):
                self.reply(401, {'error': 'Bearerトークンが必要です。'})
                return False
            return True
        def do_GET(self):
            if not self.authorized():
                return
            if self.path == '/health':
                self.reply(200, {'service': 'yukkuri-local', 'version': '2.0',
                                 'engine_available': ENGINE.is_file(), 'port': port})
            elif self.path == '/voices':
                self.reply(200, {'voices': VOICES})
            else:
                self.reply(404, {'error': 'endpoint not found'})
        def do_POST(self):
            if not self.authorized():
                return
            if self.path not in ('/synthesize', '/kana', '/shutdown'):
                self.reply(404, {'error': 'endpoint not found'})
                return
            if self.headers.get('Transfer-Encoding'):
                self.reply(400, {'error': 'Content-Lengthを指定してください。'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.reply(400, {'error': 'Content-Lengthが不正です。'})
                return
            if not 0 < length <= MAX_BODY:
                self.reply(413, {'error': 'JSON本文は1〜32768バイトです。'})
                return
            if self.headers.get_content_type() != 'application/json':
                self.reply(415, {'error': 'Content-Type: application/json を指定してください。'})
                return
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
                if self.path == '/shutdown':
                    self.reply(200, {'status': 'stopping'})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if set(data) - {'text', 'voice', 'preset', 'speed', 'trim', 'readings'}:
                    raise VoiceError('使用できる項目は text / voice / preset / speed / trim / readings です。')
                validate(data.get('text'), data.get('voice', 'reimu'), data.get('preset'))
                check_speed(data.get('speed'))
                validate_readings(data.get('readings'))
                if type(data.get('trim', False)) is not bool:
                    raise VoiceError('trim はtrueまたはfalseです。')
            except (ValueError, UnicodeError, VoiceError) as e:
                self.reply(400, {'error': str(e) or 'JSONオブジェクトを指定してください。'})
                return
            if not self.server.busy.acquire(blocking=False):
                self.reply(503, {'error': '音声生成中です。完了後に再実行してください。'})
                return
            try:
                if self.path == '/kana':
                    self.reply(200, kana_preview(data['text'], data.get('readings')))
                else:
                    wav = synthesize(data['text'], data.get('voice', 'reimu'), data.get('preset'),
                                     data.get('speed'), data.get('trim', False), data.get('readings'))
                    self.reply(200, wav, 'audio/wav')
            except VoiceError as e:
                self.reply(422, {'error': str(e)})
            except (ValueError, wave.Error, subprocess.TimeoutExpired):
                self.reply(422, {'error': '設定ファイルまたは読み解析処理を確認してください。'})
            except OSError:
                self.reply(500, {'error': '音声エンジンまたはファイル処理でエラーが発生しました。'})
            finally:
                self.server.busy.release()
    with lock('server-{}.lock'.format(port), wait=0):
        with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
            server.daemon_threads = False
            server.busy = threading.Lock()
            print('Yukkuri API: http://127.0.0.1:{}'.format(port), flush=True)
            server.serve_forever(poll_interval=0.2)


def add_options(parser):
    parser.add_argument('--speed', type=int, help='エンジンの話速50〜300。標準100、速め180')
    parser.add_argument('--trim', action='store_true', help='前後の無音だけを除去（10ms余白）')
    parser.add_argument('--reading', action='append', default=[], help='表記=読み。複数回指定可能')
    parser.add_argument('--reading-dict', help='読み辞書（JSONまたは2列TSV）')


def batch(args):
    check_speed(args.speed)
    readings = load_readings(args.reading_dict, args.reading)
    source = Path(args.script).expanduser().resolve()
    with source.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.reader(f, delimiter='\t') if r and any(r)]
    if not rows:
        raise VoiceError('台本が空です。')
    header = rows[0]
    aliases = {'番号':'id', '声':'voice', 'セリフ':'text', '速度':'speed', '話速':'speed'}
    columns = [aliases.get(x.strip(), x.strip()) for x in header]
    has_header = columns[:3] == ['id', 'voice', 'text']
    if has_header:
        if columns not in (['id','voice','text'], ['id','voice','text','speed']):
            raise VoiceError('TSVの見出しは「番号・声・セリフ・速度（任意）」の順です。')
        rows = rows[1:]
    if not rows:
        raise VoiceError('台本にセリフがありません。')
    plans, ids = [], set()
    presets = json.loads(PARAMS.read_text()) if PARAMS.is_file() else []
    for n, row in enumerate(rows, 2 if has_header else 1):
        if len(row) not in (3, 4):
            raise VoiceError('台本{}行目は3列または4列で指定してください。'.format(n))
        ident, voice, text = row[:3]
        ident, voice = ident.strip(), voice.strip()
        if not re.fullmatch(r'(?:L)?[0-9]{1,6}', ident):
            raise VoiceError('台本{}行目の番号は1、01、L01などです。'.format(n))
        ident = 'L{:02d}'.format(int(ident.lstrip('L')))
        if ident in ids:
            raise VoiceError('番号が重複しています: ' + ident)
        ids.add(ident)
        selected = validate(text, voice)
        speed = int(row[3]) if len(row) == 4 and row[3].strip() else args.speed
        check_speed(speed)
        prepared = apply_readings(text, readings)
        validate(prepared, voice)
        base_name = FAST.get(selected, selected)
        config = next((x for x in presets if x.get('name') == base_name), None)
        effective_speed = speed if speed is not None else (180 if selected in FAST else (config or {}).get('spd', 100))
        signature = {'id':ident, 'voice':voice, 'text':text, 'speed':speed,
                     'trim':args.trim, 'readings':readings, 'preset_config':config, 'adapter':'2.0'}
        request_hash = hashlib.sha256(json.dumps(signature,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        plans.append({'id':ident, 'voice':voice, 'preset':selected, 'text':text,
                      'prepared_text':prepared, 'speed':effective_speed, 'requested_speed':speed,
                      'trim':args.trim, 'file':'{}_{}.wav'.format(ident,selected),
                      'request_hash':request_hash, 'status':'pending'})
    outdir = Path(args.outdir).expanduser().resolve()
    manifest = outdir / 'manifest.json'
    outputs = {outdir/x['file'] for x in plans}
    if source in outputs or source == manifest:
        raise VoiceError('台本ファイルを出力先で上書きする配置は使用できません。')
    outdir.mkdir(parents=True, exist_ok=True)
    # Lock the output directory independently from the engine lock.
    lockname = 'batch-' + hashlib.sha256(str(outdir).encode()).hexdigest() + '.lock'
    with lock(lockname, wait=0):
        old = {}
        if manifest.exists():
            if not args.resume and not args.force:
                raise VoiceError('manifest.jsonが既にあります。--resume または別フォルダを指定してください。')
            if args.resume:
                previous = json.loads(manifest.read_text())
                old = {x['id']:x for x in previous.get('items', [])}
        elif args.resume:
            raise VoiceError('--resumeには既存のmanifest.jsonが必要です。')
        for item in plans:
            dest = outdir/item['file']
            if not dest.exists():
                continue
            previous = old.get(item['id'], {})
            if args.resume and previous.get('status') == 'done' and previous.get('request_hash') == item['request_hash']:
                audio = dest.read_bytes()
                if hashlib.sha256(audio).hexdigest() != previous.get('sha256'):
                    raise VoiceError('生成済み音声が変更されています: '+item['file'])
                wav_info(audio)
                item.update(previous)
                item['resumed'] = True
            elif not args.force:
                raise VoiceError('既存音声と台本・設定が一致しません: '+item['file'])
        state = {'version':'2.0','script':str(source),'outdir':str(outdir),
                 'status':'running','items':plans}
        def checkpoint():
            state['completed'] = sum(x['status']=='done' for x in plans)
            state['total_duration_seconds'] = round(sum(x.get('duration_seconds',0) for x in plans if x['status']=='done'),3)
            atomic_json(manifest,state)
        checkpoint()
        for index, item in enumerate(plans,1):
            if item['status'] == 'done':
                continue
            try:
                data = synthesize(item['text'], item['voice'], speed=item['requested_speed'],
                                  trim=args.trim, readings=readings)
                save(data, outdir/item['file'], force=args.force)
                item.update(wav_info(data), status='done', sha256=hashlib.sha256(data).hexdigest())
                checkpoint()
                print('[{}/{}] {} {:.3f}秒'.format(index,len(plans),item['file'],item['duration_seconds']), file=sys.stderr)
            except (VoiceError,OSError,ValueError,subprocess.TimeoutExpired) as e:
                item.update(status='error',error=str(e))
                state['status']='error'
                checkpoint()
                raise VoiceError('{}で停止しました。manifest.jsonを確認してください: {}'.format(item['id'],e))
        state['status']='complete'
        checkpoint()
        return {'manifest':str(manifest),'count':len(plans),'total_duration_seconds':state['total_duration_seconds']}


def main():
    parser = argparse.ArgumentParser(description='ゆっくりボイス CLI / このMac専用API')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('say', 'request'):
        p = sub.add_parser(name, help='WAV生成' if name == 'say' else 'HTTP API経由でWAV生成')
        src = p.add_mutually_exclusive_group(required=True)
        src.add_argument('--text', '-t')
        src.add_argument('--file', '-f', help='UTF-8ファイル。- で標準入力')
        p.add_argument('--voice', '-v', default='reimu')
        p.add_argument('--preset', help='GUIで登録したプリセット名（voiceより優先）')
        add_options(p)
        p.add_argument('--output', '-o', required=True)
        p.add_argument('--force', action='store_true', help='出力ファイルの上書きを許可')
        if name == 'request':
            p.add_argument('--port', type=int, default=PORT)
    p = sub.add_parser('batch', help='TSV台本からWAVとmanifest.jsonを生成')
    p.add_argument('script')
    p.add_argument('--outdir', required=True)
    add_options(p)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--resume', action='store_true')
    mode.add_argument('--force', action='store_true')
    p = sub.add_parser('kana', help='MeCabによる参考読み。エンジン内蔵辞書とは別です。')
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument('--text', '-t')
    src.add_argument('--file', '-f')
    p.add_argument('--reading', action='append', default=[])
    p.add_argument('--reading-dict')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--json', action='store_true')
    mode.add_argument('--phonetic', action='store_true', help='#>付きの読み固定用入力を返す')
    sub.add_parser('voices', help='対応する声の一覧')
    sub.add_parser('describe', help='AI向けに機能・入出力・呼び出し方をJSONで表示')
    sub.add_parser('token', help='ローカルAPI用Bearerトークンを表示')
    for name in ('serve', 'start', 'stop', 'status'):
        p = sub.add_parser(name)
        p.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()
    if hasattr(args, 'port') and not 1024 <= args.port <= 65535:
        parser.error('port は1024〜65535です。')
    try:
        if args.command in ('say', 'request'):
            if Path(args.output).expanduser().exists() and not args.force:
                raise VoiceError('出力先が既にあります。別名か --force を指定してください。')
            text = args.text if args.text is not None else (sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8-sig'))
            validate(text, args.voice, args.preset)
            readings = load_readings(args.reading_dict, args.reading)
            if args.command == 'say':
                data = synthesize(text, args.voice, args.preset, args.speed, args.trim, readings)
            else:
                body = {'text': text, 'voice': args.voice, 'speed': args.speed, 'trim': args.trim, 'readings': readings}
                if args.preset is not None:
                    body['preset'] = args.preset
                data = api('/synthesize', body, args.port)
            info = wav_info(data)
            info['output'] = save(data, args.output, args.force)
            print(json.dumps(info, ensure_ascii=False))
        elif args.command == 'batch':
            print(json.dumps(batch(args), ensure_ascii=False))
        elif args.command == 'kana':
            text = args.text if args.text is not None else (sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8-sig'))
            validate(text, 'reimu')
            result = kana_preview(text, load_readings(args.reading_dict, args.reading))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.phonetic:
                print(phonetic_preview(result))
            else:
                print(result['kana'])
                print('注: ' + result['note'], file=sys.stderr)
        elif args.command == 'voices':
            print(json.dumps(VOICES, ensure_ascii=False, indent=2))
        elif args.command == 'describe':
            print(json.dumps(describe(), ensure_ascii=False, indent=2))
        elif args.command == 'token':
            print(token())
        elif args.command == 'serve':
            serve(args.port)
        elif args.command == 'start':
            with lock('startup-{}.lock'.format(args.port), wait=10):
                if not health(args.port):
                    runtime()
                    with (RUNTIME/'server.log').open('ab') as log:
                        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve', '--port', str(args.port)],
                                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                    for _ in range(40):
                        if health(args.port):
                            break
                        if proc.poll() is not None:
                            raise VoiceError('APIを起動できません。ポート使用状況と .runtime/server.log を確認してください。')
                        time.sleep(0.1)
                    else:
                        raise VoiceError('APIの起動確認がタイムアウトしました。statusとログを確認してください。')
                print(json.dumps(health(args.port), ensure_ascii=False))
        elif args.command == 'status':
            state = health(args.port)
            print(json.dumps(state or {'status': 'stopped', 'port': args.port}, ensure_ascii=False))
            return 0 if state else 1
        elif args.command == 'stop':
            if not health(args.port):
                print('APIは起動していません。')
            else:
                print(api('/shutdown', {}, args.port).decode())
                for _ in range(50):
                    if not health(args.port):
                        break
                    time.sleep(0.1)
                else:
                    raise VoiceError('停止完了を確認できません。statusで再確認してください。')
        return 0
    except urllib.error.HTTPError as e:
        print('APIエラー {}: {}'.format(e.code, e.read().decode('utf-8', errors='replace')), file=sys.stderr)
    except (VoiceError, OSError, ValueError, wave.Error, urllib.error.URLError, subprocess.TimeoutExpired) as e:
        print('エラー: {}'.format(e), file=sys.stderr)
    except KeyboardInterrupt:
        return 130
    return 1

if __name__ == '__main__':
    sys.exit(main())
