# WSLc Dev Container

このリポジトリ向けの WSL Containers / Dev Containers 設定です。
共通の土台は `wslc-dev-base` に置き、このリポジトリでは Python アプリ向けの最小限の追加だけを行います。

## 方針

- Dev Container は事前にビルドした `localhost/siren6-helper-dev:dev` を使います。
- ベースイメージは `localhost/wslc-dev-base:dev` を使います。
- Linux 側 venv は `.venv-linux` に作ります。
- Windows 側 venv は `.venv-win` に作り、Windows ホストに入れた uv.exe を使います。
- Windows 専用の画面キャプチャ依存 `dxcam` は Windows のみインストール対象にします。

## ベースイメージの準備

隣に `wslc-dev-base` がある場合の例です。

```powershell
cd D:\work\wslc-dev-base
& "C:\Program Files\WSL\wslc.exe" build -f Containerfile -t localhost/wslc-dev-base:dev .
```

## プロジェクトイメージの準備

WSL 側のこのリポジトリで実行します。

```bash
make build-devcontainer
```

既定では Windows 側の `C:\Program Files\WSL\wslc.exe` を WSL パス `/mnt/c/Program\ Files/WSL/wslc.exe` 経由で呼びます。別の場所にある場合は `CONTAINER_ENGINE` を変更してください。

## VS Code の設定

`Reopen in Container` のログで次のように `Start: Run:` と表示される場合、Dev Containers は Windows 側プロセスからコンテナエンジンを起動しています。

```text
Start: Run: /home/kata/bin/wslc version
spawn /home/kata/bin/wslc ENOENT
```

この場合、Linux パスではなく Windows 側から見えるパスを設定します。ただし `C:\Program Files\WSL\wslc.exe` はスペースを含むため、短い 8.3 パスを使います。

開くウィンドウ: WSL ではない通常の Windows VS Code ウィンドウ
開くファイル: `C:\Users\katao\AppData\Roaming\Code\User\settings.json`

```json
{
  "dev.containers.dockerPath": "C:\\PROGRA~1\\WSL\\wslc.exe"
}
```

このリポジトリにも補助として `.vscode/settings.json` を置いています。中身は同じ `C:\PROGRA~1\WSL\wslc.exe` です。

設定が効いているかは `Dev Containers: Show Log` で確認できます。ログ上の実行コマンドが `docker ...` や `/home/kata/bin/wslc ...` ではなく、`C:\PROGRA~1\WSL\wslc.exe ...` になっていれば OK です。

## VS Code で開く

1. WSL ではない通常の Windows VS Code ウィンドウで `D:\work\siren_helper` を開きます。
2. `Dev Containers: Reopen in Container` を実行します。

Dev Container 作成時に `.venv-linux` が作成されます。
必要に応じて依存を同期し直す場合は、コンテナ内で次を実行します。

```bash
scripts/setup-linux-venv.sh
```

## Windows venv

Windows で GUI 実行やビルド確認をする場合は、WSL ホスト側から次を実行します。

```bash
scripts/setup-windows-venv.sh
```

Windows の uv.exe が既定パス以外にある場合は、`UV_WIN` を指定します。

```bash
UV_WIN=/mnt/c/path/to/uv.exe scripts/setup-windows-venv.sh
```

Windows venv でコマンドを実行する例です。

```bash
UV_PROJECT_ENVIRONMENT=.venv-win /mnt/c/Users/katao/.local/bin/uv.exe run python -m py_compile siren6_helper.pyw
```

## バージョン管理するもの

- `.devcontainer/Containerfile` と `.devcontainer/devcontainer.json`: プロジェクト固有の追加パッケージ、マウント、起動時処理。
- `.dockerignore`: ビルドコンテキストは Containerfile に限定します。ソースコードは起動時に bind mount します。
- `.vscode/settings.json`、`scripts/`、`Makefile`: エディタ設定と構築手順。
- `.env.example`: 個人設定の項目例。実際の `.env` は Git から除外します。

`install-dotfiles`、`setup-git-identity`、`devcontainer-entrypoint` と共通 dotfiles はベースイメージから継承しています。ベース側を更新した場合は、ベースイメージとプロジェクトイメージを順にビルドし直してください。`localhost/wslc-dev-base:dev` は可変タグのため、これだけでは元のベースソースの版を特定できません。環境を固定して共有する場合は、ベースリポジトリのコミットを記録し、その版のイメージを用意して `make build-devcontainer BASE_IMAGE=<そのイメージ名>` を指定します。

## Git の接続確認

Dev Containers が転送するホストの SSH エージェントを利用します。秘密鍵やトークンは、このリポジトリやイメージにコピーしません。コンテナ内では次の順で確認します。

```bash
ssh-add -l
git ls-remote origin HEAD
git branch -vv
```

リモートを読めても `git pull` で追跡先未設定のエラーになる場合は、現在のブランチがどこから変更を取り込むかを設定します。たとえば `main` から分岐したローカル作業ブランチで `origin/main` を取り込む場合は、次を実行します。

```bash
git branch --set-upstream-to=origin/main
git pull --ff-only
```

独立したリモートブランチとして公開する場合は、公開先を確認したうえで `git push -u origin HEAD` を使います。追跡設定は各チェックアウトの `.git/config` に保存され、リポジトリのファイルとしては共有されません。
