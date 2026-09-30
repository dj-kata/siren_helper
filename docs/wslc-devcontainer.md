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

## コンテナから Windows で実行・ビルドする

通常の WSL と異なり、この WSLc コンテナには `/mnt/c` や Windows exe の
相互運用機構がありません。`uv.exe` のマウントだけでは実行できません。
既存の `workspaceMount` で共有したファイルを使い、Windows 側の待受に処理を依頼します。
追加のマウント・ネットワークポートは不要です。自動起動設定の反映には Windows 側から Dev Containers で開き直してください。
Windows 側とコンテナ側で同じチェックアウトを参照する必要があります。

1. **Windows 側の VS Code** でプロジェクトを開き、`Dev Containers: Reopen in Container` を実行します。

   `initializeCommand` が Windows 側で待受を非表示で起動します。
   PowerShell のウィンドウを開いたままにする必要はありません。
   起動済みの待受は再利用し、同時に開いた場合も起動処理を直列化します。
   初回の切り替え時は、以前手動起動した待受を Ctrl+C で終了してから開き直してください。
   WSL 内の VS Code や `wslc run` 単独では、この Windows 側フックは動作しません。

2. **コンテナ側** で実行します。

   ```bash
   make windows-check  # Windows uv のバージョン確認
   make windows-sync   # .venv-win の作成・依存同期
   make test           # Windows 上で GUI 起動（自動テストではありません）
   make build          # Windows 上で cx_Freeze ビルド
   make                # 必要ならビルドし、コンテナ側の 7z で ZIP 作成
   ```

`run` / `build` も uv が依存を同期するため、`windows-sync` は必要なときだけで構いません。
Windows 側の uv は常に `.venv-win` を使用し、コンテナの `.venv-linux` と分離します。
ビルド出力は `siren6_helper/` です。Linux 側の連携クライアントは
Linux 版 uv で Python 標準ライブラリのみを使って動作します。

uv の既定パスは Windows の `%USERPROFILE%\.local\bin\uv.exe` です。
変更する場合は `.env` に次のように記載します（環境変数 `WINDOWS_UV_PATH` が優先）。

```dotenv
WINDOWS_UV_PATH=C:\Users\katao\.local\bin\uv.exe
```

値は Windows の絶対パスです。空白入りのパスと外側の引用符に対応し、
`%USERPROFILE%` などの変数展開や末尾コメントには対応しません。
この設定は Windows 側の処理ごとに読み込むため、コンテナ再作成は不要です。
Dev Containers が `.env` を自動的にマウント設定へ展開する構成ではありません。

標準出力・標準エラーと終了コードはコンテナに返ります。タスクは一度に一つ実行し、
アプリ起動中の次の依頼は終了まで待機します。コンテナの Ctrl+C は該当タスクの
Windows プロセスツリーの停止を要求します。手動で前面起動した待受の Ctrl+C も実行中タスクを停止します。
待受未起動・停止時はエラーになります。起動後にコマンドを再実行してください。
待受再起動時は古い依頼を再実行しません。

待受は VS Code / コンテナを閉じた後も動作し、次回の接続で再利用します。
Windows のログアウトで終了します。明示的に停止する場合は Windows の PowerShell で実行します
（実行中の GUI・ビルドも停止します）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage-windows-host.ps1 stop
```

手動で非表示起動する場合は末尾の `stop` を省略します。
起動失敗時は `.windows-bridge/host.stderr.log`、通常の待受ログは
`.windows-bridge/host.stdout.log` を確認してください。
アプリの出力はこれまで通りコンテナの端末へ返ります。

自動起動には Dev Containers のホスト側
[`initializeCommand`](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md#lifecycle-scripts)
を使用します。WSLc 自体に常駐処理を登録する変更ではありません。


`.windows-bridge/` は Git 対象外の一時的な依頼・ログ置き場です。
中断した依頼が残った場合は、待受とクライアントを終了してから削除できます。
待受は共有ワークスペースから固定の `check` / `sync` / `run` / `build` のみ受け付け、
そのワークスペースのコードを Windows ユーザー権限で実行します。

Windows 側だけで実行することもできます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows.ps1 run
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows.ps1 build
```

従来の `scripts/setup-windows-venv.sh` は Windows 相互運用が有効な通常の WSL 向けです。
WSLc コンテナでは上記の `make windows-sync` を使用してください。

## バージョン管理するもの

- `.devcontainer/Containerfile` と `.devcontainer/devcontainer.json`: プロジェクト固有の追加パッケージ、マウント、起動時処理。
- `.dockerignore`: ビルドコンテキストは Containerfile に限定します。ソースコードは起動時に bind mount します。
- `.vscode/settings.json`、`scripts/`、`Makefile`: エディタ設定と構築手順。
- `.env.example`: 個人設定の項目例。実際の `.env` は Git から除外します。

`install-dotfiles`、`setup-git-identity`、`devcontainer-entrypoint` と共通 dotfiles はベースイメージから継承しています。ベース側を更新した場合は、ベースイメージとプロジェクトイメージを順にビルドし直してください。`localhost/wslc-dev-base:dev` は可変タグのため、これだけでは元のベースソースの版を特定できません。環境を固定して共有する場合は、ベースリポジトリのコミットを記録し、その版のイメージを用意して `make build-devcontainer BASE_IMAGE=<そのイメージ名>` を指定します。

## Git のコミット名・メール

設定元は **ホストの通常の WSL** です。Windows Git のインストールは不要です。
Windows 側の `initializeCommand` が `wsl.exe` を使い、既定ディストリビューションで
プロジェクトのパスを `wslpath` により変換してから `git config --get user.name` /
`user.email` を実行します。`include` / `includeIf` はその WSL の Git が解決します。
取得した二項目を Git 対象外の `.windows-bridge/git-identity.config` へ保存し、
作成時・接続時に `scripts/setup-git-identity.sh` がコンテナのグローバル設定へ反映します。
これは自動生成されるコピーであり、名前・メールを二か所で手動管理する必要はありません。
認証ヘルパーなどの既存設定は保持し、リポジトリ固有の `user.*` があればそちらが優先されます。

取得先を既定以外の WSL にする場合は、Windows 側の環境変数
`GIT_IDENTITY_WSL_DISTRO` にディストリビューション名を指定して VS Code を起動してください。
取得に失敗した場合は、空ファイルで成功扱いにせず初期化をエラーにします。

Windows 側の VS Code から `Reopen Folder Locally` → `Reopen in Container` で同期します。
待受が動いていれば、コンテナ内から現在の設定を再取得・反映することもできます。

```bash
make windows-check
scripts/setup-git-identity.sh
git config --show-origin --get user.name
git config --show-origin --get user.email
```

ホスト連携を使わず直接コンテナを起動する場合は、従来のベース側
`setup-git-identity` による `.env` の `GIT_USER_NAME` / `GIT_USER_EMAIL` の補完も残しています。

### ベースイメージへの共通化

現在の同期スクリプトはこのリポジトリにあります。複数の派生プロジェクトで同じ処理を
コピーして管理する形を避けるには、`wslc-dev-base` 側へ共通処理を移す必要があります。
ベースの `devcontainer.json` 自体は `FROM` では継承されません。
一方、[Dev Container のイメージメタデータ](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainer-reference.md#image-metadata)
を使えば、マウント・コンテナ内の接続時処理などはベースイメージに集約できます。
ホスト側でイメージ処理に先行する `initializeCommand` は、このメタデータの継承対象ではありません。
WSL からの取得を共通のホスト側起動処理にまとめるか、ホスト設定を直接マウントする構成を
ベース側で設計する必要があります。`FROM` 単独でホストの設定ファイルへアクセスできるわけではありません。

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

## Python 環境の初期化と再同期

VS Code は `postCreateCommand` による依存の同期が完了してから接続します。
コンテナ内の Python Environments の探索先は `.venv-linux` に設定しています。
Windows 用の `.venv` や `.venv-win` は Linux では実行できません。
コンテナ設定の変更は `Dev Containers: Rebuild Container` で反映してください。

`scripts/setup-linux-venv.sh` は既存の環境を先に作り直さず、`uv sync` で
作成・同期します。再試行時に既存のパッケージを先に消去するのを避けるためです。
Linux 版 uv と `.venv-linux` は Codex の調査・静的検査・Linux 対応テスト用です。
アプリ本体の実行・GUI デバッグ・Windows 固有機能の検証には Windows 版 uv と
`.venv-win` を使用します。Linux 上の検査は Windows 上の動作確認を代替しません。

## ターミナルのキーバインド

`EDITOR` / `VISUAL=vim` による vi モードの自動選択を上書きし、
`/etc/zsh/zshrc` の `bindkey -e` で Emacs キーバインドを選択します。
Ctrl-A / E（行頭・行末）、Ctrl-B / F（左右）、Ctrl-P / N（履歴）、
Ctrl-K（カーソル以降の削除）、Ctrl-U（行全体の削除）、Ctrl-W（前の単語の削除）、Ctrl-Y（貼り戻し）などを利用できます。
fzf の設定はその後に読み込まれるので、Ctrl-R の fzf 履歴検索も維持します。
`EDITOR` 自体は変更しないため、Git などから起動するエディタは引き続き vim です。

新しいターミナルから有効になります。既存のターミナルでは次を実行してください。

```zsh
bindkey -e
bindkey -M emacs '^R' fzf-history-widget
```

既存のターミナルが vi モードで起動していた場合、fzf の割り当てが vi 側だけに
登録されているため、`bindkey -e` 単独では Ctrl-R が通常の履歴検索に戻ります。
上記の二行目で Emacs 側にも登録します。新しいターミナルでは起動時に
Emacs モードが選択されてから fzf が登録されるため、この操作は不要です。

今後コンテナを作り直す場合も維持するには、変更後の Containerfile で
`make build-devcontainer` を行い、そのイメージでコンテナを再作成してください。
