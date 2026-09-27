#!/usr/bin/python3
import array
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from features import apply_readings, trim_wav, VoiceError
CLI=ROOT/'yukkuri.py'
PORT=18768
checks=[]
measurements={}

def run(*args, expected=0, stdin=None):
 p=subprocess.run([sys.executable,str(CLI),*args],input=stdin,text=True,capture_output=True,timeout=150)
 assert p.returncode==expected,(args,p.returncode,p.stderr)
 return p.stdout

def info(path):
 with wave.open(str(path)) as w:
  assert (w.getframerate(),w.getsampwidth(),w.getnchannels())==(48000,2,1)
  frames=w.readframes(w.getnframes())
  assert any(frames)
  return w.getnframes()/48000,frames

def request(path, body, status=200):
 token=(ROOT/'.runtime/token').read_text().strip()
 req=urllib.request.Request('http://127.0.0.1:{}{}'.format(PORT,path),data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 try:
  with opener.open(req,timeout=150) as r:
   assert r.status==status
   return r.read()
 except urllib.error.HTTPError as e:
  assert e.code==status,(e.code,e.read())
  return e.read()

assert apply_readings('三郷市と三郷',{'三郷':'みさと','三郷市':'さんごうし'})=='サンゴウシとミサト'
assert apply_readings('甲乙',{'甲':'こう','乙':'おつ','こう':'かん'})=='コウオツ'
checks.append('Longest-match, nonrecursive reading replacement')
# Preserve internal pauses byte-for-byte, remove only the ends and keep 10ms.
a=array.array('h',[0]*2000+[1000]*3000+[0]*4000+[-1000]*3000+[0]*2000)
buf=io.BytesIO()
with wave.open(buf,'wb') as w:
 w.setparams((1,2,48000,0,'NONE','not compressed')); w.writeframes(a.tobytes())
with wave.open(io.BytesIO(trim_wav(buf.getvalue()))) as w:
 trimmed=array.array('h',w.readframes(w.getnframes()))
assert trimmed==a[1520:12480]
checks.append('Trim preserves internal silence and edge padding exactly')

with tempfile.TemporaryDirectory(prefix='yukkuri-v2-') as tmp:
 tmp=Path(tmp)
 text='三郷と並んで、今日はゆっくり音声の速さを確認します。'
 for voice in ['reimu','marisa']:
  durations={}
  for speed in [100,170,180,190]:
   output=tmp/('{}{}.wav'.format(voice,speed))
   run('say','-t',text,'-v',voice,'--speed',str(speed),'-o',str(output))
   durations[speed]=info(output)[0]
  assert durations[100]>durations[170]>durations[180]>durations[190]
  assert durations[180]<durations[100]*0.75
  measurements[voice]=durations
 checks.append('Native speeds 100 / 170 / 180 / 190 change duration for both voices')
 p=tmp/'trim.wav'
 run('say','-t',text,'-v','marisa','--speed','180','--trim','-o',str(p))
 assert info(p)[0]<measurements['marisa'][180]
 checks.append('Real WAV edge trim shortens output')
 for v in ['れいむ速','まりさ速','koishi','satori']:
  run('say','-t','こんにちは。','-v',v,'--speed','180','-o',str(tmp/(v+'.wav')))
  info(tmp/(v+'.wav'))
 checks.append('Fast aliases and all four standard voices synthesize')
 run('say','-t','こんにちは。','--speed','301','-o',str(tmp/'bad.wav'),expected=1)
 assert not (tmp/'bad.wav').exists()
 run('say','-t','三郷と並んで','--reading','三郷=みさと','--speed','180','-o',str(tmp/'reading.wav'))
 dictionary=tmp/'reading.json';dictionary.write_text(json.dumps({'三郷':'さんごう'},ensure_ascii=False))
 preview=json.loads(run('kana','-t','三郷と並んで','--reading-dict',str(dictionary),'--reading','三郷=みさと','--json'))
 assert preview['kana']=='ミサトトナランデ'
 assert preview['matches_aquestalk_analysis'] is False
 assert preview['prepared_text']=='ミサトと並んで'
 phonetic=run('kana','-t','三郷と並んで','--phonetic').strip()
 assert phonetic=='#>ミサトトナランデ'
 run('say','--file','-','--speed','180','-o',str(tmp/'phonetic.wav'),stdin=phonetic)
 info(tmp/'phonetic.wav')
 run('kana','-t','三郷','--reading','三郷=ABC',expected=1)
 checks.append('Reading dictionary, override precedence, kana and explicit phonetic synthesis')
 script=tmp/'script.tsv'
 script.write_text('番号\t声\tセリフ\t速度\n01\tまりさ\t三郷と並んで。\t190\n02\tれいむ\tこんにちは。\t\n')
 out=tmp/'batch'
 args=['batch',str(script),'--outdir',str(out),'--speed','180','--trim','--reading','三郷=みさと']
 run(*args)
 manifest=json.loads((out/'manifest.json').read_text())
 assert manifest['status']=='complete' and manifest['completed']==2
 assert [x['speed'] for x in manifest['items']]==[190,180]
 assert [x['file'] for x in manifest['items']]==['L01_まりさ.wav','L02_れいむ.wav']
 stamps={p.name:p.stat().st_mtime_ns for p in out.glob('*.wav')}
 for item in manifest['items']:
  assert abs(info(out/item['file'])[0]-item['duration_seconds'])<0.001
 run(*args,'--resume')
 assert stamps=={p.name:p.stat().st_mtime_ns for p in out.glob('*.wav')}
 run(*args,expected=1)
 checks.append('TSV batch filenames, per-row speed, exact durations, manifest, non-rewriting resume')
 bad=tmp/'bad.tsv';bad.write_text('1\tれいむ\tこんにちは\nL01\tまりさ\t重複\n')
 run('batch',str(bad),'--outdir',str(tmp/'bad-batch'),expected=1)
 assert not (tmp/'bad-batch').exists()
 failing=tmp/'failure.tsv';failing.write_text('1\tれいむ\tこんにちは。\n2\tまりさ\t#>ABC\n')
 run('batch',str(failing),'--outdir',str(tmp/'failure'),expected=1)
 failed=json.loads((tmp/'failure/manifest.json').read_text())
 assert failed['completed']==1 and failed['items'][1]['status']=='error'
 info(tmp/'failure/L01_れいむ.wav')
 failing.write_text('1\tれいむ\tこんにちは。\n2\tまりさ\t直しました。\n')
 run('batch',str(failing),'--outdir',str(tmp/'failure'),'--resume')
 checks.append('Duplicate IDs preflight; failed batches preserve results and resume after fixing row')
 run('start','--port',str(PORT))
 try:
  payload={'text':text,'voice':'marisa','speed':180,'trim':True,'readings':{'三郷':'みさと'}}
  audio=request('/synthesize',payload);(tmp/'api.wav').write_bytes(audio);info(tmp/'api.wav')
  result=json.loads(request('/kana',{'text':'三郷と並んで','readings':{'三郷':'みさと'}}))
  assert result['kana']=='ミサトトナランデ' and result['matches_aquestalk_analysis'] is False
  for k,v in [('speed',True),('speed',400),('trim','yes'),('readings',[])]:
   invalid=dict(payload);invalid[k]=v;request('/synthesize',invalid,status=400)
  run('request','-t','三郷と並んで','--reading','三郷=みさと','--speed','180','--trim','--port',str(PORT),'-o',str(tmp/'request.wav'))
  info(tmp/'request.wav')
 finally:
  run('stop','--port',str(PORT))
 checks.append('API v2 speed / trim / readings / kana and invalid parameter errors')

report={'passed':len(checks),'checks':checks,'native_speed_duration_seconds':measurements,
        'kana_limitation':'MeCab reference, not AqKanji2Koe internal result'}
(ROOT.parent/'検証/CLI_API_v2検証.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
