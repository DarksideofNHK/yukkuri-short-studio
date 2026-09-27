#!/usr/bin/env python3
"""studio.py — 動画制作を複数のAIで分担し、統括（Claude Code）が1か所で管理するための道具。

考え方
  - 状態の正本は tasks.json だけ。書くのは統括（このスクリプト）だけ。
  - 1つの作業 = tasks/<ID>_<名前>/brief.md（やること）→ 担当AIが 報告.md（やった結果）。
  - どのAIでも「brief.md を読んで実行」で動ける。モデルは交換部品、知識はファイル。

使い方（プロジェクトのフォルダで）
  python3 tools/studio.py status              フェーズごとの一覧
  python3 tools/studio.py next                今すぐ着手できる作業
  python3 tools/studio.py brief T03           brief.md のひな形を作る（すでにあれば何もしない）
  python3 tools/studio.py dispatch T03        担当に渡す（渡し方を表示して「作業中」にする）
        --run            codex-cli / gemini-cli は続けてその場で実行する
        --approve-cost   課金のある担当（gemini-cli など）を、ユーザー承認済みとして通す
  python3 tools/studio.py run T03             渡し済みの codex-cli / gemini-cli 作業を実行だけする（並列可）
  python3 tools/studio.py sync                報告.md を読んで状態を進め、受け入れ条件を点検
  python3 tools/studio.py check T03           受け入れ条件だけ点検
  python3 tools/studio.py approve T03 [--user] [--note ...]   確認待ち → 完了（user_gate の作業は --user が要る）
  python3 tools/studio.py block T03 --note ...                詰まりにする
  python3 tools/studio.py board               board.html を作り直す
  python3 tools/studio.py codex-activity      Codex アプリで今動いている作業をのぞく（手元の ~/.codex/sessions のログを読むだけ）
  python3 tools/studio.py serve [--port 8765] ユーザー用の看板ボード（ブラウザで操作できる）を開く
  python3 tools/studio.py init --title 題名   標準の工程から新しい tasks.json を作る
"""
import argparse
import datetime as dt
import fcntl
import glob
import html
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATUS_JA = {"todo": "待ち", "ready": "着手可", "doing": "作業中", "review": "確認待ち", "done": "完了", "blocked": "詰まり"}
REPORT_STATE = {"完了": "review", "途中": "doing", "詰まり": "blocked"}

REPORT_FORMAT = """状態：完了｜途中｜詰まり（どれか1つ）
やったこと：（箇条書き）
成果物：（パス。brief の「出力」と同じ場所）
受け入れ条件：（1つずつ、満たしたか）
申し送り：（統括やほかの担当に頼むこと・気づいたこと。なければ「なし」）"""

# 担当ごとの渡し方。paid=True は、使う前にコストの見積もりとユーザー承認が要る。
AGENTS = {
    "claude-main": {"label": "Claude Code（統括）", "paid": False, "how": "self"},
    "claude-sub:researcher": {"label": "Claude サブ（researcher）", "paid": False, "how": "agent"},
    "claude-sub:draft-writer": {"label": "Claude サブ（draft-writer・Sonnet）", "paid": False, "how": "agent"},
    "claude-sub:general-purpose": {"label": "Claude サブ（汎用）", "paid": False, "how": "agent"},
    "codex-cli": {"label": "Codex CLI（ChatGPT契約内）", "paid": False, "how": "codex"},
    "codex-app": {"label": "Codex アプリ（手渡し）", "paid": False, "how": "paste"},
    "gemini-cli": {"label": "Gemini CLI（APIキー・従量）", "paid": True, "how": "gemini"},
    "grok": {"label": "Grok Build（SuperGrok枠内）", "paid": False, "how": "paste"},
    "user": {"label": "ユーザー", "paid": False, "how": "user"},
}

# 標準の工程（init で使う）。ids は通し番号で振り直す。
STANDARD = [
    ("リサーチ", "リサーチ・ファクト表", "claude-sub:researcher", [], ["research/ファクト表.md"]),
    ("台本", "台本 v1", "claude-main", ["リサーチ・ファクト表"], ["台本_v1.md"]),
    ("台本", "台本のファクトチェック（別モデル）", "codex-cli", ["台本 v1"], []),
    ("台本", "台本の確定（ユーザー）", "user", ["台本のファクトチェック（別モデル）"], []),
    ("素材", "絵（人物・背景）", "codex-app", ["台本 v1"], ["絵/v1/"]),
    ("素材", "図（自作の図）", "codex-cli", ["台本 v1"], ["図/v1/"]),
    ("素材", "資料のスクショ", "claude-main", ["台本 v1"], ["スクショ/v1/"]),
    ("音声", "ゆっくりボイスの音声", "claude-main", ["台本の確定（ユーザー）"], ["音声/v1/"]),
    ("編集", "spec.json", "claude-main", ["絵（人物・背景）", "図（自作の図）", "資料のスクショ", "ゆっくりボイスの音声"], ["premiere/v1/spec.json"]),
    ("編集", "Premiere XML のビルド", "claude-main", ["spec.json"], ["premiere/v1/"]),
    ("検収", "プレビューの点検（別モデル）", "codex-cli", ["Premiere XML のビルド"], []),
    ("検収", "Premiere で確認（ユーザー）", "user", ["プレビューの点検（別モデル）"], []),
    ("公開", "概要欄・出典", "claude-main", ["台本の確定（ユーザー）"], ["公開/概要欄.md"]),
]


# ---------------------------------------------------------------- 基本

def find_root():
    env = os.environ.get("STUDIO_ROOT")
    if env:
        return Path(env).resolve()
    p = Path.cwd().resolve()
    for q in [p, *p.parents]:
        if (q / "tasks.json").exists():
            return q
    return p  # 見つからなければ今いるフォルダ（init で新しいプロジェクトを作るとき）


ROOT = find_root()
TASKS = ROOT / "tasks.json"
LOG = ROOT / "作業ログ.md"


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def load():
    if not TASKS.exists():
        sys.exit(f"tasks.json がありません（{ROOT}）。init で作ってください。")
    return json.loads(TASKS.read_text(encoding="utf-8"))


def save(data):
    data["updated"] = now()
    tmp = TASKS.with_suffix(".json.tmp")  # 書きかけをボードが読まないよう、別名で書いて差し替える
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, TASKS)
    write_board(data)


@contextmanager
def locked():
    """tasks.json の読み書きを1人ずつにする（CLI とボードのサーバーが同時に書いても壊れないように）。"""
    with open(ROOT / ".tasks.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def log(lines, who="統括（studio.py）"):
    head = f"\n## {now()}　{who}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(head + "".join(f"- {l}\n" for l in lines))


def task_of(data, tid):
    for t in data["tasks"]:
        if t["id"].lower() == tid.lower():
            return t
    sys.exit(f"{tid} というタスクはありません。")


def tdir(t):
    return ROOT / "tasks" / f"{t['id']}_{t['slug']}"


def rel(p):
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def deps_done(data, t):
    by = {x["id"]: x for x in data["tasks"]}
    return all(by[d]["status"] == "done" for d in t.get("depends_on", []) if d in by)


def view_status(data, t):
    if t["status"] == "todo" and deps_done(data, t):
        return "ready"
    return t["status"]


# ---------------------------------------------------------------- 受け入れ条件

def run_checks(t):
    """受け入れ条件を機械的に点検して [(ok, 説明)] を返す。"""
    res = []
    for c in t.get("acceptance", []):
        kind = c.get("type")
        if kind == "report":
            st = read_report_state(t)
            res.append((st == "完了", f"報告.md の状態が「完了」（いま：{st or 'なし'}）"))
        elif kind == "exists":
            hits = glob.glob(str(ROOT / c["path"]))
            need = c.get("min", 1)
            res.append((len(hits) >= need, f"{c['path']} が{need}個以上（{len(hits)}個）"))
        elif kind == "png":
            hits = sorted(glob.glob(str(ROOT / c["path"])))
            need = c.get("min", 1)
            if len(hits) < need:
                res.append((False, f"{c['path']} が{need}個以上（{len(hits)}個）"))
                continue
            try:
                from PIL import Image
            except ImportError:
                res.append((False, "Pillow がないので PNG を点検できない"))
                continue
            for h in hits:
                im = Image.open(h)
                ok, why = True, []
                if "size" in c and list(im.size) != list(c["size"]):
                    ok = False
                    why.append(f"大きさ {im.size[0]}×{im.size[1]}（期待 {c['size'][0]}×{c['size'][1]}）")
                if c.get("alpha") and im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
                    ok = False
                    why.append(f"透過なし（{im.mode}）")
                res.append((ok, f"{rel(h)} " + ("OK" if ok else "・".join(why))))
        elif kind == "grep":
            p = ROOT / c["path"]
            txt = p.read_text(encoding="utf-8") if p.exists() else ""
            n = len(re.findall(c["pattern"], txt, re.M))
            need = c.get("min", 1)
            res.append((n >= need, f"{c['path']} に /{c['pattern']}/ が{need}回以上（{n}回）"))
        else:
            res.append((False, f"知らない条件：{c}"))
    return res


def read_report_state(t):
    p = tdir(t) / "報告.md"
    if not p.exists():
        return None
    m = re.search(r"^\**状態\**\s*[：:]\s*\**\s*(完了|途中|詰まり)", p.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "不明"


# ---------------------------------------------------------------- brief と渡し方

def make_brief(data, t, force=False):
    d = tdir(t)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "brief.md"
    if p.exists() and not force:
        return p
    by = {x["id"]: x for x in data["tasks"]}
    acc = []
    for c in t.get("acceptance", []):
        if c["type"] == "report":
            acc.append("報告.md の「状態：完了」")
        elif c["type"] == "png":
            s = f"{c['size'][0]}×{c['size'][1]}" if "size" in c else "任意の大きさ"
            acc.append(f"`{c['path']}` が PNG（{s}{'・透過' if c.get('alpha') else ''}）で{c.get('min', 1)}枚以上")
        elif c["type"] == "exists":
            acc.append(f"`{c['path']}` がある")
        elif c["type"] == "grep":
            acc.append(f"`{c['path']}` に「{c['pattern']}」が{c.get('min', 1)}回以上")
    deps = ", ".join(x + "（" + by[x]["title"] + "）" for x in t.get("depends_on", []) if x in by) or "なし"
    body = [
        f"# {t['id']} {t['title']}",
        "",
        f"- 担当：{AGENTS.get(t['owner'], {}).get('label', t['owner'])}",
        f"- 工程：{t['phase']}",
        f"- 前提の作業：{deps}",
        "",
        "## 目的",
        "",
        t.get("goal", "（統括が書く）"),
        "",
        "## 入力（読むもの）",
        "",
        *([f"- `{x}`" for x in t.get("inputs", [])] or ["- なし"]),
        "",
        "## やること",
        "",
        *([f"{i}. {x}" for i, x in enumerate(t.get("do", []), 1)] or ["1. （統括が書く）"]),
        "",
        "## 出力（書いてよい場所はここだけ）",
        "",
        *[f"- `{x}`" for x in t.get("outputs", [])],
        f"- `{rel(d / '報告.md')}`",
        "",
        "## 受け入れ条件（統括が studio.py check で点検する）",
        "",
        *([f"- {x}" for x in acc] or ["- 報告.md がある"]),
        "",
        "## 守ること",
        "",
        "- 出力の場所以外のファイルは書き換えない。すでにあるファイルは上書きしない（直すときは版を上げる）。",
        "- tasks.json と 作業ログ.md は統括だけが書く。触らない。",
        "- 課金のある API は使わない（必要なら報告の申し送りに書いて止まる）。",
        "- 公開前提：画面に出す素材は、自作の絵・自作の図・法令の条文だけ。番組映像・公式ロゴ・報道写真は使わない。",
        "- 確認や質問で止まらず、判断できることは判断して最後まで進める。判断できないことは申し送りに書く。",
        "",
        "## 報告の書式（報告.md に、この形で書く）",
        "",
        "```",
        REPORT_FORMAT,
        "```",
        "",
    ]
    p.write_text("\n".join(body), encoding="utf-8")
    return p


def handoff_text(t):
    d = rel(tdir(t))
    return (f"{ROOT} の {d}/brief.md を読んで、書かれているとおりに実行してください。"
            f"終わったら {d}/報告.md を brief の末尾の書式で書いてください。"
            f"tasks.json と 作業ログ.md は触らないでください。")


def codex_bin():
    """Codex アプリ（ChatGPT.app）同梱の CLI を優先する。npm 版は古いと新しいモデルを使えない。"""
    for b in [os.environ.get("CODEX_BIN"), "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"]:
        if b and Path(b).exists():
            return b
    return "codex"


def codex_cmd(t):
    d = rel(tdir(t))
    prompt = (f"{d}/brief.md を読んで、書かれているとおりに実行してください。"
              f"作業はこのフォルダの中だけで行い、brief の「出力」に書かれたパス以外は書き換えないでください。"
              f"最後の返答は brief の末尾の「報告の書式」どおりに書いてください（その返答がそのまま {d}/報告.md になります）。"
              f"確認や質問は不要です。判断できることは判断して最後まで進めてください。日本語で回答してください。")
    return [codex_bin(), "exec", "-C", str(ROOT), "-s", t.get("sandbox", "read-only"),
            "--skip-git-repo-check", "-o", str(tdir(t) / "報告.md"), prompt]


# ---------------------------------------------------------------- コマンド

def cmd_status(data, _a):
    phases = []
    for t in data["tasks"]:
        if t["phase"] not in phases:
            phases.append(t["phase"])
    print(f"{data.get('title', '')}（更新 {data.get('updated', '-')}）")
    for ph in phases:
        print(f"\n■ {ph}")
        for t in [x for x in data["tasks"] if x["phase"] == ph]:
            st = view_status(data, t)
            mark = ("👤" if t.get("user_gate") else "") + ("💴" if AGENTS.get(t["owner"], {}).get("paid") else "")
            dep = ",".join(t.get("depends_on", [])) or "-"
            print(f"  {t['id']:<4} {STATUS_JA[st]:<5} {t['owner']:<24} {t['title']}{(' ' + mark) if mark else ''}  ← {dep}")
            if t.get("note"):
                print(f"         └ {t['note']}")


def cmd_next(data, _a):
    ready = [t for t in data["tasks"] if view_status(data, t) == "ready"]
    if not ready:
        print("今すぐ着手できる作業はありません。")
    for t in ready:
        print(f"{t['id']} {t['title']}（{t['owner']}）")


def cmd_brief(data, a):
    t = task_of(data, a.id)
    p = make_brief(data, t, force=a.force)
    print(rel(p))


def cmd_dispatch(data, a):
    t = task_of(data, a.id)
    ag = AGENTS.get(t["owner"])
    if not ag:
        sys.exit(f"知らない担当：{t['owner']}")
    if t["status"] not in ("todo", "blocked") and not a.again:
        sys.exit(f"{t['id']} はいま「{STATUS_JA[t['status']]}」なので渡せません（やり直すときは --again）。")
    if not deps_done(data, t):
        by = {x["id"]: x for x in data["tasks"]}
        left = [f"{d}（{STATUS_JA[by[d]['status']]}）" for d in t.get("depends_on", []) if by[d]["status"] != "done"]
        sys.exit(f"前提の作業が終わっていません：{', '.join(left)}")
    if ag["paid"] and not a.approve_cost:
        sys.exit(f"{t['owner']} は従量課金です。見積もり（{t.get('cost_estimate', '未記入')}）をユーザーに示して承認をもらい、--approve-cost を付けてください。")
    exist = [o for o in t.get("outputs", []) if not o.endswith("/") and glob.glob(str(ROOT / o))]
    if exist and not t.get("allow_existing"):
        sys.exit(f"出力先がすでにあります（上書き禁止）：{', '.join(exist)}。版を上げた出力先にしてください。")
    make_brief(data, t)
    old = tdir(t) / "報告.md"
    if old.exists():
        old.rename(tdir(t) / f"報告_{dt.datetime.now():%m%d%H%M}.md")

    how = ag["how"]
    t["status"] = "doing"
    t["dispatched_at"] = now()
    save(data)
    log([f"{t['id']} {t['title']} を {t['owner']} に渡した"])

    if how == "codex":
        print("Codex CLI で実行：python3 tools/studio.py run " + t["id"] + "（dispatch --run なら続けて実行）")
    elif how == "gemini":
        print("Gemini CLI で実行：python3 tools/studio.py run " + t["id"] + "（brief と入力を標準入力で渡す）")
    elif how == "agent":
        sub = t["owner"].split(":", 1)[1]
        print(f"Agent ツールで subagent_type={sub} に次の依頼文を渡す：")
        print(handoff_text(t))
    elif how == "paste":
        print(f"{ag['label']} に次の文を貼り付けて渡す：")
        print(handoff_text(t))
    elif how == "user":
        print("ユーザーの判断待ちにした。決まったら approve --user --note '決まったこと' で完了にする。")
    else:
        print("統括（Claude Code）が自分で行う。終わったら 報告.md を書いて sync。")


def cmd_run(data, a):
    """渡し済み（作業中）の codex-cli / gemini-cli 作業を実行するだけ。tasks.json は書かない（並べて走らせても安全）。"""
    t = task_of(data, a.id)
    how = AGENTS.get(t["owner"], {}).get("how")
    if how not in ("codex", "gemini") or t["status"] != "doing":
        sys.exit(f"{t['id']} は codex-cli / gemini-cli の作業中の作業ではありません（先に dispatch）。")
    d = tdir(t)
    print(f"{t['id']} を実行中…（{t['owner']}）", flush=True)
    if how == "codex":
        with open(d / "codex_stdout.log", "w") as out:
            r = subprocess.run(codex_cmd(t), cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    else:
        stdin = (d / "brief.md").read_text(encoding="utf-8")
        for x in t.get("inputs", []):
            for h in sorted(glob.glob(str(ROOT / x))):
                if Path(h).is_file() and Path(h).suffix in (".md", ".txt", ".json", ".csv"):
                    stdin += f"\n\n===== 入力：{rel(h)} =====\n" + Path(h).read_text(encoding="utf-8")
        cmd = ["gemini", "-p", "上の brief と入力を読んで、brief の「報告の書式」どおりに報告だけを返してください。日本語で。", "--approval-mode", "plan"]
        r = subprocess.run(cmd, cwd=ROOT, input=stdin, capture_output=True, text=True)
        (d / "報告.md").write_text(r.stdout, encoding="utf-8")
        (d / "gemini_stderr.log").write_text(r.stderr, encoding="utf-8")
    print(f"{t['id']} 終了コード {r.returncode}。取り込みは sync で。")


def cmd_sync(data, _a):
    changed = []
    for t in data["tasks"]:
        if t["status"] not in ("doing", "blocked"):
            continue
        st = read_report_state(t)
        if st is None:
            continue
        new = REPORT_STATE.get(st)
        if st == "不明":
            new = "review"
        if new and new != t["status"]:
            t["status"] = new
            checks = run_checks(t) if new == "review" else []
            t["checks"] = [{"ok": ok, "what": w} for ok, w in checks]
            ng = [w for ok, w in checks if not ok]
            changed.append(f"{t['id']} {t['title']}：報告「{st}」→ {STATUS_JA[new]}" + (f"（受け入れ条件 NG {len(ng)}件）" if ng else ""))
    if changed:
        save(data)
        log(changed)
    print("\n".join(changed) if changed else "変化なし。")


def cmd_check(data, a):
    t = task_of(data, a.id)
    res = run_checks(t)
    for ok, w in res:
        print(("✅ " if ok else "❌ ") + w)
    t["checks"] = [{"ok": ok, "what": w} for ok, w in res]
    save(data)


def cmd_approve(data, a):
    t = task_of(data, a.id)
    if t.get("user_gate") and not a.user:
        sys.exit(f"{t['id']} はユーザーの確認が要る作業です。ユーザーがOKと言ったときだけ --user を付けて完了にしてください。")
    if t["status"] not in ("review", "doing") and not (t["owner"] == "user" and t["status"] in ("todo", "doing")):
        sys.exit(f"{t['id']} はいま「{STATUS_JA[t['status']]}」です。")
    ng = [c for c in t.get("checks", []) if not c["ok"]]
    if ng and not a.force:
        sys.exit("受け入れ条件に NG があります：" + " / ".join(c["what"] for c in ng) + "（それでも通すなら --force と理由の --note）")
    t["status"] = "done"
    t["done_at"] = now()
    if a.note:
        t["note"] = a.note
    save(data)
    log([f"{t['id']} {t['title']} を完了にした" + ("（ユーザー確認）" if a.user else "") + (f"：{a.note}" if a.note else "")])
    print(f"{t['id']} 完了。")
    cmd_next(load(), a)


def cmd_block(data, a):
    t = task_of(data, a.id)
    t["status"] = "blocked"
    t["note"] = a.note or t.get("note", "")
    save(data)
    log([f"{t['id']} {t['title']} を詰まりにした：{a.note}"])


def cmd_codex_activity(_data, a):
    files = sorted(glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")), key=os.path.getmtime)
    if not files:
        sys.exit("Codex のセッションが見つかりません。")
    for f in files[-a.n:]:
        cwd, users, last = None, [], ""
        for line in open(f, encoding="utf-8", errors="ignore"):
            try:
                j = json.loads(line)
            except ValueError:
                continue
            pl = j.get("payload", {})
            if j.get("type") == "session_meta":
                cwd = pl.get("cwd")
            if pl.get("type") == "message":
                txt = " ".join(c.get("text", "") for c in pl.get("content", []) if isinstance(c, dict))
                if pl.get("role") == "user" and txt and not txt.lstrip().startswith(("<", "# AGENTS")):
                    users.append(txt.strip().replace("\n", " ")[:160])
                elif pl.get("role") == "assistant" and txt:
                    last = txt.strip().replace("\n", " ")[:300]
        mt = dt.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%m-%d %H:%M")
        print(f"■ 最終更新 {mt}  場所 {cwd}")
        for u in users[-2:]:
            print(f"  依頼：{u}")
        if last:
            print(f"  最後の返答：{last}")


def cmd_init(_data, a):
    if TASKS.exists() and not a.force:
        sys.exit("tasks.json はもうあります（作り直すなら --force。上書きになるので注意）。")
    ids = {}
    tasks = []
    for i, (ph, title, owner, deps, outs) in enumerate(STANDARD, 1):
        tid = f"T{i:02d}"
        ids[title] = tid
        tasks.append({"id": tid, "slug": re.sub(r"[\s/（）()・]+", "_", title).strip("_"), "phase": ph, "title": title,
                      "owner": owner, "status": "todo", "depends_on": [ids[d] for d in deps], "inputs": [],
                      "outputs": outs, "acceptance": [{"type": "report"}], "user_gate": owner == "user", "goal": "", "do": []})
    save({"title": a.title, "agents": {k: v["label"] for k, v in AGENTS.items()}, "tasks": tasks})
    print(f"{TASKS} を作りました（{len(tasks)}件）。")


# ---------------------------------------------------------------- ボード（HTML）

def write_board(data):
    cols = ["todo", "ready", "doing", "review", "blocked", "done"]
    cards = {c: [] for c in cols}
    for t in data["tasks"]:
        cards[view_status(data, t)].append(t)
    def card(t):
        badges = []
        if t.get("user_gate"):
            badges.append('<span class="b u">ユーザー確認</span>')
        if AGENTS.get(t["owner"], {}).get("paid"):
            badges.append('<span class="b p">従量課金</span>')
        ng = [c for c in t.get("checks", []) if not c["ok"]]
        if ng:
            badges.append(f'<span class="b n">条件NG {len(ng)}</span>')
        dep = "・".join(t.get("depends_on", []))
        note = f'<div class="note">{html.escape(t["note"])}</div>' if t.get("note") else ""
        return (f'<div class="card"><div class="top"><b>{t["id"]}</b><span class="ph">{html.escape(t["phase"])}</span></div>'
                f'<div class="ti">{html.escape(t["title"])}</div>'
                f'<div class="ow">{html.escape(AGENTS.get(t["owner"], {}).get("label", t["owner"]))}</div>'
                f'{"<div class=dep>← " + dep + "</div>" if dep else ""}{note}<div>{"".join(badges)}</div></div>')
    colhtml = "".join(
        f'<section class="col s-{c}"><h2>{STATUS_JA[c]} <small>{len(cards[c])}</small></h2>{"".join(card(t) for t in cards[c])}</section>'
        for c in cols)
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>制作ボード</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--sub:#6b6b70;--line:#e2e0da;--u:#b4441c;--p:#8a5a00;--n:#c0262d;--acc:#2f5bd3}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#17181a;--card:#222326;--ink:#ececef;--sub:#a0a0a8;--line:#34353a;--u:#ff9466;--p:#e0b24d;--n:#ff6b6b;--acc:#7ea2ff}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Hiragino Sans",system-ui,sans-serif}}
header{{padding:16px}} h1{{font-size:18px;margin:0}} header p{{margin:4px 0 0;color:var(--sub)}}
main{{display:grid;grid-template-columns:repeat(6,minmax(180px,1fr));gap:10px;padding:0 16px 24px;overflow-x:auto}}
@media (max-width:760px){{main{{grid-template-columns:1fr}}}}
.col h2{{font-size:13px;margin:0 0 8px;color:var(--sub)}} .col h2 small{{font-weight:400}}
.s-ready h2{{color:var(--acc)}} .s-blocked h2{{color:var(--n)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px}}
.s-done .card{{opacity:.6}} .top{{display:flex;justify-content:space-between;color:var(--sub);font-size:12px}}
.ti{{font-weight:600;margin:2px 0}} .ow,.dep,.note{{font-size:12px;color:var(--sub)}}
.b{{display:inline-block;font-size:11px;border:1px solid currentColor;border-radius:99px;padding:0 6px;margin:4px 4px 0 0}}
.u{{color:var(--u)}} .p{{color:var(--p)}} .n{{color:var(--n)}}
</style></head><body><header><h1>{html.escape(data.get("title", "制作ボード"))}</h1>
<p>更新 {html.escape(data.get("updated", ""))}・正本は tasks.json（このページは studio.py が作り直す）</p></header>
<main>{colhtml}</main>
<script type="application/json" id="board-data">{html.escape(json.dumps(data, ensure_ascii=False))}</script>
</body></html>"""
    (ROOT / "board.html").write_text(page, encoding="utf-8")


def cmd_board(data, _a):
    write_board(data)
    print(ROOT / "board.html")


# ---------------------------------------------------------------- ユーザー用の看板ボード（serve）

def phases_of(data):
    out = []
    for t in data["tasks"]:
        if t["phase"] not in out:
            out.append(t["phase"])
    return out


def state_json():
    data = load()
    tasks = []
    for t in data["tasks"]:
        d = tdir(t)
        x = dict(t)
        x["view"] = view_status(data, t)
        x["dir"] = rel(d)
        x["has_brief"] = (d / "brief.md").exists()
        x["has_report"] = (d / "報告.md").exists()
        x["report_state"] = read_report_state(t)
        x["owner_label"] = AGENTS.get(t["owner"], {}).get("label", t["owner"])
        x["paid"] = AGENTS.get(t["owner"], {}).get("paid", False)
        x["needs_user"] = (t["owner"] == "user" and x["view"] in ("ready", "doing")) or \
                          (bool(t.get("user_gate")) and t["status"] == "review")
        tasks.append(x)
    tail = LOG.read_text(encoding="utf-8").splitlines()[-80:] if LOG.exists() else []
    return {"title": data.get("title", ""), "updated": data.get("updated", ""), "tasks": tasks,
            "phases": phases_of(data), "agents": {k: v["label"] for k, v in AGENTS.items()},
            "log": "\n".join(tail)}


def task_detail(tid):
    data = load()
    t = task_of(data, tid)
    d = tdir(t)
    rd = lambda n: (d / n).read_text(encoding="utf-8") if (d / n).exists() else ""
    imgs = []
    for o in t.get("outputs", []):
        pat = o + "**/*.png" if o.endswith("/") else o
        for h in sorted(glob.glob(str(ROOT / pat), recursive=True)):
            if h.lower().endswith((".png", ".jpg", ".jpeg")) and rel(h) not in imgs:
                imgs.append(rel(h))
    return {"brief": rd("brief.md"), "report": rd("報告.md"), "images": imgs[:40]}


def do_action(body):
    act = body.get("action")
    note = (body.get("note") or "").strip()
    with locked():
        data = load()
        if act == "add":
            title = (body.get("title") or "").strip()
            if not title:
                sys.exit("題名を入れてください。")
            owner = body.get("owner") or "claude-main"
            if owner not in AGENTS:
                sys.exit(f"知らない担当：{owner}")
            n = max([int(re.sub(r"\D", "", x["id"]) or 0) for x in data["tasks"]] + [0]) + 1
            t = {"id": f"T{n:02d}", "slug": re.sub(r"[\s/（）()・:：]+", "_", title).strip("_")[:24] or "作業",
                 "phase": (body.get("phase") or "その他").strip(), "title": title, "owner": owner,
                 "status": "todo", "depends_on": [], "inputs": [], "outputs": [],
                 "acceptance": [] if owner == "user" else [{"type": "report"}],
                 "user_gate": owner == "user", "added_by": "ユーザー（ボード）"}
            if note:
                t["memos"] = [{"at": now(), "by": "ユーザー", "text": note}]
            data["tasks"].append(t)
            save(data)
            log([f"{t['id']} {title}（{owner}）をカードに足した" + (f"：{note}" if note else "")], who="ユーザー（ボード）")
            return f"{t['id']} を足しました。"
        t = task_of(data, body.get("id", ""))
        if act == "approve":
            v = view_status(data, t)
            if t["status"] == "done":
                sys.exit("もう完了しています。")
            if not (t["status"] in ("review", "doing") or (t["owner"] == "user" and v == "ready")):
                sys.exit(f"いま「{STATUS_JA[v]}」なので完了にできません。")
            ng = [c for c in t.get("checks", []) if not c["ok"]]
            if ng and not body.get("force"):
                sys.exit("受け入れ条件に NG があります：" + " / ".join(c["what"] for c in ng))
            t["status"] = "done"
            t["done_at"] = now()
            t["approved_by"] = "ユーザー（ボード）"
            if note:
                t.setdefault("memos", []).append({"at": now(), "by": "ユーザー", "text": note})
                if t["owner"] == "user":
                    t["decision"] = note
            msg = f"{t['id']} {t['title']} をOK（完了）にした" + (f"：{note}" if note else "")
        elif act == "sendback":
            if not note:
                sys.exit("差し戻す理由を書いてください。")
            t["status"] = "blocked"
            t["note"] = "差し戻し：" + note
            t.setdefault("memos", []).append({"at": now(), "by": "ユーザー", "text": "差し戻し：" + note})
            msg = f"{t['id']} {t['title']} を差し戻した：{note}"
        elif act == "memo":
            if not note:
                sys.exit("メモが空です。")
            t.setdefault("memos", []).append({"at": now(), "by": "ユーザー", "text": note})
            msg = f"{t['id']} {t['title']} にメモ：{note}"
        else:
            sys.exit(f"知らない操作：{act}")
        save(data)
        log([msg], who="ユーザー（ボード）")
        return msg


class BoardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _host_ok(self):
        h = (self.headers.get("Host") or "").split(":")[0]
        return h in ("127.0.0.1", "localhost")

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "forbidden", "text/plain")
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                app = (Path(__file__).parent / "board_app.html").read_text(encoding="utf-8")
                return self._send(200, app, "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._json(200, state_json())
            if u.path == "/api/task":
                return self._json(200, task_detail(q.get("id", [""])[0]))
            if u.path == "/file":
                p = (ROOT / q.get("path", [""])[0]).resolve()
                p.relative_to(ROOT)
                if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp") or not p.exists():
                    return self._send(404, "not found", "text/plain")
                ct = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                return self._send(200, p.read_bytes(), ct)
        except SystemExit as e:
            return self._json(400, {"ok": False, "msg": str(e)})
        except ValueError:
            return self._send(403, "forbidden", "text/plain")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Studio") != "1":
            return self._send(403, "forbidden", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            self._json(200, {"ok": True, "msg": do_action(body)})
        except SystemExit as e:
            self._json(400, {"ok": False, "msg": str(e)})


def cmd_serve(_data, a):
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), BoardHandler)
    print(f"看板ボード：http://127.0.0.1:{a.port}/  （止めるときは Ctrl+C）", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description="動画制作の分担ボード")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status")
    sp.add_parser("next")
    b = sp.add_parser("brief"); b.add_argument("id"); b.add_argument("--force", action="store_true")
    d = sp.add_parser("dispatch"); d.add_argument("id"); d.add_argument("--run", action="store_true")
    d.add_argument("--approve-cost", action="store_true"); d.add_argument("--again", action="store_true")
    sp.add_parser("sync")
    r = sp.add_parser("run"); r.add_argument("id")
    c = sp.add_parser("check"); c.add_argument("id")
    p = sp.add_parser("approve"); p.add_argument("id"); p.add_argument("--user", action="store_true")
    p.add_argument("--note"); p.add_argument("--force", action="store_true")
    k = sp.add_parser("block"); k.add_argument("id"); k.add_argument("--note", default="")
    sp.add_parser("board")
    x = sp.add_parser("codex-activity"); x.add_argument("-n", type=int, default=1)
    i = sp.add_parser("init"); i.add_argument("--title", required=True); i.add_argument("--force", action="store_true")
    v = sp.add_parser("serve"); v.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    fn = globals()["cmd_" + a.cmd.replace("-", "_")]
    if a.cmd in ("serve", "run", "codex-activity", "status", "next"):
        fn(None if a.cmd == "serve" else load(), a)
        return
    with locked():  # 状態を書き換えるコマンドは1人ずつ
        fn(None if a.cmd == "init" else load(), a)
    if a.cmd == "dispatch" and a.run and AGENTS.get(task_of(load(), a.id)["owner"], {}).get("how") in ("codex", "gemini"):
        cmd_run(load(), a)


if __name__ == "__main__":
    main()
