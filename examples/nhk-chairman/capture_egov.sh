#!/bin/bash
# e-Gov 法令検索の放送法52条を撮る（browser-use CLI）。法令は著作権の対象外。
# 表示倍率160％で52条までスクロールし、マーカーを引く文言の位置も表示する（スクショ/v1/位置.json の値と比べる）
set -e
cd "$(dirname "$0")"
mkdir -p スクショ/v1
browser-use --session egov open "https://laws.e-gov.go.jp/law/325AC0000000132" >/dev/null
browser-use --session egov wait selector "#Mp-Ch_3-Se_5-At_52" >/dev/null
browser-use --session egov eval "(()=>{document.documentElement.style.zoom='1.6';document.getElementById('Mp-Ch_3-Se_5-At_52').scrollIntoView({block:'center'});return 'ok'})()"
browser-use --session egov eval "(()=>{const a=document.getElementById('Mp-Ch_3-Se_5-At_52');const w=document.createTreeWalker(a,NodeFilter.SHOW_TEXT);let n,out=[];const key='委員九人以上の多数による議決';while(n=w.nextNode()){const i=n.textContent.indexOf(key);if(i>=0){const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+key.length);out=[...r.getClientRects()].map(x=>[Math.round(x.left),Math.round(x.top),Math.round(x.width),Math.round(x.height)]);}}return JSON.stringify(out)})()"
browser-use --session egov screenshot "$PWD/スクショ/v1/放送法52条_e-Gov.png"
browser-use --session egov close >/dev/null
echo "撮った：スクショ/v1/放送法52条_e-Gov.png（画面の大きさでマーカーの位置が変わるので、位置.json と make_spec.py の mark・box を合わせる）"
