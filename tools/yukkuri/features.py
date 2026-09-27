"""Local preset, pronunciation and PCM helpers. No private engine keys used."""
import array
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
import wave

class VoiceError(Exception):
    pass

PARAMS = Path.home() / 'Library/Application Support/AquesTalkPlayer/params.json'
import shutil as _shutil
# MeCab と IPA 辞書の場所は Homebrew の置き場所（Apple Silicon は /opt/homebrew、Intel は /usr/local）を探す。環境変数でも指定できる
MECAB = os.environ.get('YUKKURI_MECAB') or _shutil.which('mecab') or '/opt/homebrew/bin/mecab'
IPADIC = os.environ.get('YUKKURI_IPADIC') or next(
    (d for d in ('/opt/homebrew/lib/mecab/dic/ipadic', '/usr/local/lib/mecab/dic/ipadic') if Path(d).exists()),
    '/opt/homebrew/lib/mecab/dic/ipadic')
FAST = {'れいむ速': 'れいむ', 'まりさ速': 'まりさ'}


def check_speed(speed):
    if speed is not None and (type(speed) is not int or not 50 <= speed <= 300):
        raise VoiceError('speed は50〜300の整数です（標準100、速め180）。')


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.yukkuri-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def speed_preset(selected, speed, runtime):
    """Add an immutable speed variant; never modify the selected base preset."""
    check_speed(speed)
    if selected in FAST:
        selected = FAST[selected]
        if speed is None:
            speed = 180
    if speed is None:
        return selected
    if not PARAMS.is_file():
        raise VoiceError('アプリでプリセットを一度保存し、params.jsonを作成してください。')
    before = PARAMS.read_bytes()
    try:
        params = json.loads(before)
    except ValueError:
        raise VoiceError('アプリのparams.jsonが不正です。バックアップから復元してください。')
    if not isinstance(params, list) or not all(isinstance(p, dict) for p in params):
        raise VoiceError('アプリのプリセット保存形式を確認してください。')
    base = next((p for p in params if p.get('name') == selected), None)
    if base is None:
        raise VoiceError('プリセットが見つかりません: ' + selected)
    if base.get('spd') == speed:
        return selected
    variant = dict(base)
    variant['spd'] = speed
    digest = hashlib.sha256(json.dumps(variant, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    name = '__yukkuri_{}_{}'.format(speed, digest)
    variant.update(name=name, memo='yukkuri CLI: {} / 話速{}'.format(selected, speed))
    existing = next((p for p in params if p.get('name') == name), None)
    if existing == variant:
        return name
    if existing is not None:
        raise VoiceError('自動プリセット名が競合しています。')
    # A recovery copy of user presets is kept before the first adapter write.
    backup = Path(runtime) / 'params.before-speed.json'
    try:
        with backup.open('xb') as f:
            f.write(before)
    except FileExistsError:
        pass
    params.append(variant)
    if PARAMS.read_bytes() != before:
        raise VoiceError('GUIでプリセットが変更されました。保存後に再実行してください。')
    atomic_json(PARAMS, params)
    return name


def validate_readings(readings):
    if readings is None:
        return {}
    if not isinstance(readings, dict) or len(readings) > 500:
        raise VoiceError('readings は500語以内の「表記: 読み」オブジェクトです。')
    result = {}
    for source, target in readings.items():
        if not isinstance(source, str) or not source.strip() or len(source) > 100 or any(c in source for c in '\n\r\x00'):
            raise VoiceError('読み指定の表記が不正です。')
        if not isinstance(target, str) or not 1 <= len(target) <= 200:
            raise VoiceError('読みは1〜200文字のひらがな・カタカナで指定してください。')
        target = unicodedata.normalize('NFKC', target)
        if not re.fullmatch('[ぁ-ゖァ-ヺー]+', target):
            raise VoiceError('読みはひらがな・カタカナ・長音記号だけで指定してください。')
        result[source] = target
    return result


def load_readings(path=None, overrides=None):
    result = {}
    if path:
        p = Path(path).expanduser()
        if p.suffix.lower() == '.json':
            result = validate_readings(json.loads(p.read_text(encoding='utf-8-sig')))
        else:
            with p.open(encoding='utf-8-sig', newline='') as f:
                rows = csv.reader(f, delimiter='\t')
                for number, row in enumerate(rows, 1):
                    if not row or not any(row):
                        continue
                    if number == 1 and row in (['表記', '読み'], ['surface', 'reading']):
                        continue
                    if len(row) != 2 or row[0] in result:
                        raise VoiceError('読み辞書TSVの{}行目が不正または重複です。'.format(number))
                    result[row[0]] = row[1]
    for item in overrides or []:
        if '=' not in item:
            raise VoiceError('--reading は「三郷=みさと」の形式です。')
        k, v = item.split('=', 1)
        result[k] = v
    return validate_readings(result)


def reading_parts(text, readings):
    """Longest match wins; replacement is one pass and never recursive."""
    readings = validate_readings(readings)
    if not readings:
        return [(text, False)]
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(readings, key=len, reverse=True)))
    result, last = [], 0
    for match in pattern.finditer(text):
        result.append((text[last:match.start()], False))
        result.append((readings[match.group()], True))
        last = match.end()
    result.append((text[last:], False))
    return result


def katakana(text):
    return ''.join(chr(ord(c)+0x60) if 'ぁ' <= c <= 'ゖ' else c for c in text)


def apply_readings(text, readings):
    if readings and any(line.startswith('#>') for line in text.splitlines()):
        raise VoiceError('音声記号列（#>）と読み置換は併用できません。')
    # Katakana prevents the supplied name from being reparsed as another kanji name.
    return ''.join(katakana(part) if specified else part for part, specified in reading_parts(text, readings))


def kana_preview(text, readings=None):
    """MeCab reference reading. This is explicitly not AqKanji2Koe output."""
    tokens, unknown = [], []
    for part, specified in reading_parts(text, readings):
        if not part:
            continue
        if specified:
            tokens.append({'surface': part, 'reading': katakana(part), 'source': 'override'})
            continue
        p = subprocess.run([MECAB, '-d', IPADIC, '-b', '65536'], input=part,
                           text=True, encoding='utf-8', capture_output=True, timeout=15)
        if p.returncode:
            raise VoiceError('MeCabの読み解析に失敗しました。')
        for line in p.stdout.splitlines():
            if line == 'EOS' or '\t' not in line:
                continue
            surface, features = line.split('\t', 1)
            fields = features.split(',')
            # IPADIC pronunciation includes spoken particles and long vowels.
            value = fields[8] if len(fields) > 8 and fields[8] != '*' else None
            if value is None:
                value = katakana(surface)
                if not re.fullmatch('[ァ-ヺー、。！？!?・「」『』（）()….,：:;；]+', value):
                    unknown.append(surface)
            tokens.append({'surface': surface, 'reading': value, 'source': 'mecab-ipadic'})
    joined = ''.join(t['reading'] for t in tokens)
    return {'text': text, 'prepared_text': apply_readings(text, readings),
            'kana': joined, 'tokens': tokens, 'unknown': unknown,
            'engine': 'MeCab/IPADIC', 'matches_aquestalk_analysis': False,
            'note': '参考読みです。AquesTalk内蔵辞書の解析結果とは異なる場合があります。'}


def phonetic_preview(preview):
    if preview['unknown']:
        raise VoiceError('読み不明の語があります。--readingで指定してください: ' + ', '.join(preview['unknown']))
    value = preview['kana'].translate(str.maketrans({'!': '。', '?': '？', '！': '。', ',': '、', '.': '。'}))
    value = re.sub('[「」『』（）()・…：:;；]', '、', value)
    if not re.fullmatch('[ァ-ヺー、。？]+', value):
        raise VoiceError('音声記号列にできない文字が残っています。仮名で読みを指定してください。')
    # No accent inference: intended for flat yukkuri narration, one explicit reading.
    return '#>' + value


def trim_wav(data, threshold_db=-60, padding_ms=10):
    """Trim only edge silence, preserving pauses inside the utterance."""
    with wave.open(io.BytesIO(data), 'rb') as w:
        params = w.getparams()
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise VoiceError('無音カットには16bitモノラルPCMが必要です。')
        frames = w.readframes(w.getnframes())
    samples = array.array('h', frames)
    threshold = max(1, int(32768 * 10**(threshold_db/20)))
    first = next((i for i, s in enumerate(samples) if abs(s) > threshold), None)
    if first is None:
        raise VoiceError('有効な音声がありません。無音のみのWAVは保存しません。')
    last = len(samples) - next(i for i, s in enumerate(reversed(samples)) if abs(s) > threshold)
    pad = int(params.framerate * padding_ms / 1000)
    begin, end = max(0, first-pad), min(len(samples), last+pad)
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setparams(params)
        w.writeframes(frames[begin*2:end*2])
    return out.getvalue()
