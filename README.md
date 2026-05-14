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

## ゲーム画面の自動取得機能
ゲーム画面を読み取り、
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
Steam版&直接取得での利用を推奨します。

# 中身
- siren6_helper.exe: プログラム本体
- template\: HTMLテンプレート
  - overlay.html: 配信画面風オーバーレイ
  - vertical_overlay.html: 2つの情報を縦に並べただけのビュー。直接ブラウザで確認する用途を想定。
  - monster_icons.html: その階層の出現モンスター表示用
  - shop_price_candidates.html: 価格識別用

# 設定方法
## インストール及び実行
1. [Releaseページ](https://github.com/dj-kata/siren_helper/releases)から最新のsiren6_helper.zipをダウンロードし、好きなフォルダに解凍する
2. 解凍したsiren6_helperフォルダ内にあるsiren6_helper.exeを実行する

## OBSにおける情報表示の設定
OBS上で本ツールの情報表示を行う場合は、
```template\overlay.html```をOBSにドラッグ&ドロップしてください。  
ゲーム画面を適切な大きさに調整して配置してください。

## 画面取得設定方法
モンスターテーブルの自動更新やアイテム候補の自動表示を行いたい場合は、
```ゲーム画面取得方法```について```直接取得(Steam版のみ)```を選択して```OK```をクリックしてください。
<img width="510" alt="image" src="https://github.com/user-attachments/assets/6d1cf65a-e0ac-4008-9aba-e7ecb90b37e2" />

**注意**  
現状、自動識別機能はライブ探索表示をタイプ2にしないと動きません。  
また、ウィンドウの色はパープル2を推奨します。  
青い床の店などではうまく検出できない場合もあります。中央のウィンドウが読み取りやすいように、店の右端などに移動すると検出しやすいかもしれません。

文字認識を定期的に実行するせいか若干PCへの負荷が大きめです。  

Switch版の場合は[こちら](https://github.com/dj-kata/siren_helper/wiki/OBS%E9%80%A3%E6%90%BA%E6%A9%9F%E8%83%BD%E5%88%A9%E7%94%A8%E6%96%B9%E6%B3%95)を参考にOBSwebsocket設定を行ってください。(かなり重いです)

店内での価格取得について、アイテム欄選択ではなく、以下のようにアイテムの上に乗っている場合にのみ動作します。
<img width="960" alt="Image" src="https://github.com/user-attachments/assets/da7d4e4e-10b8-4da5-9327-358b0fd0e0a0" />  

アイテム欄選択では動作しません(カーソル周りの取得がめんどくさそうなため)
<img width="960" alt="Image" src="https://github.com/user-attachments/assets/5502e520-80c4-4600-870b-a3ecf1a9115d" />

# 主な操作方法
## 共通部分
ダンジョンのコンボボックスより、対象とするダンジョンを選択できます。

表示開始階を選択することで、どの階層のモンスターを表示するかを選択できます。

```リセット```を押すことで、アイテム識別、現在の階層、メモ(1冒険用)を全て初期化します。

なお、画面取得設定を有効にしている場合、上記の操作は全て自動で行われます。

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
