## /ec2 のファイルについて

ipfs サーバーを ec2 上で立ち上げる際に必要なコマンドをスクリプトにまとめた

**※必ず ALB で https のみ受付&特定のホスト以外からの通信は拒否する設定で下記実行すること**

- install.sh: パッケージのインストールするスクリプト

  - サーバー作成時に 1 回やれば OK

- setup.sh: インストール後のセットアップと ipfs daemon の立ち上げまでやるスクリプト
  - サーバー起動させるごとにやる。
  - ipfs daemon 落としたい時は、ipfs shutdown で落とす

```
sudo su -
crontab -e
[設定](ex. 30 0 * * * /usr/local/bin/ipfs shutdown >> /var/log/ipfs-shutdown.log 2>&1)
```
