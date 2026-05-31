# Backtest A A7R2 リファクター計画

## 目的

`backtest_A_a7r2.py` は、A7R2のスクリーニング条件に合う銘柄を購入した場合、その後の株価がどう推移したかを集計するバックテスト用スクリプトである。

最初のリファクター目的は、現行の動作を変えずに責務を分離すること。既存の `backtest_A_a7r2.py` は、従来通り実行できる互換エントリーポイントとして残す。

## 作業進捗

### Commit 1: 現行仕様とリファクター計画の追加

状態: 完了

実施内容:

- 現行仕様を文書化した。
- 目標アーキテクチャを整理した。
- `yfinance_repository` は生OHLCV取得だけを担当する方針を明記した。
- 指標計算をドメイン層へ独立させる方針を明記した。
- 将来エントリー条件を差し替えられるようにする `EntryRule` 案を記載した。
- コミット分割案を作成した。

動作影響:

- なし。ドキュメント追加のみ。

### Commit 2: パッケージ骨格とドメインモデルの導入

状態: 完了

実施内容:

- `app/` パッケージを追加した。
- `app/domain/` パッケージを追加した。
- `ReasonItem` と `ScreenResult` を `app/domain/models.py` へ移動した。
- A7R2の定数群を `app/domain/config.py` へ移動した。
- 将来の閾値差し替えに備え、現行値を保持する `A7R2Config` dataclass を追加した。
- `backtest_A_a7r2.py` は、新しいドメインモジュールからモデルと定数を import する形に変更した。

動作影響:

- 仕様上の動作変更なし。
- 既存の関数名、定数名、判定ロジックは維持している。

検証:

- `backtest_A_a7r2.py`, `app/domain/config.py`, `app/domain/models.py` の構文チェックを実施。
- `backtest_A_a7r2.py` から新しいドメイン定数・モデルを import できることを確認。

### Commit 3: 指標計算の抽出

状態: 完了

実施内容:

- `app/domain/indicators.py` を追加した。
- `safe_float`, `ema_rsi`, `compute_indicators` を `app/domain/indicators.py` へ移動した。
- `backtest_A_a7r2.py` は指標計算関数を新しいドメインモジュールから import する形に変更した。
- yfinance取得処理と指標計算処理の分離に向けて、指標計算を単独で呼び出せる状態にした。

動作影響:

- 仕様上の動作変更なし。
- 生成する指標列名、RSI計算、ボリンジャーバンド計算、既存の `safe_float` 挙動は維持している。

検証:

- `backtest_A_a7r2.py`, `app/domain/indicators.py`, `app/domain/config.py`, `app/domain/models.py` の構文チェックを実施。
- 固定のインメモリOHLCV DataFrameに対して `compute_indicators` を実行し、主要な指標列が生成されることを確認。
- `backtest_A_a7r2.py` から `compute_indicators` と `safe_float` を従来名で参照できることを確認。

### Commit 4: yfinance生価格リポジトリの抽出

状態: 完了

実施内容:

- `app/data/` パッケージを追加した。
- `app/data/yfinance_repository.py` を追加した。
- `app/data/fundamental_extractors.py` を追加した。
- yfinanceの日足価格取得処理を `fetch_raw_price_map` へ移動した。
- `fetch_raw_price_map` は指標計算を行わず、生OHLCVを正規化して返すだけにした。
- ファンダメンタル取得処理を `fetch_fundamentals_once` として data 層へ移動した。
- PER/PBR、売上成長率、ROAの正規化処理を `fundamental_extractors.py` へ移動した。
- `run_backtest_A7R2` は、生OHLCV取得後に `compute_indicators` を適用する流れへ変更した。
- 既存互換のため、`bulk_download_prices` は残し、内部で生OHLCV取得後に指標計算する薄いラッパーにした。

動作影響:

- 仕様上の動作変更なし。
- yfinanceから取得する価格期間、引数、auto adjust指定は維持している。
- 指標計算の場所は data 層から domain 層へ移ったが、生成列と判定入力は維持している。

検証:

- `backtest_A_a7r2.py`, `app/data/yfinance_repository.py`, `app/data/fundamental_extractors.py`, `app/domain/indicators.py`, `app/domain/config.py`, `app/domain/models.py` の構文チェックを実施。
- `backtest_A_a7r2.py` から新しい data 層関数を import できることを確認。
- インメモリOHLCVを使って `bulk_download_prices` 互換ラッパーが指標列を付与することを確認。

yFinance API呼び出し回数の現状:

- 価格データ: バックテスト1回につき `yf.download(...)` を1回呼ぶ。全銘柄をまとめて取得する。
- ファンダメンタル: 銘柄数を `N` とすると、各銘柄で `yf.Ticker(symbol)` を作り、以下の4プロパティを順に参照する。
  - `ticker.info`
  - `ticker.income_stmt`
  - `ticker.quarterly_income_stmt`
  - `ticker.balance_sheet`
- コード上の yfinance 呼び出し単位では、1実行あたり `yf.download` が1回、ファンダメンタル系プロパティ参照が最大 `4 * N` 回。
- `yf.Ticker(symbol)` の生成自体は、通常はこのコード上ではデータ取得プロパティ参照の準備であり、主な取得は上記プロパティ参照時に発生する。
- yfinance内部のHTTPリクエスト数は、yfinance側の実装・キャッシュ・失敗時挙動に依存するため、コード上の呼び出し数と完全には一致しない可能性がある。

## 現行仕様

### 入力

- 監視銘柄のMarkdownファイル。
  - 銘柄名と4桁コードが括弧内に書かれた行を抽出する。
  - 半角括弧と全角括弧の両方に対応する。
  - 同一コードが複数回出た場合は、最初の出現だけを採用する。
- 開始日: `YYYY-MM-DD`。
- 終了日: `YYYY-MM-DD`。
- 出力先ディレクトリ。
- 入力はCLI引数またはGUIから指定できる。

### データ取得

- 日足価格データは yfinance から `{code}.T` の形式で取得する。
- 取得期間は、指定されたバックテスト期間より広めに取る。
  - 開始日は指定開始日から340日前。
  - 終了日は指定終了日から45日後。
- 日足OHLCV取得時の主な指定は以下。
  - `interval="1d"`
  - `auto_adjust=True`
  - `group_by="ticker"`
  - `threads=True`
- ファンダメンタルデータは銘柄ごとに1回取得する。
  - `info`
  - `income_stmt`
  - `quarterly_income_stmt`
  - `balance_sheet`

### 指標計算

指標計算は yfinance アクセスから独立させる。

現行で計算している指標は以下。

- `MA5`, `MA25`, `MA75`
- EMA方式の `RSI14`
- `Momentum20`
- `Dev5`, `Dev25`
- `Turnover`
- `AvgTurnover20`
- `High60`
- `NearHighRatio`
- `MA25_SlopePct`, `MA75_SlopePct`
- `VolumeAvg20`, `VolumeRatio20`
- `PrevClose`, `PrevOpen`, `PrevVolume`
- `DayChangePct`
- `ClosePositionPct`
- `IsBear`
- `LowerLow`
- `DownVolExpand`, `DownVolExpand2`
- ボリンジャーバンド関連
  - `BB_Mid20`
  - `BB_Upper20`
  - `BB_Lower20`
  - `BB_PercentB`
- `Close2Ago`

### ファンダメンタル抽出

現行で正規化しているファンダメンタル値は以下。

- PER: `trailingPE`。
- PBR: `priceToBook`。
- 売上成長率:
  - `quarterlyRevenueGrowth` を優先。
  - 次に `revenueGrowth`。
  - 次に四半期損益計算書の売上成長率。
  - 最後に年次損益計算書の売上成長率。
- ROA:
  - `returnOnAssets` を優先。
  - 取得できない場合は、直近純利益を総資産で割って推定する。

ファンダメンタル値が欠損している場合は、エントリー判定ではハードエラーではなく soft fail として扱う。

### エントリー判定

指定期間内の営業日ごとに、各銘柄を評価する。

指定営業日に完全一致する取引日がない場合は、指定日以前で最も近い取引日を使う。

判定結果には以下を含める。

- 価格データ。
- 指標値。
- ファンダメンタル値。
- pass / near pass フラグ。
- スコア。
- 主カテゴリと主理由。
- 副理由。
- 監視ステータス。
- 想定エントリー価格帯。

現行の主な判定グループは以下。

- トレンド。
- 押し目 / 過熱。
- ボリンジャーバンド過熱。
- RSI / 短期上昇率。
- 押し目完成度。
- 流動性。
- ファンダメンタル。
- 高PERかつ過熱時の除外。

hard fail がある場合は pass と near pass にならない。

soft fail は、理由がすべて回復可能な種類であり、かつ既存の許容数以内であれば pass になり得る。

### エントリー価格帯

現行の想定エントリー価格帯は以下。

- 下限: `MA25`
- 上限: `MA25 * 1.015`
- 終値が計算上限より低い場合、上限は `max(close, MA25)` になる。

### エントリー後評価

各シグナルについて、判定に使った取引日を基準に将来指標を計算する。

現行のリターン評価期間は以下。

- 1営業日後。
- 3営業日後。
- 5営業日後。
- 10営業日後。
- 20営業日後。

現行の最大上昇・最大下落評価ウィンドウは以下。

- 5営業日。
- 10営業日。
- 20営業日。

各リターン評価期間では、基準終値から将来終値までの騰落率を計算する。

各評価ウィンドウでは、基準終値から将来高値までの最大上昇率と、将来安値までの最大下落率を計算する。

### 出力

UTF-8 BOM付きCSVを2ファイル出力する。

- `backtest_A_signals_a7r2_<start>_to_<end>.csv`
- `backtest_A_summary_a7r2_<start>_to_<end>.csv`

シグナルCSVは、指定営業日と銘柄の組み合わせごとに1行出力する。

サマリーCSVは、正規化カテゴリごとに以下を集計する。

- 件数。
- 各リターン評価期間の平均、中央値、勝率。
- 各評価ウィンドウの平均最大上昇率、平均最大下落率。

### プレゼンテーション

- CLIは `argparse` を使う。
- GUIは `tkinter` と `tkcalendar` を使う。
- GUIの責務は、入力選択と完了通知だけに限定する。

## 目標アーキテクチャ

```text
backtest_A_a7r2.py
app/
  main.py
  domain/
    config.py
    models.py
    indicators.py
    entry_rules/
      base.py
      a7r2.py
    post_entry_metrics.py
    summary.py
  usecases/
    run_backtest.py
    watchlist.py
  data/
    yfinance_repository.py
    fundamental_extractors.py
  output/
    signal_record.py
    csv_writer.py
  presentation/
    cli.py
    gui.py
```

### 依存方向

```text
presentation -> usecases -> domain
data ---------^
output -------^
```

- `domain` は yfinance、tkinter、argparse、CSV保存処理に依存しない。
- `data` は yfinance と pandas に依存してよい。
- `output` は pandas と pathlib に依存してよい。
- `presentation` は argparse と tkinter に依存してよい。
- `usecases` は各層をつなぐが、業務ルール本体は domain に置く。

## データ層の方針

`yfinance_repository` は生OHLCV取得だけを担当する。

指標計算は行わない。これにより、yfinanceアクセスを将来差し替えやすくし、指標計算を単独でテストしやすくする。

推奨フローは以下。

```text
yfinance_repository で生OHLCVを取得
-> domain.indicators で指標計算
-> domain.entry_rules でエントリー判定
-> domain.post_entry_metrics でエントリー後評価
-> output でCSV行作成と保存
```

ファンダメンタルについては、yfinanceオブジェクトへのアクセスは `yfinance_repository.py` に置く。yfinance由来フィールドの正規化は `fundamental_extractors.py` に置く。

## 将来のエントリー条件変更

複数のエントリー条件を追加する前に、エントリールールのインターフェースを導入する。

想定形は以下。

```python
class EntryRule(Protocol):
    name: str

    def evaluate(
        self,
        stock: Stock,
        trade_date: pd.Timestamp,
        row: pd.Series,
        prev_rows: pd.DataFrame,
        fundamentals: Fundamentals,
    ) -> ScreenResult:
        ...
```

A7R2はその実装の1つにする。

```python
class A7R2EntryRule:
    name = "a7r2"

    def evaluate(...):
        return evaluate_row_a7r2(...)
```

これにより、将来以下が可能になる。

- CLIオプションでルールを選ぶ。例: `--entry-rule a7r2`
- `a7r3` を追加してもバックテストループ本体を変更しない。
- 閾値を設定オブジェクトから渡す。
- 同じデータで複数ルールを比較する。

最初の分割では、閾値を完全に外部設定化しない。まずはデフォルト値が現行と同じ `A7R2Config` dataclass へ移すにとどめる。

## コミット分割案

### Commit 1: 現行仕様とリファクター計画の追加

対象ファイル:

- `docs/backtest_A_a7r2_refactor_plan.md`

目的:

- コード変更前に現行動作を固定する。
- 目標とする依存方向を定義する。
- yfinance価格取得は生OHLCVのみ返す方針を記録する。

検証:

- 実行時の挙動変更なし。

### Commit 2: パッケージ骨格とドメインモデルの導入

対象ファイル:

- `app/__init__.py`
- `app/domain/__init__.py`
- `app/domain/models.py`
- `app/domain/config.py`

移動対象:

- `ReasonItem`
- `ScreenResult`
- A7R2定数群。`A7R2Config` または `config.py` へ移動する。

互換性:

- `backtest_A_a7r2.py` は引き続き動く状態を維持する。
- 必要なら移動したオブジェクトを既存ファイル側でimportして利用する。

検証:

- 構文チェック。
- 最小限のimportチェック。

### Commit 3: 指標計算の抽出

対象ファイル:

- `app/domain/indicators.py`

移動対象:

- `safe_float`。必要なら domain utility として配置する。
- `ema_rsi`
- `compute_indicators`

動作維持方針:

- 生成する列名は完全に同じにする。
- RSI計算式は完全に同じにする。
- ボリンジャーバンド設定は完全に同じにする。

検証:

- 固定のインメモリOHLCV DataFrameで、旧関数と新関数の列・サンプル値が一致することを確認する。

### Commit 4: yfinance生価格リポジトリの抽出

対象ファイル:

- `app/data/__init__.py`
- `app/data/yfinance_repository.py`
- `app/data/fundamental_extractors.py`

移動対象:

- yfinance価格取得処理。
- ファンダメンタル取得処理。
- PER/PBR、売上成長率、ROA抽出処理。

重要な変更:

- `yfinance_repository` は `compute_indicators` を呼ばない。
- `run_backtest` 側で、生OHLCV取得後に指標計算を適用する。

検証:

- fake repository またはインメモリデータで、判定前に指標列が付与されることを確認する。

### Commit 5: エントリールール実装の抽出

対象ファイル:

- `app/domain/entry_rules/base.py`
- `app/domain/entry_rules/a7r2.py`

移動対象:

- `add_reason`
- `summarize_reasons`
- `is_recoverable_soft_reason`
- `can_promote_soft_fails`
- `estimate_entry_limits`
- `score_result_a7r2`
- `evaluate_row_a7r2`

設計:

- `EntryRule` protocol を追加する。
- `A7R2EntryRule` を追加する。
- 互換性とテスト容易性のため、`evaluate_row_a7r2` は純粋関数として残す。

検証:

- 同じ入力行とファンダメンタル値から、同じ `ScreenResult` フィールドが返ることを確認する。

### Commit 6: エントリー後評価とサマリーの抽出

対象ファイル:

- `app/domain/post_entry_metrics.py`
- `app/domain/summary.py`

移動対象:

- `business_days`。営業日ヘルパーとして扱う場合。
- `build_trade_date_index`
- `build_forward_metrics_map`
- `build_prev3_cache`
- `summarize_signals`

検証:

- 固定のインメモリOHLCVデータで、将来リターン指標とサマリー出力が一致することを確認する。

### Commit 7: 出力層の抽出

対象ファイル:

- `app/output/__init__.py`
- `app/output/signal_record.py`
- `app/output/csv_writer.py`

移動対象:

- `normalize_category`
- `make_signal_record`
- `save_outputs`

検証:

- 出力カラム名が変わらないこと。
- CSVエンコーディングが `utf-8-sig` のままであること。
- ファイル名が変わらないこと。

### Commit 8: ユースケース層の抽出

対象ファイル:

- `app/usecases/__init__.py`
- `app/usecases/watchlist.py`
- `app/usecases/run_backtest.py`

移動対象:

- `parse_stock_md`
- `load_watchlist`
- `run_backtest_A7R2`

設計:

- 可能な範囲で、リポジトリとエントリールールを依存として受け取る。
- デフォルトでは yfinance と A7R2 を使い、現行CLI動作を維持する。

検証:

- インメモリ fake repository で、ネットワークなしにバックテストを実行できることを確認する。

### Commit 9: プレゼンテーション層と互換エントリーポイントの抽出

対象ファイル:

- `app/presentation/__init__.py`
- `app/presentation/cli.py`
- `app/presentation/gui.py`
- `app/main.py`
- `backtest_A_a7r2.py`

移動対象:

- `select_stock_file`
- `select_output_dir`
- `select_date_range`
- `build_parser`
- `resolve_inputs`
- `main`

互換性:

- `python backtest_A_a7r2.py ...` が引き続き動くこと。
- `backtest_A_a7r2.py` は `app.main.main` を呼ぶ薄いラッパーにする。

検証:

- CLI help が動くこと。
- import check が成功すること。

### Commit 10: キャラクタライゼーションテストの追加

対象ファイル:

- `tests/`

テスト対象:

- 監視銘柄Markdownのパース。
- 指標計算。
- 既知の行に対するA7R2エントリー判定。
- 将来リターン指標。
- サマリー集計。
- 出力レコードのカラム互換性。

目的:

- 今の挙動を固定し、以後の戦略変更で意図しない差分を見つけやすくする。

## 推奨リファクター順序

安全な順序は以下。

1. 仕様書作成。
2. モデルと定数の抽出。
3. 純粋なドメイン関数の抽出。
4. データリポジトリの抽出。
5. ユースケースの抽出。
6. プレゼンテーション層の抽出。
7. 抽出済み部品へのテスト追加。

この順序なら、yfinance と GUI の挙動を保ったまま、検証しやすい純粋処理から分離できる。
