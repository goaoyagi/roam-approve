# AGENTS.md

## Overview

roam-approve は、M5StickC PLUS SE を AI エージェントの human-in-the-loop 物理承認デバイスとして使うためのモノレポです。Devin CLI/Desktop の `PermissionRequest` hook → Bridge(FastAPI, Bearer トークン認証) → MQTT → M5StickC PLUS SE の経路で、エージェントの操作を物理ボタンで承認するか、PC(Devin desktop の通常承認プロンプト)へ差し戻します。新しいエージェントの追加は `host/adapters` 内の 1 モジュールで完結します。

```
┌──────────────┐  stdin(JSON)   ┌──────────────────┐  POST /v1/requests   ┌─────────────┐
│ Devin CLI /  │──────────────▶│ adapter          │ (Bearer: agent token)│ Bridge      │
│ Desktop      │◀──────────────│ roam-approve-hook│────────────────────▶│ (FastAPI)   │
│ Permission-  │ stdout decision│ devin-cli        │◀── long-poll wait ──│             │
│ Request hook │               └──────────────────┘                      └──┬───────▲──┘
└──────────────┘                                                            │MQTT    │HTTP (Bearer: device token)
                                                               roam/approval/request  POST /v1/requests/{id}/decision
                                                                            ▼        │
                                                                      ┌─────────────────┐
                                                                      │ M5StickC PLUS SE│  BtnA=Approve / BtnB=PC
                                                                      └─────────────────┘
```

## Repository layout

`host/` = PC / サーバ(Raspberry Pi, Docker 等)で動くもの、`device/` = ハードウェアで動くもの、`tools/` = 開発・検証ツール。

```
roam-approve/
├── host/
│   ├── bridge/                      # FastAPI Bridge Server(uv workspace member)
│   │   ├── src/roam_approve_bridge/ # main.py / api.py / auth.py / models.py / store.py / config.py / notifier/
│   │   └── tests/                   # pytest + httpx。notifier=memory で HW/MQTT 不要
│   │       └── integration/         # 実 mosquitto 結合(@pytest.mark.integration、未起動時 skip)
│   └── adapters/                    # エージェント別アダプタ(hook から呼ばれる軽量 CLI、stdlib のみ)
│       ├── src/roam_approve_adapters/ # cli.py / client.py / base.py / registry.py / devin_cli.py
│       ├── examples/devin-cli/hooks.v1.json
│       └── tests/
├── device/
│   └── firmware/                    # PlatformIO (M5StickC PLUS SE)
│       ├── platformio.ini           # env:m5stickc-plus-se / env:native
│       ├── src/main.cpp             # 配線のみ: HAL(M5 実装) + ApprovalApp
│       ├── src/hal_m5/              # M5StickC / Wi-Fi / MQTT / HTTP の HAL 実装
│       ├── lib/ApprovalApp/         # 純粋ロジック(Arduino 非依存)
│       ├── lib/Hal/                 # IDisplay / IButtons / IMqtt / IHttp(get/post) / IPower / IClock
│       ├── test/test_app/           # env:native で走る Unity テスト
│       └── include/config.example.h # → config.h にコピー(config.h は gitignore)
├── tools/
│   ├── gen_tokens.sh / check_secrets.sh
│   └── e2e/                         # fake_device.py + test_e2e.py (@pytest.mark.e2e)
├── infra/mosquitto/mosquitto.conf   # LAN 内匿名。TLS/認証雛形はコメント
└── docker-compose.yml               # mosquitto (+ bridge は profile 指定)
```

## Commands

| コマンド | 内容 | 必要なもの |
|---|---|---|
| `make install` | `uv sync --all-packages` | uv |
| `make up` / `make down` | mosquitto の起動/停止 | docker |
| `make bridge` | Bridge を `127.0.0.1:8000` で起動 | uv |
| `make test` | `pytest host` + `check-secrets` | uv, gitleaks |
| `make lint` | `ruff check host tools` | uv |
| `make fw-build` | `pio run -e m5stickc-plus-se` | pio |
| `make fw-test` | `pio test -e native`(HAL モック) | pio |
| `make fw-upload` | 実機書き込み | pio |
| `make sim` | フェイクデバイス(`tools/e2e/fake_device.py`)。`ARGS='--auto approve'` 可 | uv, mosquitto, Bridge |
| `make e2e` | hook → Bridge → MQTT → fake device の E2E | uv, docker |
| `make integration` | Bridge + 実 mosquitto 結合テスト(`pytest -m integration`) | uv, docker |
| `make gen-tokens` | `.env` にトークン生成(値は表示しない) | openssl |
| `make check-secrets` | 追跡ファイルのシークレット確認 + gitleaks | gitleaks |

## Protocol

### Bridge REST(`/v1`)— `/healthz` 以外は `Authorization: Bearer <token>` 必須

| Method | Path | トークン | 用途 |
|---|---|---|---|
| POST | `/v1/requests` | agent | 要求登録 `{agent, session_id, title, lines[], timeout_s}` → `{id}`(uuid4) |
| GET | `/v1/requests/{id}/wait?timeout_s=` | agent | long-poll → `{status: approved|rejected|pending|expired, reason?}` |
| POST | `/v1/requests/{id}/decision` | device | `{decision: approve|reject, source}` |
| GET | `/v1/requests?status=pending` | device | 遅延接続デバイス/シミュレータの同期 |
| GET | `/healthz` | なし | 監視 |

### MQTT トピック

- `roam/approval/request/{id}`(retained、要求ごと): `{id, agent, title, lines[], expires_at}` — コマンド全文ではなく要約のみ(title 64 文字・lines 最大 6 行 × 40 文字に切り詰め。firmware の MQTT バッファ 4096 バイトに収めるため)。デバイスは `roam/approval/request/+` を購読
- `roam/approval/resolved`: `{id, status}` — デバイスの表示クリア用。決定/期限切れ時に該当 `{id}` の retained も空で上書き
- Bridge は起動・再接続時に `roam/approval/request/+` を購読し、自分が pending として知らない retained(再起動前の残骸)を空で上書きする
- 解決済み要求は 600 秒保持後に Bridge のメモリから削除される(以降の `wait` / `decision` は 404)
- MQTT は LAN 内匿名(v1)で誰でも publish できるため、**MQTT の内容は信頼しない**。デバイスは MQTT 受信を「更新の合図」としてのみ扱い、表示・承認の対象は device トークン付き `GET /v1/requests?status=pending` で取得したものに限る(下記 Design rules 参照)

### Devin CLI hook(利用側プロジェクトの `.devin/hooks.v1.json`)

```json
{ "PermissionRequest": [ { "matcher": "^(exec|write|edit)$",
    "hooks": [ { "type": "command", "command": "roam-approve-hook devin-cli", "timeout": 300 } ] } ] }
```

- parse: `tool_name` → title、`tool_input.command` / `file_path` → 画面幅(≒20 文字 × 6 行)に要約
- デバイスのフォントは ASCII のみのため、parse で NFC 正規化後に連続した非 ASCII 部分を 1 つの目印に縮める: すべて日本語なら `<JA:n>`、それ以外(絵文字・全角英数などの紛らわしい文字を含む)は `<?:n>`(n はコードポイント数)。目印は行をまたいで分割しない。翻訳はしない(承認対象をそのまま見せるため)
- render: approved → `{"decision":"approve"}`、rejected / expired / Bridge 不達 → **何も出力せず exit 0**(通常プロンプトへフォールバック、安全側)。M5 の BtnB(画面表示 `B:PC`)は Bridge には `reject` を送るが、hook は block せず desktop の通常承認プロンプトへ差し戻す(M5 側では拒否できない)
- トークンと Bridge URL は環境変数 `ROAM_BRIDGE_URL` / `ROAM_AGENT_TOKEN`(hook は親プロセスの env を継承)

## Design rules

- **Bridge は正規化された `ApprovalRequest` しか知らない**。エージェント固有の差分は `host/adapters` 内の parse/render に閉じ込める。Bridge と firmware は原則触らない。
- **firmware のロジックは `lib/ApprovalApp` に置き、Arduino 非依存・`env:native` でテスト可能にする**。`src/main.cpp` は配線のみ。ハード依存は `lib/Hal` のインタフェース(IDisplay / IButtons / IMqtt / IHttp / IPower / IClock)越しに限定。`IHttp` は `postJson` と `getJson` を提供し、`getJson` はレスポンス本文を `IByteReader` でストリームとして渡す(pending 一覧は全体をバッファせず 1 要素ずつ解析する)。
- **firmware は MQTT payload を表示・承認に使わない**。`roam/approval/request` / `roam/approval/resolved` を受信したら、device トークン付き `GET /v1/requests?status=pending` を呼んで状態を同期し、HTTP で取得した `id` / `title` / `lines` のみ表示する。HTTP の一覧にない `id` は表示せず、decision も送らない。起動時・再接続時にも同じ同期を行う。`lib/ApprovalApp` の native テストで「偽 MQTT payload を表示しない」「一覧にない id を承認しない」を検証する。
- **adapters はランタイム依存ゼロ(stdlib のみ)**。hook 起動ごとに実行されるため外部パッケージを入れない。
- **M5 に届くのは `PermissionRequest` かつ `matcher: ^(exec|write|edit)$` のみ**。`ask_user_question` などの Q&A 形式の問い合わせは PermissionRequest ではないため **Bridge に届かず IDE で完結する**。質問待ちを M5 に通知だけしたい場合は `PreToolUse` + `matcher: ^ask_user_question$` + Bridge `kind: notify`(v2 候補)。

## Adding a new agent

| 追加対象 | 触るファイル | 触らない |
|---|---|---|
| Claude Code(hook 型) | `host/adapters/.../claude_code.py`(render は `hookSpecificOutput.decision.behavior: allow/deny`)、`registry.py` 1 行、`examples/claude-code/settings.json`、tests | bridge, firmware |
| Devin Cloud(ポーリング型) | `devin_cloud.py`(常駐: blocked 検知 → client で登録 → Message API で返答)、`cli.py` の watch サブコマンド、`.env.example` に API キー名 | bridge, firmware |
| HTTP を叩ける任意エージェント | adapter 不要。`POST /v1/requests` を直接呼ぶ(汎用 Webhook 口) | — |
| Bridge を触る例外 | 承認/却下以外の選択肢(3 択等)が必要になった時のみ `models.options` + firmware 表示 | — |
| v2 候補: 質問待ち通知 | `PreToolUse` + `matcher: ^ask_user_question$` の hook、Bridge に `kind: notify`、firmware でブザー/表示のみ(決定は IDE) | — |

追加チェックリスト:
1. `base.AgentAdapter` を実装(parse / render)
2. `registry` に登録
3. `examples/<agent>/` に設定例を追加
4. parse/render の単体テストを追加
5. README の対応表を更新

`agent` 名はデバイス画面に表示されるので短く一意に。

## Security

詳細は [.devin/rules/security.md](.devin/rules/security.md) を参照。要点:

- agent 用 / device 用トークンを分離し、`secrets.compare_digest` で比較
- Bridge のデフォルト bind は `127.0.0.1`。外部公開はポート開放ではなく Tailscale 等を使う
- 実値は `.env`(host)と `device/firmware/include/config.h`(device)のみに置く。リポジトリには `.env.example` / `config.example.h` だけ
- 多層防御: `.gitignore` → `.devin/config.json` permissions.deny → pre-commit(gitleaks) → CI(gitleaks action) → GitHub Secret Scanning/Push Protection → `make gen-tokens`(stdout に値を出さない)→ `make check-secrets`

| 層 | 誰が実行 | 仕組み |
|---|---|---|
| 置き場所 | 設計 | 実値は `.env` と `include/config.h` のみ |
| .gitignore | git | `.env`, `.env.*`(`!.env.example`), `**/include/config.h`, `*.local.json` |
| Devin permissions | Devin CLI/Desktop | `.devin/config.json` の `deny` で実値を読み書き不可 |
| pre-commit | `git commit` 時 | gitleaks がコミットを拒否 |
| GitHub Actions | push/PR 時 | gitleaks action + `make test` |
| Secret Scanning | GitHub | 既知パターンは push 自体をブロック |
| rules / gen-tokens | エージェント/人 | 直書き禁止、`make gen-tokens`、テストは `test-token` |
| check-secrets | 手動補助 | 追跡確認 + gitleaks |
| firmware 代替 | 設計 | `build_flags` で `${sysenv.ROAM_DEVICE_TOKEN}` を注入 |

## Verification

PR 前に `make test`(pytest + check-secrets)と `make lint` が通ること。firmware 変更時は `make fw-test` と `make fw-build` も。CI は gitleaks + `ruff check host tools` + `pytest host` を実行する。
