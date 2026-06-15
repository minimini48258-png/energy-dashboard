# ⚡ 電力需給分析ダッシュボード

公共施設の30分値電力使用量データを可視化・分析するStreamlitアプリです。
地域新電力事業のエネルギー小売検討に活用することを想定しています。

## 機能（MVP）

- **Excelデータ読み込み**：複数ファイル対応、列名の自動マッピング
- **需要カーブ表示**：施設別 / 全施設合計の30分値折れ線グラフ
- **KPI表示**：積算使用量・最大・平均・最小
- **需要パターン分析**：
  - 月別使用量
  - 時間帯別平均使用量
  - 平日・休日比較
  - 施設別年間使用量ランキング
  - 日別使用量
- **需給バランス**（次フェーズ）：太陽光・蓄電池・市場調達との需給比較

## 対応データ形式

| 列名 | 内容 |
|------|------|
| `datetime` | 日時（30分刻み）|
| `facility_name` | 施設名 |
| `consumption_kwh` | 使用電力量 (kWh/30min) |

列名が異なる場合は読み込み後に手動マッピングできます。
日本語列名（`日時`、`施設名`、`使用電力量`など）にも対応しています。

## セットアップ

```bash
pip install -r requirements.txt
```

## 起動

```bash
streamlit run app.py
```

## サンプルデータの生成

```bash
python generate_sample.py
```

5施設・1年分（87,600行）のサンプルCSVとExcelが `data/sample/` に生成されます。

## ファイル構成

```
energy-dashboard/
├── app.py              # Streamlitメインアプリ
├── data_loader.py      # Excel/CSV読み込み・列マッピング
├── data_cleaner.py     # データクレンジング・品質チェック
├── analyzer.py         # 集計・分析ロジック
├── visualizer.py       # Plotlyグラフ生成
├── generate_sample.py  # サンプルデータ生成
├── requirements.txt
└── data/sample/        # サンプルデータ（.gitignoreでExcel除外）
```
