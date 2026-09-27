# studio.py：複数 AI の分担ボード

状態の正本は `tasks.json`（統括だけが書く）。1つの作業＝`tasks/<ID>_<名前>/brief.md`（依頼書）→ `報告.md`（結果）。

| コマンド | すること |
|---|---|
| `init --title 題名` | 今いるフォルダに標準の工程の tasks.json を作る |
| `status` / `next` | 工程ごとの一覧／今すぐ着手できる作業 |
| `brief T03` | 依頼書のひな形を作る |
| `dispatch T03` | 担当に渡す（前提が終わっていない・従量課金の承認がない・出力先がすでにある、のときは止める） |
| `run T03` | 渡し済みの Codex CLI / Gemini CLI の作業を実行する（tasks.json は書かないので並べて走らせてよい） |
| `sync` | 報告.md を読んで状態を進め、受け入れ条件を点検する |
| `check T03` / `approve T03 [--user]` / `block T03` | 点検／完了にする（人の判断が要る作業は `--user`）／詰まりにする |
| `serve [--port 8765]` | 看板ボード（http://127.0.0.1:8765/）。人が OK・差し戻し・判断・メモ・カードの追加をする。127.0.0.1 だけで待ち受け、よそのサイトからの操作は断る |
| `board` | 読むだけの board.html を書き出す |
| `codex-activity` | 手元の Codex のセッションのログ（`~/.codex/sessions`）を読んで、Codex アプリが今している作業を表示する |

担当の種類：`claude-main`（統括）・`claude-sub:<type>`（Claude のサブエージェント）・`codex-cli`（`codex exec`。ChatGPT アプリ同梱の CLI があればそれを使う）・`codex-app`（依頼文を貼る）・`gemini-cli`（従量課金。承認が要る）・`grok`・`user`。
