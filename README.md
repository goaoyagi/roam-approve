# roam-approve

M5StickC PLUS SE を AI エージェントの human-in-the-loop 物理承認デバイスとして使うモノレポ。Devin CLI/Desktop の `PermissionRequest` hook → Bridge(FastAPI) → MQTT → M5StickC の経路で、エージェントの `exec` / `write` / `edit` を物理ボタン(BtnA=承認 / BtnB=却下)で承認する。

## アーキテクチャ

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
                                                                      │ M5StickC PLUS SE│  BtnA=Approve / BtnB=Reject
                                                                      └─────────────────┘
```

## フォルダ概要

- `host/bridge/` — FastAPI Bridge Server(REST + Bearer 認証 + MQTT 通知)
- `host/adapters/` — エージェント別アダプタ(hook から呼ばれる CLI、stdlib のみ)
- `device/firmware/` — PlatformIO ファームウェア(M5StickC PLUS SE)
- `tools/` — トークン生成・シークレット検査・E2E
- `infra/mosquitto/` — MQTT broker 設定

## Quick start (ホスト)

```sh
brew install uv gitleaks docker
# PlatformIO (ファーム書き込み時)
uv tool install platformio   # または brew / pipx
# Docker ランタイム例: Colima (`colima start`) または Docker Desktop

make install               # uv sync --all-packages
make gen-tokens            # .env を生成しトークンを書き込む(値は表示されない)
make up                    # mosquitto 起動 (docker compose)
# 実機が同じ LAN から Bridge に届くようにする
# .env の ROAM_BIND=0.0.0.0 を設定してから:
make bridge                # デフォルトは ROAM_BIND=127.0.0.1 / ROAM_PORT=8000
```

`make bridge` はシェルの `ROAM_BIND` / `ROAM_PORT` を uvicorn に渡します。`.env` だけ書き換えても反映されないので、LAN 公開時は `ROAM_BIND=0.0.0.0 make bridge` とするか export してください。

## 日常の開始と停止

初回セットアップ(`.env` / `config.h` / ファーム書き込み / hook)が済んだあとは、使うときだけホスト側を起動し、終わったら止めます。`make gen-tokens` や `make fw-upload` は設定変更時だけで十分です。

### 開始

```sh
# 1) Docker ランタイムが止まっている場合のみ (Colima 利用時)
colima start

# 2) MQTT (mosquitto)
cd /path/to/roam-approve
make up

# 3) Bridge (実機が同じ LAN から届くように 0.0.0.0)
ROAM_BIND=0.0.0.0 make bridge
# このターミナルは起動したままにする
```

続けて:

4. M5StickC の電源を入れる(同じ Wi-Fi)→ `roam-approve` / `waiting...`
5. Devin CLI/Desktop を起動して使う

### 停止

| 対象 | やり方 |
|---|---|
| Bridge | `make bridge` を動かしているターミナルで `Ctrl+C` |
| mosquitto | リポジトリで `make down` |
| Colima (Docker ごと止める) | `colima stop` |
| M5 | 電源オフ、または USB 抜線(待機のまま放置でも可) |
| Devin | アプリを終了(hooks 設定はそのままでよい) |

Bridge だけ止めれば承認フローは止まります。mosquitto も止めると MQTT 通知も止まります。

### 状態確認 (Docker / Bridge / ポート)

```sh
# Colima (Docker ランタイム)
colima status

# Docker デーモンに届くか
docker info >/dev/null && echo 'docker ok' || echo 'docker down'

# mosquitto コンテナ
docker compose ps
# 期待: roam-approve-mosquitto-1 が Up、PORTS に 0.0.0.0:1883->1883/tcp

# MQTT ポートが開いているか
nc -z -v 127.0.0.1 1883

# Bridge
curl -sS http://127.0.0.1:8000/healthz
# 期待: {"status":"ok"}

# 誰が 8000 / 1883 を聴いているか
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:1883 -sTCP:LISTEN
```

Colima 利用時に `docker` がソケットを見つけられない場合は、次を試してください。

```sh
export DOCKER_HOST="unix://${HOME}/.colima/docker.sock"
# または: docker context use colima
```

## 実機セットアップ (M5StickC PLUS SE)

1. `cp device/firmware/include/config.example.h device/firmware/include/config.h`
2. `config.h` を埋める(gitignore 済み。値をコミットしない):

   | 定数 | 内容 |
   |---|---|
   | `WIFI_SSID` / `WIFI_PASSWORD` | 実機が乗る Wi-Fi |
   | `MQTT_HOST` | PC の LAN IP(例 `192.168.1.122`)。`127.0.0.1` は不可 |
   | `MQTT_PORT` | 通常 `1883` |
   | `BRIDGE_URL` | `http://<同じ LAN IP>:8000` |
   | `DEVICE_TOKEN` | `.env` の `ROAM_DEVICE_TOKEN` と同じ値 |

3. USB 接続して書き込み:

   ```sh
   make fw-upload   # または cd device/firmware && pio run -e m5stickc-plus-se -t upload
   ```

4. 成功時の待機画面: `roam-approve` / `waiting...`(同期失敗時は 3 行目に `bridge err`)

ファームウェアは `device/firmware/lib/ApprovalApp` の純粋 C++ ロジックと M5StickC 用 HAL で構成され、`make fw-test` で native テストを実行できます。匿名 MQTT は更新の合図としてのみ扱い、表示・承認対象は device トークン付き HTTP 同期で取得した pending 一覧に限定します。

### ボタン配置 (画面を横向き・文字が読める向き)

| ボタン | 位置 | 役割 |
|---|---|---|
| **BtnA** | 本体正面の大きいボタン(横向きだとだいたい右下) | 承認 |
| **BtnB** | 側面の小さいボタン(画面上側・電源ボタンの隣) | 却下 |

電源ボタンは使いません。

### 省電力 (実機確認済み)

- 無操作約 **30 秒** でバックライトを落とす(`idleDimMs`)。あわせて CPU 80 MHz・Wi-Fi sleep を有効化
- 通知(新規 pending)やボタン操作で復帰
- **暗転中の 1 回目のボタンは復帰だけ**。承認/却下は明るい状態でもう 1 回押す
- バッテリー持続の長時間実測は未実施(用途・通知頻度依存)。待機中心なら暗転後の消費が支配的

## Using with Devin CLI/Desktop

CLI と Desktop は同じ `PermissionRequest` hook 経路です。

1. hook CLI をインストールして `roam-approve-hook` を PATH に置く:

   ```sh
   uv tool install ./host/adapters   # リポジトリルートから
   command -v roam-approve-hook       # PATH 確認(見つからなければ uv tool update-shell)
   ```

2. 利用プロジェクトに `.devin/hooks.v1.json` を置く。

   - **CLI** (シェルで env を export できる場合): `host/adapters/examples/devin-cli/hooks.v1.json` をコピーし、`ROAM_BRIDGE_URL` / `ROAM_AGENT_TOKEN` / `ROAM_WAIT_S` を親プロセスに設定
   - **Desktop** (GUI は login-shell の env を引き継がない): このリポジトリ同様 `bash tools/devin_desktop_hook.sh` を呼ぶ hooks にする(ラッパーがリポジトリの `.env` を読んで hook を起動)

   | 変数 | 内容 |
   |---|---|
   | `ROAM_BRIDGE_URL` | Bridge の URL(デフォルト `http://127.0.0.1:8000`) |
   | `ROAM_AGENT_TOKEN` | agent 用 Bearer トークン(必須) |
   | `ROAM_WAIT_S` | hook が M5 の応答を待つ秒数(**推奨 240**、最大 280。超過分はクランプ) |

3. Devin で `exec` / `write` / `edit` の PermissionRequest が発生すると M5StickC に表示される。

   - **Ask モード**ではコード変更・exec 自体がほぼ走らない
   - **Accept Edits (Code) モード**でもシェルは本来 Prompt だが、セッションで一度 Allow したコマンドや安全と判定された操作は IDE 側だけで通り、M5 に来ないことがある
   - 確認時は **新しいセッション**で `/normal` にし、例: `touch /tmp/roam-desktop-ok && date` のように実行させる
   - `.devin/config.json` に `"ask": ["exec","write","edit"]` を置くと PermissionRequest を強制しやすい
   - Desktop ラッパーの起動ログ: `$TMPDIR/roam-approve-desktop-hook.log`(未作成なら hook 未発火)

   `ask_user_question` などの Q&A は PermissionRequest ではないためデバイスには届かない。

### hook timeout の推奨値

| 層 | 値 | 理由 |
|---|---|---|
| `hooks.v1.json` の `timeout` | **300** (例のまま) | Devin が hook プロセスに許す上限 |
| `ROAM_WAIT_S` | **240** (デフォルト) | Bridge long-poll 待ち。HTTP 余裕 ~20s を見て 300 未満に収める |
| 上限クランプ | 280 | adapter 側のハード上限 |

hook は同期実行のため、待機中は通常の Permission プロンプトより先に hook 完了を待ちます。タイムアウト/Bridge 不通時は stdout なし + exit 0 で **通常プロンプトへフォールバック**します(実機 + hook CLI で確認済み)。

### 動作

| Bridge の結果 | hook の stdout | Devin の動作 |
|---|---|---|
| approved | `{"decision":"approve"}` | 承認 |
| rejected | `{"decision":"block","reason":"Rejected on M5StickC"}` | ブロック |
| expired / タイムアウト / Bridge エラー | (出力なし, exit 0) | 通常プロンプトへフォールバック |

## トラブルシュート

| 症状 | 確認すること |
|---|---|
| 待機画面のまま要求が出ない | Bridge に実機 IP から `GET /v1/requests?status=pending` が来ているか。`BRIDGE_URL` / `DEVICE_TOKEN` が `.env` と一致しているか。`ROAM_BIND=0.0.0.0` で Bridge を起動しているか |
| `bridge err` | PC のファイアウォール、mosquitto(`make up`)、Wi-Fi、`MQTT_HOST` / `BRIDGE_URL` の LAN IP |
| USB が見えない | ケーブル・ポート。`pio device list` で `M5stack` / `usbserial` を確認 |
| `docker compose` が無い | Docker Compose v2 プラグイン、または Colima + `brew install docker-compose` |
| ボタン 1 回で決まらない | 暗転中は 1 回目が復帰のみ(上記「省電力」) |
| MQTT が頻繁に取り直される | 暗転時の Wi-Fi sleep による再接続。表示・承認は HTTP 同期が正なので通常は問題にならない |

## 実装状況

| Step | 内容 | 状態 |
|---|---|---|
| 1 | スキャフォールド + セキュリティ設定 + CI | 完了 |
| 2 | Bridge 実装 + pytest | 完了 |
| 3 | Adapters(devin-cli) + hooks 設定例 | 完了 |
| 4 | Firmware(ApprovalApp + native テスト + M5 HAL) | 完了 |
| 5 | フェイクデバイス + E2E | 完了 (`make sim` / `make e2e` / `make integration`) |
| 6 | 実機検証 + README 仕上げ | 完了 (承認/却下/hook CLI/Desktop/timeout/省電力ウェイクを実機確認) |

## Security notes

- このリポジトリは **public**。実値シークレットは `.env` と `device/firmware/include/config.h` のみに置き、どちらも gitignore 済み。トークン生成は `make gen-tokens` を使い、値は stdout に出さない。
- Bridge はデフォルト `127.0.0.1` にバインド。同じ LAN の M5 から届けるときだけ `ROAM_BIND=0.0.0.0`。インターネット公開はせず Tailscale 等を推奨。
- MQTT は LAN 内匿名(v1)。LAN 外に出す場合は `infra/mosquitto/mosquitto.conf` 内の TLS/認証雛形を有効化する。

## License

MIT — see [LICENSE](LICENSE)
