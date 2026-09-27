#!/usr/bin/python3
"""Real engine and HTTP integration checks; no paid or external API."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import wave

CLI = Path(__file__).resolve().parents[1] / 'yukkuri.py'
PORT = 18767
checks = []
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def run(*args, expected=0, stdin=None):
    p = subprocess.run([sys.executable, str(CLI), *args], input=stdin, text=True,
                       capture_output=True, timeout=150)
    assert p.returncode == expected, (args, p.returncode, p.stderr)
    return p.stdout

def wav(data):
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (48000, 2, 1)
        assert w.getnframes() > 24000
        assert any(w.readframes(w.getnframes()))

def req(path, body=None, auth=True, expected=200, raw=None, origin=None):
    headers = {'Content-Type': 'application/json'}
    if auth:
        headers['Authorization'] = 'Bearer ' + (CLI.parent/'.runtime/token').read_text().strip()
    if origin:
        headers['Origin'] = origin
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request('http://127.0.0.1:{}{}'.format(PORT,path), data=data, headers=headers)
    try:
        with opener.open(request, timeout=150) as r:
            assert r.status == expected
            return r.read()
    except urllib.error.HTTPError as e:
        assert e.code == expected, (e.code,e.read())
        return e.read()

with tempfile.TemporaryDirectory(prefix='yukkuri-test-') as temp:
    temp=Path(temp)
    out=temp/'日本語 出力.wav'
    info=json.loads(run('say','--file','-','--voice','reimu','-o',str(out),stdin='こんにちは。ゆっくりしていってね。'))
    wav(out.read_bytes())
    assert info['sample_rate']==48000
    checks.append('CLI stdin / Japanese path / PCM16 mono 48kHz WAV')
    before=hashlib.sha256(out.read_bytes()).hexdigest()
    run('say','-t','上書きしない。','-o',str(out),expected=1)
    assert hashlib.sha256(out.read_bytes()).hexdigest()==before
    checks.append('Existing output preserved without --force')
    run('say','-t','','-o',str(temp/'empty.wav'),expected=1)
    run('say','-t','こんにちは。','--voice','unknown','-o',str(temp/'unknown.wav'),expected=1)
    run('say','-t','こんにちは。','--preset','存在しないプリセット_検証','-o',str(temp/'badpreset.wav'),expected=1)
    checks.append('Empty text / invalid voice / native preset error handled')
    run('start','--port',str(PORT))
    try:
        run('start','--port',str(PORT))
        assert json.loads(run('status','--port',str(PORT)))['service']=='yukkuri-local'
        checks.append('Background start is idempotent / status authenticated')
        req('/health',auth=False,expected=401)
        req('/health',origin='https://example.org',expected=403)
        req('/synthesize',{'text':''},expected=400)
        req('/synthesize',{'text':'こんにちは。','voice':[]},expected=400)
        req('/synthesize',{'text':'こんにちは。','output':'/tmp/not-allowed.wav'},expected=400)
        req('/synthesize',raw=b'{broken',expected=400)
        req('/synthesize',{'text':'a'*4001},expected=400)
        req('/synthesize',raw=b' '*32769,expected=413)
        req('/missing',expected=404)
        checks.append('401 / 403 / 400 / 413 / 404 input and access controls')
        voices=json.loads(req('/voices'))
        assert voices['voices']['marisa']=='まりさ'
        audio=req('/synthesize',{'text':'こんにちは。ゆっくりしていってね。','voice':'marisa'})
        wav(audio)
        assert hashlib.sha256(audio).hexdigest()!=before
        checks.append('HTTP marisa WAV / different from reimu')
        run('request','-t','音声のテストです。','--voice','れいむ','--port',str(PORT),'-o',str(temp/'request.wav'))
        wav((temp/'request.wav').read_bytes())
        checks.append('API client command / Japanese voice alias')
    finally:
        run('stop','--port',str(PORT))
        for _ in range(30):
            p=subprocess.run([sys.executable,str(CLI),'status','--port',str(PORT)],capture_output=True)
            if p.returncode==1:
                break
            time.sleep(0.1)
        assert p.returncode==1
    checks.append('Authenticated shutdown / status stopped')
report={'passed':len(checks),'checks':checks}
(CLI.parent.parent/'検証/CLI_API検証.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
