# siren6_helperについて
風来のシレン6向けの識別支援ツールです。Windows(64bit)で動作します。

# できること
## アイテムの値段識別補助
このようなGUIにより、アイテムの価格表を確認することができます。  
また、識別済みアイテムをチェックすることもできます。
画面下部の手動サーチ欄より候補アイテムを検索できます。

<img width="1664" alt="Image" src="https://github.com/user-attachments/assets/42c8c0d4-e39e-4ba9-8b2d-2f2a8d121978" />  

## モンスターテーブル確認
各階層のモンスターテーブルを確認できます。
<img width="1672" alt="Image" src="https://github.com/user-attachments/assets/376405dc-04cd-4e55-ba2f-83f6b9a552b7" />

## 配信向けオーバーレイ
OBSにドラッグ&ドロップするだけで使える情報表示用HTMLを同梱しています。
このHTMLでは、その階層に出現するモンスターのアイコンや、
未識別アイテムの候補を表示できます。
<img width="1661" alt="Image" src="https://github.com/user-attachments/assets/97bec4c7-98c9-42b8-b7db-e7c9dc3c9155" />

## OBS連携機能
OBSWebsocket経由でゲーム画面を読み取り、
店における未識別アイテムの候補や、現在の階層における出現モンスターの一覧を**自動で更新することもできます**。
(出現モンスターについては現状通常神髄及び超・神髄のみ対応)

現時点では店内でアイテム欄を選択した場合のみですが、識別済みのアイテムを自動で反映することもできます。

未識別の武器・盾についても修正値を表示します。

また、冒険失敗時のリセットボタン押下も自動で行います。

## トライごとのメモの保存
以下のように、識別情報とは別にメモが必要な場合にテキストを書き込めるようになっています。  
救助パス作成時などにも役に立つかと思います。  
メモ欄は冒険用と全体用の2つを用意しており、前者はリセット(=乙)時に消えるようにしています。
<img width="970" alt="Image" src="https://github.com/user-attachments/assets/28a3272c-a086-4f24-87e6-f2bceac41c95" />

<!-- ## 装備印、識別状況の情報をOBSへリアルタイムに反映
OBSを使った配信の補助用に、現在の装備についた印をチェックするとOBS側に反映してくれる仕組みも搭載しています。  
同梱のstat.html、soubi.htmlをOBSのブラウザソースで取り込むことで使えます。
![image](https://user-images.githubusercontent.com/61326119/231686063-afe06bc4-f502-4e59-b9ce-1cf1357e6287.png)
![image](https://user-images.githubusercontent.com/61326119/231687238-1e016ea8-482c-4497-bd99-928f1f606060.png)

## モンスターテーブルの表示
原始のモンスターテーブルを表示する機能も搭載しています。  
個人的にきついフロアは紫、何らかの草を稼げそうなフロアは緑、にぎり系がいるフロアは青、のような色付けをしています。
![image](https://user-images.githubusercontent.com/61326119/233817095-6f0febab-c0e4-4236-9303-b94e0e8da058.png) -->

# 注意
Switch版(キャプチャボード経由)でもSteam版でも動きますが、
Switch版の場合は画面取得によってOBSが重くなるケースがあるようです。
Steam版での利用を推奨します。

# 中身
- siren6_helper.exe: プログラム本体
- template\: HTMLテンプレート
  - overlay.html: 配信画面風オーバーレイ
  - monster_icons.html: その階層の出現モンスター表示用
  - shop_price_candidates.html: 価格識別用

# 設定方法
## インストール及び実行
1. [Releaseページ](https://github.com/dj-kata/siren_helper/releases)から最新のsiren6_helper.zipをダウンロードし、好きなフォルダに解凍する
2. 解凍したsiren6_helperフォルダ内にあるsiren6_helper.exeを実行する

## OBS連携設定方法
モンスターテーブルの自動更新やアイテム候補の自動表示を行いたい場合は、以下のようにOBS連携設定も行ってください。

**注意**  
現状、自動識別機能はライブ探索表示をタイプ2にしないと動きません。  
また、ウィンドウの色はパープル2を推奨します。  
(青い床の店などではうまく検出できない場合もあります)

### 1. OBSの準備
[OBSのインストール](https://obsproject.com/ja/download)を行っておいてください。

最近のOBSのバージョンでは標準搭載されているはずですが、  
ツール内に```WebSocketサーバー設定```の項目がない場合は
[OBSwebsocket](https://github.com/obsproject/obs-websocket/releases)をインストールしてください。  
アルファ版は不安定らしいので非推奨です。  
～～Windows-Installer.exeと書いてあるファイルをダウンロードして実行します。  
インストール後にOBSを再起動すると、メニューバー内ツールの中に**obs-websocket設定**が出てきます。

### 2. OBSWebsocket設定(OBS側)
OBS側で```ツール->WebSocketサーバ設定```を開き、以下の状態にする。
- ```WebSocketサーバーを有効する```にチェックする
- サーバーポート番号(デフォルト:4444)、パスワードを設定する。ポート番号とパスワードはsiren6_helperで入力するため、控えておくこと。

本ツールとの連携でしか使わないので、普段使わない長いパスワードにしておくのが良いと思います。

<img width="667" alt="image" src="https://github.com/user-attachments/assets/2e24b115-962b-4970-90ed-7a23cdacd468" />

また、シレン6のゲーム画面をキャプチャするためのソースを用意しておく。  
ソース一覧の下部にある+をクリックして```ゲームキャプチャ```を選択し、全てデフォルトのままOKをクリックする。  
分かりやすいように、ソース名を変更しておくとよい。(ここでは```シレン6(Steam)```と設定した)

<img width="826" alt="Image" src="https://github.com/user-attachments/assets/b4dda71f-2f40-4c3a-8ccb-93ae3b9d85d5" />

<img width="1147" alt="Image" src="https://github.com/user-attachments/assets/a88f20a7-d67c-4e8d-860e-31ee67beca96" />

### 3. siren6_helper側の設定
メニューバー内```ファイル```->```基本設定```より設定画面を開く。  
```OBS連携を有効にする```をチェックし、```OK```をクリックして閉じる。
<img width="515" alt="Image" src="https://github.com/user-attachments/assets/9b83e0fa-ba28-4f20-bf69-2f2e525ebca3" />

次に、メニューバー内```ファイル```->```OBS制御設定```よりOBS制御設定画面を開く。  
手順2で設定したポートとパスワードを入力し、一旦```OK```をクリックして閉じる。

そして、再度OBS制御設定画面を開く。  
画面中段の新しい制御設定追加セクションにおいて、以下を指定する。
- アクション: ```監視対象ソース指定```
- 対象シーン: 自分がOBSで設定しているもの
- 対象ソース: 手順2で用意したゲームキャプチャの名前

```OK```をクリックしてダイアログを閉じる。

以下のように、シーン名とソース名を合わせる必要があります。
<img width="1197" alt="Image" src="https://github.com/user-attachments/assets/c305c2ed-7a52-4849-8731-504f375b1f56" />

現在の監視対象に正しいソース名が設定できていることを確認し、```OK```でダイアログを閉じてください。
<img width="894" alt="Image" src="https://github.com/user-attachments/assets/4c1449d7-ba6c-4be7-aa90-ce3c848704d3" />

メイン画面の右下に```OBS: 接続中```と表示されていればOKです。
<img width="115" alt="Image" src="https://github.com/user-attachments/assets/bf67b329-0bef-4ddb-9e63-bf050e506a1a" />

## 4. OBSにおける情報表示の設定
```template\overlay.html```をOBSにドラッグ&ドロップする。  
ゲーム画面を適切な大きさに調整する。

# 主な操作方法
## 共通部分
ダンジョンのコンボボックスより、対象とするダンジョンを選択できます。

表示開始階を選択することで、どの階層のモンスターを表示するかを選択できます。

```リセット```を押すことで、アイテム識別、現在の階層、メモ(1冒険用)を全て初期化します。

なお、OBS連携設定済みの場合、上記の操作は全て自動で行われます。

## アイテムタブ
行をダブルクリック、または行を選択した状態で```識別済みにする```を押すことで、そのアイテムを識別済みにできます。再度行をダブルクリックすること、または行を選択した状態で```未識別に戻す```を押すことで、そのアイテムを未識別に戻します。

## 手動サーチ欄
アイテムのカテゴリを選択して、価格を入力すると画面下部に候補アイテムが表示されます。  
買値/売値を選択すると更に絞り込むことができます(多くの場合)。  

また、未識別アイテム名を入力して```識別候補に追加```を押すと、識別候補タブから確認できるようになります。  
(OBS連携機能を用いる場合、ここへの登録も自動で行われます)
<img width="1001" alt="Image" src="https://github.com/user-attachments/assets/ff7b90ee-67e5-4364-a34a-22014c4bbc9b" />


# クレジット表示について
営利・非営利問わず配信などに自由にご利用いただけます。
以下のように記載していただけると喜びます。

```
siren6_helper
https://github.com/dj-kata/siren_helper
```

# その他
シレン5用のツールはこちら。  
https://github.com/dj-kata/siren_helper/releases/tag/v.1.0.1

# 連絡先
HN: かた  
Twitter: @cold_planet_
