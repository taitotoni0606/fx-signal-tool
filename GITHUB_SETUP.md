# GitHub Actions / iPhone setup

このフォルダをGitHubのpublic repositoryへ置くと、PCを起動していなくてもUSD/JPYを定期監視できます。

## できること

- GitHub Actionsが15分ごとに分析します。
- 条件を満たすとntfyでスマホ通知します。
- GitHub PagesにiPhone用の簡易ダッシュボードを公開します。

## 必要なGitHub設定

1. GitHubでpublic repositoryを作成します。
2. `make_github_upload_folder.bat` をダブルクリックして、アップロード用フォルダを作ります。
3. `C:\codex_tools\codex_tools\fx_signal_tool_github_upload` の中身をrepositoryへアップロードします。
4. Repositoryの `Settings` > `Secrets and variables` > `Actions` を開きます。
5. `New repository secret` で以下を追加します。

```text
Name: NTFY_TOPIC
Value: notification_settings.json の topic の値
```

6. Repositoryの `Settings` > `Pages` を開きます。
7. `Build and deployment` の `Source` を `GitHub Actions` にします。
8. `Actions` タブで `USDJPY Monitor` を開き、`Run workflow` を押します。

## iPhoneで開くURL

GitHub Pagesが有効になると、URLは基本的に以下の形になります。

```text
https://<GitHubユーザー名>.github.io/<リポジトリ名>/
```

初回公開には数分かかることがあります。

## 注意

- 無料運用するにはrepositoryをpublicにしてください。
- GitHub Actionsのスケジュール実行は遅れることがあります。
- public repositoryで60日間活動がないと、スケジュール実行が自動停止される場合があります。
- ダッシュボードは静的なスマホ用ページです。PC版Streamlitと完全に同じ操作画面ではありません。
