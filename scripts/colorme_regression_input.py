#!/usr/bin/env python3
"""カラーミーCSV変換 実データ回帰テストの入力パス解決(読み取り専用)。

このスクリプトは以下を一切行わない:
  - ファイルの作成・変更・削除
  - Supabase/SQLへのアクセス
  - AI秘書(index.html)のコード実行・ブラウザ操作
  - Desktop/Downloads/Documents/プロジェクト内tmp等への自動フォールバック

行うのは ~/Claude-Workspace/config/workspace.json の読み込み・解析と、
そこに定義されたカラーミー商品CSV・オプションCSVの絶対パスの組み立て、
および実在確認のみ。実際の回帰テスト(PapaParseでの解析・Merchant変換・
ブラウザでのTSV/監査CSV生成確認)はこのスクリプトの対象外であり、
別途ブラウザを介して手動で実行する(established methodology)。

workspace.jsonの場所やパス・ファイル名は、このスクリプト内に固定記述せず、
常にworkspace.json自体を正とする。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_CONFIG_PATH = Path.home() / "Claude-Workspace" / "config" / "workspace.json"


def main() -> int:
    if not WORKSPACE_CONFIG_PATH.exists():
        print(f"[NG] workspace.jsonが見つかりません: {WORKSPACE_CONFIG_PATH}")
        print("Desktop・Downloads・Documents等への自動フォールバックは行いません。")
        print(f"上記の場所にworkspace.jsonを配置してください。")
        return 1

    try:
        with open(WORKSPACE_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[NG] workspace.jsonのJSON解析に失敗しました: {e}")
        return 1
    except OSError as e:
        print(f"[NG] workspace.jsonの読み込みに失敗しました: {e}")
        return 1

    try:
        colorme_input_dir = config["paths"]["colorme_input"]
        product_filename = config["filenames"]["colorme_product_csv"]
        option_filename = config["filenames"]["colorme_option_csv"]
    except KeyError as e:
        print(f"[NG] workspace.json内に必要なキーが見つかりません: {e}")
        return 1

    product_path = Path(colorme_input_dir) / product_filename
    option_path = Path(colorme_input_dir) / option_filename

    missing = [p for p in (product_path, option_path) if not p.is_file()]

    if missing:
        print("[NG] 以下のファイルが見つかりません:")
        for p in missing:
            print(f"  - {p}")
        print("")
        print("正式な配置場所(workspace.json定義):")
        print(f"  商品CSV     : {product_path}")
        print(f"  オプションCSV: {option_path}")
        print("")
        print("Desktop・Downloads・Documents・プロジェクト内tmp等への自動フォールバックは行いません。")
        return 1

    product_size = product_path.stat().st_size
    option_size = option_path.stat().st_size

    print("[OK] 実データCSVを確認しました。")
    print(f"  商品CSV     : {product_path} ({product_size:,} bytes)")
    print(f"  オプションCSV: {option_path} ({option_size:,} bytes)")
    # 他のツール(シェル等)から機械的に読み取れるよう、末尾にkey=value形式でも出力する
    print(f"PRODUCT_CSV_PATH={product_path}")
    print(f"OPTION_CSV_PATH={option_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
