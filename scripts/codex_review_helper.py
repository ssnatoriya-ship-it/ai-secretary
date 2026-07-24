#!/usr/bin/env python3
"""Codexレビュー原文の事実確認ツール(読み取り専用・意味判断なし)。

標準入力からCodexレビュー本文を受け取り、以下の機械的な事実確認結果のみを
Markdownとして標準出力する。

  - ファイル参照候補(「ファイル名:行番号」等)の抽出
  - 対象ファイルの実在確認(リポジトリ外を指す候補は判定拒否、内容は読まない)
  - 行番号の妥当性確認
  - report-finish-task-diff.patch との突合せによるdiff内判定(追加行のみ)
  - 入力テキスト全体に対する秘密情報・個人情報候補のスキャン(値は非表示)

分類・重複統合・修正提案・重要度の意味づけは一切行わない。
ファイルへの書き込みは一切行わない(標準出力のみ)。
入力はClaude Codeがユーザーから明示的に受け取ったCodexレビュー原文に限る
(クリップボードや外部ファイルを暗黙に読み取ることはしない)。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import finish_task as ft  # noqa: E402  既存の危険パターン検出・repo_root取得を再利用する

CONFIG_PATH = SCRIPT_DIR / "codex_review_config.json"

FIELD_LABEL_LINE_RE = re.compile(r"^\s*[-・*]?\s*([^\s:：]{1,20})\s*[:：]\s*(.+)$")
TRAILING_PUNCT = "、。,.)）」』"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# ファイル参照候補の抽出(構文パターンマッチのみ、意味の解釈はしない)
# ---------------------------------------------------------------------------

def build_colon_line_regex(extensions: list[str]) -> re.Pattern:
    ext_pattern = "|".join(re.escape(e.lstrip(".")) for e in extensions)
    return re.compile(
        r"([A-Za-z0-9_.\-/]+\.(?:" + ext_pattern + r"))\s*[:：]\s*(\d+)(?:\s*[-〜]\s*(\d+))?"
    )


def build_japanese_suffix_regex(extensions: list[str]) -> re.Pattern:
    ext_pattern = "|".join(re.escape(e.lstrip(".")) for e in extensions)
    return re.compile(
        r"([A-Za-z0-9_.\-/]+\.(?:" + ext_pattern + r"))"
        r"\s*[\(（]?\s*(?:の)?\s*(\d+)(?:\s*[-〜]\s*(\d+))?\s*行目"
    )


def looks_like_recognized_file(value: str, extensions: list[str]) -> bool:
    value = value.strip().rstrip(TRAILING_PUNCT)
    return any(value.lower().endswith(e.lower()) for e in extensions)


def extract_colon_and_suffix_candidates(text: str, extensions: list[str]) -> list[dict]:
    candidates = []
    for rx in (build_colon_line_regex(extensions), build_japanese_suffix_regex(extensions)):
        for m in rx.finditer(text):
            file_val, start_s, end_s = m.group(1), m.group(2), m.group(3)
            candidates.append(
                {
                    "raw_text": m.group(0),
                    "file": file_val,
                    "line_start": int(start_s),
                    "line_end": int(end_s) if end_s else None,
                    "pos": m.start(),
                }
            )
    return candidates


def extract_field_style_candidates(text: str, config: dict) -> list[dict]:
    lines = text.splitlines()
    extraction_cfg = config.get("reference_extraction", {})
    file_labels = set(extraction_cfg.get("field_style_file_labels", []))
    line_labels = set(extraction_cfg.get("field_style_line_labels", []))
    window = extraction_cfg.get("field_style_search_window_lines", 5)
    extensions = config.get("recognized_file_extensions", [])

    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    candidates = []
    for i, line in enumerate(lines):
        m = FIELD_LABEL_LINE_RE.match(line)
        if not m or m.group(1) not in file_labels:
            continue
        file_val_raw = m.group(2).strip()
        if not looks_like_recognized_file(file_val_raw, extensions):
            continue
        file_val = file_val_raw.rstrip(TRAILING_PUNCT)

        line_start = line_end = None
        raw_line_part = ""
        for j in range(i + 1, min(i + 1 + window, len(lines))):
            m2 = FIELD_LABEL_LINE_RE.match(lines[j])
            if not m2:
                continue
            label2 = m2.group(1)
            if label2 in file_labels:
                # 次の指摘の開始に到達したため、今回の候補には行番号を結び付けない
                break
            if label2 not in line_labels:
                continue
            nums = re.findall(r"\d+", m2.group(2))
            if nums:
                line_start = int(nums[0])
                if len(nums) > 1:
                    line_end = int(nums[1])
                raw_line_part = f" / {m2.group(1)}: {m2.group(2).strip()}"
            break

        candidates.append(
            {
                "raw_text": f"{m.group(1)}: {file_val}{raw_line_part}",
                "file": file_val,
                "line_start": line_start,
                "line_end": line_end,
                "pos": offsets[i],
            }
        )
    return candidates


def dedupe_and_sort(candidates: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda c: c["pos"]):
        key = (c["file"], c["line_start"], c["line_end"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


# ---------------------------------------------------------------------------
# report-finish-task-diff.patch の解析(変更後ファイル側の行番号で追加行を記録)
# ---------------------------------------------------------------------------

def parse_diff_added_lines(patch_text: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    current_file = None
    new_line_no = 0
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                current_file = None
            else:
                current_file = path[2:] if path.startswith("b/") else path
                result.setdefault(current_file, set())
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_line_no = (int(m.group(1)) - 1) if m else 0
            continue
        if current_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_line_no += 1
            result[current_file].add(new_line_no)
        elif line.startswith(" "):
            new_line_no += 1
        # '-' で始まる行(削除行)はカウントしない = 「追加行に含まれる」対象にならない

    return result


def load_diff_info(repo_root: Path, config: dict) -> tuple[dict | None, float | None]:
    patch_path = repo_root / config.get("diff_patch_filename", "report-finish-task-diff.patch")
    if not patch_path.exists():
        return None, None
    try:
        text = patch_path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return parse_diff_added_lines(text), patch_path.stat().st_mtime


# ---------------------------------------------------------------------------
# 候補ごとの事実確認(リポジトリ外パスは内容を読まず判定拒否)
# ---------------------------------------------------------------------------

def verify_candidate(candidate: dict, repo_root: Path, diff_added: dict | None, diff_mtime: float | None) -> dict:
    result = dict(candidate)
    repo_root_resolved = repo_root.resolve()
    raw_file = candidate["file"]

    try:
        target = (repo_root / raw_file).resolve()
    except (OSError, RuntimeError, ValueError):
        result.update(
            file_exists="rejected",
            reject_reason="パスを解決できませんでした",
            line_valid="rejected",
            diff_status="rejected",
        )
        return result

    try:
        target.relative_to(repo_root_resolved)
    except ValueError:
        result.update(
            file_exists="rejected",
            reject_reason="リポジトリ外を指すパスのため確認していません",
            line_valid="rejected",
            diff_status="rejected",
        )
        return result

    if not target.is_file():
        result["file_exists"] = False
        try:
            matches = [p for p in repo_root_resolved.rglob(target.name) if ".git" not in p.parts]
        except OSError:
            matches = []
        if matches:
            result["similar_found"] = str(matches[0].relative_to(repo_root_resolved))
        result["line_valid"] = None
        result["diff_status"] = None
        return result

    result["file_exists"] = True

    if candidate["line_start"] is None:
        result["line_valid"] = "n/a"
        result["diff_status"] = "n/a"
        return result

    try:
        with target.open("r", encoding="utf-8", errors="replace") as f:
            line_count = sum(1 for _ in f)
    except OSError:
        result["line_valid"] = None
        result["diff_status"] = None
        return result

    result["file_line_count"] = line_count
    check_line = candidate["line_end"] or candidate["line_start"]
    result["line_valid"] = check_line <= line_count

    if not result["line_valid"]:
        result["diff_status"] = None
        return result

    rel_path_str = str(target.relative_to(repo_root_resolved))
    if diff_added is None:
        result["diff_status"] = None
        result["diff_note"] = "差分ファイルが見つかりません"
    elif rel_path_str not in diff_added:
        result["diff_status"] = False
        result["diff_note"] = "このファイルは差分に含まれていません"
    else:
        line_range = range(candidate["line_start"], (candidate["line_end"] or candidate["line_start"]) + 1)
        result["diff_status"] = any(n in diff_added[rel_path_str] for n in line_range)

    if diff_mtime is not None:
        try:
            if target.stat().st_mtime > diff_mtime:
                result["staleness_warning"] = True
        except OSError:
            pass

    return result


# ---------------------------------------------------------------------------
# 見出し検出(意味づけなし、文字列の検出有無のみ)
# ---------------------------------------------------------------------------

def detect_headings(text: str, config: dict) -> list[str]:
    markers = config.get("heading_markers_to_detect", [])
    return [m for m in markers if m in text]


# ---------------------------------------------------------------------------
# 秘密情報・個人情報候補スキャン(finish_task_config.jsonのdanger_patternsを再利用)
# ---------------------------------------------------------------------------

def scan_secrets_in_text(text: str, ft_config: dict) -> list[dict]:
    compiled = ft.compile_danger_patterns(ft_config)
    danger_patterns = ft_config.get("danger_patterns", {})
    known_safe = set(ft_config.get("known_safe_values", []))
    watchlist = ft_config.get("personal_name_watchlist", [])

    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for key, label in ft.find_matches_in_line(line, compiled, danger_patterns, known_safe, watchlist):
            findings.append({"type": key, "label": label, "line": line_no})
    return findings


# ---------------------------------------------------------------------------
# Markdown整形
# ---------------------------------------------------------------------------

def format_candidate_block(idx: int, c: dict) -> str:
    lines = [f"### 候補 {idx}"]
    lines.append(f"- 入力中の表記: `{c['raw_text']}`")
    lines.append(f"- 対象ファイル: {c['file']}")

    if c["file_exists"] == "rejected":
        lines.append("- ファイル実在: 判定拒否")
        lines.append(f"- 理由: {c['reject_reason']}")
        line_display = c["line_start"] if c["line_start"] is not None else "(なし)"
        lines.append(f"- 対象行番号: {line_display}")
        lines.append("- 行番号の妥当性: 判定拒否")
        lines.append("- diff内判定: 判定拒否")
        return "\n".join(lines)

    if c["file_exists"]:
        lines.append("- ファイル実在: ○ 存在する")
    else:
        lines.append("- ファイル実在: × 存在しない(リポジトリ内に見つかりません)")
        if c.get("similar_found"):
            lines.append(f"  - 補足: 同名ファイルが別の場所に存在: {c['similar_found']}")

    if c["line_start"] is None:
        lines.append("- 対象行番号: (なし)")
        lines.append("- 行番号の妥当性: 対象外(入力から行番号を抽出できませんでした)")
        lines.append("- diff内判定: 対象外")
        return "\n".join(lines)

    line_display = str(c["line_start"]) if not c["line_end"] else f"{c['line_start']}-{c['line_end']}"
    lines.append(f"- 対象行番号: {line_display}")

    if not c["file_exists"]:
        lines.append("- 行番号の妥当性: 判定不能(ファイルが存在しないため)")
        lines.append("- diff内判定: 判定不能(ファイルが存在しないため)")
        return "\n".join(lines)

    if c["line_valid"] is True:
        lines.append(f"- 行番号の妥当性: ○ ファイルの現在行数({c['file_line_count']}行)以内")
    elif c["line_valid"] is False:
        lines.append(f"- 行番号の妥当性: × ファイルの現在行数({c['file_line_count']}行)を超えています")
    else:
        lines.append("- 行番号の妥当性: 判定不能")

    staleness = " (注記: 差分が対象ファイルより古い可能性があります)" if c.get("staleness_warning") else ""
    if c["diff_status"] is True:
        lines.append(f"- diff内判定: ○ 追跡済み差分の追加行に含まれる{staleness}")
    elif c["diff_status"] is False:
        note_text = c.get("diff_note", "差分内には見つからない(このファイルは今回の差分に含まれていない、またはこの行は変更されていない)")
        lines.append(f"- diff内判定: × {note_text}{staleness}")
    else:
        note_text = c.get("diff_note", "判定不能")
        lines.append(f"- diff内判定: {note_text}")

    return "\n".join(lines)


def build_report(text: str, repo_root: Path, config: dict, ft_config: dict) -> str:
    now = datetime.now()
    extensions = config.get("recognized_file_extensions", [])

    raw_candidates = extract_colon_and_suffix_candidates(text, extensions)
    raw_candidates += extract_field_style_candidates(text, config)
    candidates = dedupe_and_sort(raw_candidates)

    diff_added, diff_mtime = load_diff_info(repo_root, config)
    verified = [verify_candidate(c, repo_root, diff_added, diff_mtime) for c in candidates]

    with_line = [c for c in verified if c["line_start"] is not None]
    without_line = [c for c in verified if c["line_start"] is None]

    headings_found = detect_headings(text, config)
    secret_findings = scan_secrets_in_text(text, ft_config)

    patch_path = repo_root / config.get("diff_patch_filename", "report-finish-task-diff.patch")
    if diff_added is not None and diff_mtime is not None:
        diff_line = f"検出 (最終更新日時 {datetime.fromtimestamp(diff_mtime).strftime('%Y-%m-%d %H:%M:%S')})"
    else:
        diff_line = "未検出"

    lines = []
    lines.append("# Codexレビュー 事実確認結果(機械的検証のみ)")
    lines.append("")
    lines.append("このツールは意味判断・分類・修正提案を一切行っていません。")
    lines.append("以下は入力テキストから抽出できた「ファイル参照候補」に対する機械的な事実確認結果です。")
    lines.append("分類・重複統合・採用可否の判断はChatGPT側で行ってください。")
    lines.append("この出力を、Codexレビュー原文とあわせてChatGPTに貼り付けてください。")
    lines.append("")
    lines.append("## 実行情報")
    lines.append(f"- 実行日時: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- リポジトリルート: {repo_root}")
    lines.append(f"- 入力文字数: {len(text)}文字 / 入力行数: {len(text.splitlines())}行")
    lines.append(f"- 差分ファイル({patch_path.name}): {diff_line}")
    if headings_found:
        lines.append(f"- 見出し文字列の検出(意味づけなし、検出有無のみ): {', '.join(headings_found)}")
    else:
        lines.append("- 見出し文字列の検出(意味づけなし、検出有無のみ): なし")
    if len(text.encode("utf-8")) > config.get("max_input_size_warning_bytes", 500000):
        lines.append("- 注記: 入力サイズが大きいため、処理に時間がかかる場合があります")
    lines.append("")

    lines.append("## ファイル参照候補の検証")
    if not verified:
        lines.append("")
        lines.append("機械的に抽出できるファイル参照候補はありませんでした。入力原文に指摘が存在しないことを意味するものではありません。")
    else:
        lines.append("入力テキスト中に現れた順に列挙します。")
        for i, c in enumerate(verified, start=1):
            lines.append("")
            lines.append(format_candidate_block(i, c))
    lines.append("")

    lines.append("## 秘密情報・個人情報候補スキャン(入力テキスト全体)")
    lines.append(
        "既存の危険パターン定義(finish_task_config.jsonのdanger_patterns)を、入力テキスト全体に適用した結果です。値は一切表示しません。"
    )
    lines.append("")
    if secret_findings:
        for f in secret_findings:
            lines.append(f"- [{f['type']}] 入力テキスト{f['line']}行目 — {f['label']}")
    else:
        lines.append("検出なし")
    lines.append("")

    lines.append("## サマリー")
    lines.append("| 項目 | 件数 |")
    lines.append("|---|---|")
    lines.append(f"| 抽出できたファイル参照候補数 | {len(verified)}件 |")
    lines.append(f"| うち行番号付き候補数 | {len(with_line)}件 |")
    lines.append(f"| うち行番号なし候補数 | {len(without_line)}件 |")
    lines.append(f"| ファイル実在 | {sum(1 for c in verified if c['file_exists'] is True)}件 |")
    lines.append(f"| ファイル不在 | {sum(1 for c in verified if c['file_exists'] is False)}件 |")
    lines.append(f"| 判定拒否(リポジトリ外) | {sum(1 for c in verified if c['file_exists'] == 'rejected')}件 |")
    lines.append(f"| 秘密情報・個人情報候補 | {len(secret_findings)}件 |")

    return "\n".join(lines) + "\n"


def build_error_report(error_type: str, detail: str) -> str:
    return (
        "# Codexレビュー 事実確認結果(機械的検証のみ)\n\n"
        "## エラー\n"
        "このツールは事実確認を実行できませんでした。分類・修正提案はこのツールの対象外です。\n\n"
        f"- エラー種別: {error_type}\n"
        f"- 詳細: {detail}\n"
    )


def main() -> int:
    raw_input_text = sys.stdin.read()
    if not raw_input_text or not raw_input_text.strip():
        print(build_error_report("入力なし", "標準入力からCodexレビュー本文を受け取れませんでした"))
        return 1

    try:
        config = load_config()
    except (OSError, json.JSONDecodeError) as e:
        print(build_error_report("設定ファイル読み込み失敗", f"{CONFIG_PATH.name}: {e}"))
        return 1

    try:
        ft_config = ft.load_config()
    except (OSError, json.JSONDecodeError) as e:
        print(build_error_report("設定ファイル読み込み失敗", f"finish_task_config.json: {e}"))
        return 1

    try:
        repo_root = ft.get_repo_root()
    except RuntimeError as e:
        print(build_error_report("リポジトリ未検出", str(e)))
        return 1

    try:
        report = build_report(raw_input_text, repo_root, config, ft_config)
    except Exception as e:  # このツール自体の想定外の失敗もMarkdownで返す
        print(build_error_report("その他", str(e)))
        return 1

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
