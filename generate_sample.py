"""
generate_sample.py
テスト用サンプルデータを data/sample/ に生成する。
実行: python generate_sample.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
rng = np.random.default_rng(SEED)

FACILITIES = {
    "市民会館": {"base": 15.0, "peak_factor": 2.5, "weekend_factor": 0.5},
    "小学校": {"base": 8.0, "peak_factor": 3.0, "weekend_factor": 0.1},
    "中学校": {"base": 10.0, "peak_factor": 2.8, "weekend_factor": 0.15},
    "図書館": {"base": 5.0, "peak_factor": 1.8, "weekend_factor": 0.9},
    "役場庁舎": {"base": 20.0, "peak_factor": 2.2, "weekend_factor": 0.2},
}

START = pd.Timestamp("2024-04-01")
END = pd.Timestamp("2025-03-31 23:30")
FREQ = "30min"


def _day_profile(hour: int, is_weekend: bool, fac_cfg: dict) -> float:
    """0〜23 時の需要プロファイル（正規化 0〜1）。"""
    if is_weekend:
        # 休日：昼間に穏やかなピーク
        profile = np.exp(-((hour - 12) ** 2) / 20) * fac_cfg["weekend_factor"]
    else:
        # 平日：朝 8 時と夕方 14 時にピーク
        morning = np.exp(-((hour - 8) ** 2) / 4)
        afternoon = np.exp(-((hour - 14) ** 2) / 8)
        profile = (morning * 0.6 + afternoon * 0.4) * fac_cfg["peak_factor"]
    return max(profile, 0.05)  # ベースライン


def generate() -> pd.DataFrame:
    dt_index = pd.date_range(START, END, freq=FREQ)
    rows = []

    for fac, cfg in FACILITIES.items():
        for dt in dt_index:
            is_weekend = dt.dayofweek >= 5
            hour = dt.hour + dt.minute / 60.0
            profile = _day_profile(int(hour), is_weekend, cfg)

            # 季節補正（冬・夏に増加）
            month = dt.month
            seasonal = 1.0 + 0.3 * np.cos((month - 1) / 6 * np.pi - np.pi)

            kwh = cfg["base"] * profile * seasonal
            noise = rng.normal(1.0, 0.05)
            kwh = max(kwh * noise, 0.0)

            rows.append({
                "datetime": dt,
                "facility_name": fac,
                "consumption_kwh": round(kwh, 3),
            })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    out_dir = Path("data/sample")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = generate()
    csv_path = out_dir / "sample_data.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"✅ CSV 生成完了: {csv_path}  ({len(df):,} 行)")

    # Excel も生成（施設ごとに別ファイル）
    for fac in FACILITIES:
        fac_df = df[df["facility_name"] == fac].copy()
        xlsx_path = out_dir / f"sample_{fac}.xlsx"
        fac_df.to_excel(xlsx_path, index=False)
        print(f"   📄 {xlsx_path}")
