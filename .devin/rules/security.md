# セキュリティルール

このリポジトリは public です。以下を厳守してください。

- **トークン分離**: `ROAM_AGENT_TOKEN`(adapter/hook 用)と `ROAM_DEVICE_TOKEN`(device/simulator 用)は別値。Bridge は `secrets.compare_digest` で比較する。
- **デフォルト bind は `127.0.0.1`**。LAN 公開は `ROAM_BIND=0.0.0.0` を明示的に設定した場合のみ。外部公開にはポート開放ではなく Tailscale 等を使う。
- **ハードコード禁止**: トークン、Wi-Fi SSID、パスワードをソースコード・テスト・README・コミットメッセージ・ログ出力に書かない。
- **トークン生成は `make gen-tokens`** を使う。値を stdout に表示しない。
- **テストではダミー値 `test-token`** を使う。
- **実値の置き場所は 2 つだけ**: `.env`(host 側)と `device/firmware/include/config.h`(firmware 側、`device/firmware/include/config.example.h` からコピー)。どちらも gitignore 済み。
- **トークン値を stdout / ログに print しない**。
