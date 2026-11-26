"""
storage.py
アプリが保存するJSON・キャッシュの置き場所を一か所で決める。

既定は従来どおり /tmp/energy_dashboard（Streamlit Community Cloud などでは再起動で消える）。
消えない場所に置きたい場合は、環境変数 ENERGY_DASHBOARD_DATA_DIR に保存先ディレクトリを指定する
（例：自前サーバーの永続ボリューム）。Community Cloud のように永続領域が無い環境では、
「シナリオ比較」ページのJSONバックアップ（書き出し／読み込み）で退避・復元する。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_DIR = "/tmp/energy_dashboard"
DATA_DIR = Path(os.environ.get("ENERGY_DASHBOARD_DATA_DIR") or DEFAULT_DATA_DIR)
