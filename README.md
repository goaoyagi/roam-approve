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

## Quick start

```sh
brew install uv gitleaks   # platformio は必要になったら別途
make install               # uv sync --all-packages
make gen-tokens            # .env を生成しトークンを書き込む(値は表示されない)
make up                    # mosquitto 起動 (docker)
make bridge                # Bridge を 127.0.0.1:8000 で起動
```

ファームウェアの書き込み:

```sh
cp device/firmware/include/config.example.h device/firmware/include/config.h
# config.h に Wi-Fi / MQTT_HOST / BRIDGE_URL / DEVICE_TOKEN を記入
cd device/firmware && pio run -e m5stickc-plus-se -t upload
```

## Using with Devin CLI/Desktop

1. `host/adapters/examples/devin-cli/hooks.v1.json` を、承認を有効化したいプロジェクトの `.devin/hooks.v1.json` にコピーする
2. そのプロジェクトを起動するシェル環境で `ROAM_BRIDGE_URL` と `ROAM_AGENT_TOKEN` を設定する(hook は親プロセスの env を継承)

## 実装状況

| Step | 内容 | 状態 |
|---|---|---|
| 1 | スキャフォールド + セキュリティ設定 + CI | 完了 |
| 2 | Bridge 実装 + pytest | 完了 |
| 3 | Adapters(devin-cli) + hooks 設定例 | 未着手 (Issue 参照) |
| 4 | Firmware(ApprovalApp + native テスト + M5 HAL) | 未着手 (Issue 参照) |
| 5 | フェイクデバイス + E2E | 未着手 (Issue 参照) |
| 6 | 実機検証 + README 仕上げ | 未着手 (Issue 参照) |

## Security notes

- このリポジトリは **public**。実値シークレットは `.env` と `device/firmware/include/config.h` のみに置き、どちらも gitignore 済み。トークン生成は `make gen-tokens` を使い、値は stdout に出さない。
- Bridge はデフォルト `127.0.0.1` にバインド。外部から使う場合はポート開放ではなく Tailscale 等のオーバーレイネットワークを推奨。
- MQTT は LAN 内匿名(v1)。LAN 外に出す場合は `infra/mosquitto/mosquitto.conf` 内の TLS/認証雛形を有効化する。

## License

MIT — see [LICENSE](LICENSE)
