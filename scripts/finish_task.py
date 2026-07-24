#!/usr/bin/env python3
"""終了時チェック(読み取り専用)。

このスクリプトは以下を一切行わない:
  - ファイルの作成・変更(このスクリプトが生成する
    report-finish-task-latest.md / report-finish-task-diff.patch を除く)
  - git add / commit / push などの書き込み系git操作
  - サーバーの起動・停止
  - 検出結果に基づく自動修正
  - 未追跡ファイルの内容をレポートへ全文掲載すること(ファイル名・行番号・検出種別のみ)

実行するのは git status/diff の取得、静的な構文チェック、
簡易的なパターン照合(追跡済み差分・未追跡ファイル双方)、そしてその結果のレポート化のみ。
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "finish_task_config.json"
SUMMARY_REPORT_NAME = "report-finish-task-latest.md"
DIFF_PATCH_NAME = "report-finish-task-diff.patch"

SCRIPT_TAG_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
API_PATTERN_RE = re.compile(r"/api/[a-zA-Z0-9_\-]+")
SECRET_MASK_TYPES_DEFAULT = {"private_key", "openai_key", "aws_access_key", "service_role", "email", "phone"}

# 未追跡ファイルスキャンでも常に除外するディレクトリ(このツール自身のコードを含む)
ALWAYS_EXCLUDED_DIR_PARTS = {".git", ".claude", "scripts"}
# 生成物自身は自己参照を避けるため常に除外
ALWAYS_EXCLUDED_NAMES = {SUMMARY_REPORT_NAME, DIFF_PATCH_NAME}


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
    )
    return result.returncode, result.stdout, result.stderr


def get_repo_root() -> Path:
    rc, out, err = run_git(["rev-parse", "--show-toplevel"], cwd=SCRIPT_DIR)
    if rc != 0:
        raise RuntimeError(f"gitリポジトリが見つかりません: {err.strip()}")
    return Path(out.strip())


def get_git_status(repo_root: Path) -> str:
    rc, out, err = run_git(["status", "--short"], cwd=repo_root)
    if rc != 0:
        raise RuntimeError(f"git status --short に失敗しました: {err.strip()}")
    return out


def get_diff_stat(repo_root: Path) -> str:
    rc, out, err = run_git(["diff", "--stat"], cwd=repo_root)
    if rc != 0:
        raise RuntimeError(f"git diff --stat に失敗しました: {err.strip()}")
    return out


def get_diff(repo_root: Path) -> str:
    rc, out, err = run_git(["diff"], cwd=repo_root)
    if rc != 0:
        raise RuntimeError(f"git diff に失敗しました: {err.strip()}")
    return out


def get_untracked_paths(repo_root: Path) -> list[str]:
    """未追跡ファイルを個別に列挙する(未追跡ディレクトリも再帰的に展開される)。
    .gitignore対象は --untracked-files=all でも表示されないため、この時点で自動的に除外済み。
    """
    rc, out, err = run_git(["status", "--porcelain", "--untracked-files=all"], cwd=repo_root)
    if rc != 0:
        raise RuntimeError(f"git status --porcelain に失敗しました: {err.strip()}")
    paths = []
    for line in out.splitlines():
        if line.startswith("?? "):
            paths.append(line[3:].strip())
    return paths


def check_patch_ignored(repo_root: Path) -> bool:
    rc, _out, _err = run_git(["check-ignore", "-q", DIFF_PATCH_NAME], cwd=repo_root)
    return rc == 0


# ---------------------------------------------------------------------------
# JavaScript構文チェック
# ---------------------------------------------------------------------------

def extract_main_script(html_text: str, min_len: int) -> list[tuple[int, str]]:
    """<script src=...>(外部)を除外し、インライン内容が閾値以上のブロックを候補として返す。
    行番号に依存せず、<script ...>...</script> のペアを構造的に走査する。
    """
    candidates = []
    for m in SCRIPT_TAG_RE.finditer(html_text):
        attrs, content = m.group(1), m.group(2)
        has_src = re.search(r"\bsrc\s*=", attrs, re.IGNORECASE) is not None
        if not has_src and len(content) >= min_len:
            start_line = html_text.count("\n", 0, m.start(2)) + 1
            candidates.append((start_line, content))
    return candidates


def js_syntax_check(repo_root: Path, config: dict) -> dict:
    html_path = repo_root / config["target_files"]["html"]
    if not html_path.exists():
        return {"status": "FAIL", "detail": f"{html_path.name} が見つかりません"}

    html_text = html_path.read_text(encoding="utf-8")
    candidates = extract_main_script(html_text, config.get("min_inline_script_length", 500))
    if not candidates:
        return {"status": "FAIL", "detail": "実行対象のインラインscriptブロックを検出できませんでした"}

    note = None
    if len(candidates) > 1:
        candidates.sort(key=lambda c: len(c[1]), reverse=True)
        note = f"インラインscriptブロックが{len(candidates)}件検出されたため、最大のものを対象としました"

    start_line, content = candidates[0]

    try:
        proc = subprocess.run(
            ["node", "--check"], input=content, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        return {"status": "FAIL", "detail": "node コマンドが見つかりません"}

    if proc.returncode == 0:
        return {"status": "OK", "start_line": start_line, "note": note}

    m = re.search(r"\[stdin\]:(\d+)", proc.stderr)
    msg_m = re.search(r"^SyntaxError:.*$", proc.stderr, re.MULTILINE)
    rel_line = int(m.group(1)) if m else None
    abs_line = (start_line - 1) + rel_line if rel_line else None
    if msg_m:
        message = msg_m.group(0)
    else:
        message = proc.stderr.strip().splitlines()[0] if proc.stderr.strip() else "不明なエラー"

    return {"status": "NG", "line": abs_line, "message": message, "note": note}


# ---------------------------------------------------------------------------
# Python構文チェック(ast.parseのみ、py_compileは使わない = __pycache__を作らない)
# ---------------------------------------------------------------------------

def python_syntax_check(repo_root: Path, config: dict) -> dict:
    py_path = repo_root / config["target_files"]["python"]
    if not py_path.exists():
        return {"status": "FAIL", "detail": f"{py_path.name} が見つかりません"}

    src = py_path.read_text(encoding="utf-8")
    try:
        ast.parse(src, filename=py_path.name)
        return {"status": "OK"}
    except SyntaxError as e:
        return {"status": "NG", "line": e.lineno, "col": e.offset, "message": e.msg}


# ---------------------------------------------------------------------------
# フロント/サーバー API簡易突合せ(警告用、失敗扱いにはしない)
# ---------------------------------------------------------------------------

def api_route_diff(repo_root: Path, config: dict) -> dict:
    html_path = repo_root / config["target_files"]["html"]
    py_path = repo_root / config["target_files"]["python"]

    front, back = set(), set()
    if html_path.exists():
        front = set(API_PATTERN_RE.findall(html_path.read_text(encoding="utf-8")))
    if py_path.exists():
        back = set(API_PATTERN_RE.findall(py_path.read_text(encoding="utf-8")))

    return {
        "front_count": len(front),
        "back_count": len(back),
        "only_front": sorted(front - back),
        "only_back": sorted(back - front),
    }


# ---------------------------------------------------------------------------
# 危険パターン共通ロジック
# ---------------------------------------------------------------------------

def compile_danger_patterns(config: dict) -> dict:
    return {key: re.compile(spec["pattern"]) for key, spec in config.get("danger_patterns", {}).items()}


def find_matches_in_line(line: str, compiled: dict, danger_patterns: dict, known_safe: set, watchlist: list) -> list[tuple[str, str]]:
    """1行に対して危険パターン・実名watchlistの一致を調べ、(type, label) のリストを返す。値そのものは返さない。"""
    hits = []
    for key, rx in compiled.items():
        for match in rx.finditer(line):
            if match.group(0) in known_safe:
                continue
            hits.append((key, danger_patterns[key]["label"]))
    for name in watchlist:
        if name and name in line:
            hits.append(("personal_name", "実名watchlistに一致"))
    return hits


# ---------------------------------------------------------------------------
# 危険パターン検出: 追跡済みファイルのgit diff(追加行のみ)
# ---------------------------------------------------------------------------

def scan_diff_danger(diff_text: str, config: dict) -> list[dict]:
    findings = []
    known_safe = set(config.get("known_safe_values", []))
    danger_patterns = config.get("danger_patterns", {})
    compiled = compile_danger_patterns(config)
    watchlist = config.get("personal_name_watchlist", [])

    current_file = None
    new_line_no = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            current_file = None if path == "/dev/null" else (path[2:] if path.startswith("b/") else path)
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_line_no = (int(m.group(1)) - 1) if m else 0
            continue
        if line.startswith("+"):
            new_line_no += 1
            content = line[1:]
            for key, label in find_matches_in_line(content, compiled, danger_patterns, known_safe, watchlist):
                findings.append({"source": "tracked_diff", "file": current_file, "line": new_line_no, "type": key, "label": label})
        elif line.startswith(" "):
            new_line_no += 1
        # '-' で始まる行(削除行)はnew_line_noを増やさない

    return findings


# ---------------------------------------------------------------------------
# 未追跡ファイルのスキャン
# ---------------------------------------------------------------------------

def classify_untracked_path(rel_path: str, config: dict) -> tuple[bool, str | None]:
    """(対象に含めるか, 除外理由 or None) を返す。I/Oは行わない(パス文字列のみで判定)。"""
    scan_cfg = config.get("untracked_scan", {})
    parts = Path(rel_path).parts

    if any(p in ALWAYS_EXCLUDED_DIR_PARTS for p in parts):
        return False, "excluded_dir"
    for d in scan_cfg.get("exclude_dirs", []):
        if d in parts:
            return False, "excluded_dir"

    basename = Path(rel_path).name
    if basename in ALWAYS_EXCLUDED_NAMES:
        return False, "generated_report_file"
    for pattern in scan_cfg.get("exclude_name_patterns", []):
        if fnmatch.fnmatch(basename, pattern):
            return False, "excluded_name_pattern"

    suffix = Path(rel_path).suffix.lower()
    if suffix in set(scan_cfg.get("exclude_extensions", [])):
        return False, "excluded_extension_binary_or_media"

    return True, None


def looks_binary(path: Path, sniff_bytes: int = 8192) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(sniff_bytes)
    except OSError:
        return True
    if b"\x00" in chunk:
        return True
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def scan_untracked_files(repo_root: Path, config: dict) -> dict:
    scan_cfg = config.get("untracked_scan", {})
    max_size = scan_cfg.get("max_file_size_bytes", 2_000_000)

    all_paths = get_untracked_paths(repo_root)
    scanned = []
    skipped = []
    findings = []

    known_safe = set(config.get("known_safe_values", []))
    danger_patterns = config.get("danger_patterns", {})
    compiled = compile_danger_patterns(config)
    watchlist = config.get("personal_name_watchlist", [])

    for rel_path in all_paths:
        include, reason = classify_untracked_path(rel_path, config)
        if not include:
            skipped.append({"path": rel_path, "reason": reason})
            continue

        full_path = repo_root / rel_path
        try:
            size = full_path.stat().st_size
        except OSError:
            skipped.append({"path": rel_path, "reason": "stat_failed"})
            continue

        if size > max_size:
            skipped.append({"path": rel_path, "reason": "too_large"})
            continue

        if looks_binary(full_path):
            skipped.append({"path": rel_path, "reason": "binary_content_detected"})
            continue

        try:
            text = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped.append({"path": rel_path, "reason": "read_failed_or_non_utf8"})
            continue

        scanned.append(rel_path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for key, label in find_matches_in_line(line, compiled, danger_patterns, known_safe, watchlist):
                findings.append({"source": "untracked_file", "file": rel_path, "line": line_no, "type": key, "label": label})

    return {
        "total_untracked": len(all_paths),
        "scanned": scanned,
        "skipped": skipped,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# 構造的な警告(.gitignore変更・大量削除・大量変更)
# ---------------------------------------------------------------------------

def structural_warnings(status_text: str, diff_stat_text: str, config: dict) -> tuple[list[dict], int, int]:
    warnings = []

    for line in status_text.splitlines():
        if len(line) <= 3:
            continue
        path = line[3:].strip()
        if path.endswith(".gitignore"):
            warnings.append({"type": "gitignore_change", "label": ".gitignoreの変更", "file": path})

    ins_m = re.search(r"(\d+) insertions?\(\+\)", diff_stat_text)
    del_m = re.search(r"(\d+) deletions?\(-\)", diff_stat_text)
    insertions = int(ins_m.group(1)) if ins_m else 0
    deletions = int(del_m.group(1)) if del_m else 0

    deletion_threshold = config.get("large_deletion_threshold_lines", 200)
    change_threshold = config.get("large_change_threshold_lines", 500)

    if deletions >= deletion_threshold:
        warnings.append({"type": "large_deletion", "label": f"大量削除の可能性(-{deletions}行、閾値{deletion_threshold}行)"})
    if insertions + deletions >= change_threshold:
        warnings.append({"type": "large_change", "label": f"大量の変更(+{insertions}/-{deletions}行、閾値{change_threshold}行)"})

    return warnings, insertions, deletions


# ---------------------------------------------------------------------------
# diffのマスク処理(レポート/patchファイル掲載前)
# ---------------------------------------------------------------------------

def mask_diff(diff_text: str, config: dict) -> str:
    danger_patterns = config.get("danger_patterns", {})
    mask_targets = [
        (key, re.compile(spec["pattern"]))
        for key, spec in danger_patterns.items()
        if spec.get("mask_in_report", key in SECRET_MASK_TYPES_DEFAULT)
    ]
    known_safe = config.get("known_safe_values", [])

    masked_lines = []
    for line in diff_text.splitlines():
        masked = line
        for value in known_safe:
            if value and value in masked:
                masked = masked.replace(value, "[MASKED:known-safe-value]")
        for key, rx in mask_targets:
            masked = rx.sub(f"[MASKED:{key}]", masked)
        masked_lines.append(masked)
    return "\n".join(masked_lines)


# ---------------------------------------------------------------------------
# 総合判定
# ---------------------------------------------------------------------------

def determine_verdict(js_result: dict, py_result: dict, danger_findings: list, untracked_findings: list, warn_list: list, api_result: dict) -> str:
    if js_result["status"] in ("NG", "FAIL") or py_result["status"] in ("NG", "FAIL"):
        return "FAIL"
    if danger_findings or untracked_findings or warn_list or api_result["only_front"] or api_result["only_back"]:
        return "WARNING"
    return "PASS"


# ---------------------------------------------------------------------------
# 「次に確認すべきこと」の自動生成
# ---------------------------------------------------------------------------

SQL_DANGER_TYPES = {"drop_table", "truncate", "delete_no_where"}
SECRET_TYPES = {"private_key", "openai_key", "aws_access_key", "service_role"}
PERSONAL_TYPES = {"email", "phone", "personal_name"}


def analyze_findings(context: dict) -> dict:
    """次に確認すべきこと・Codexレビュー依頼文の両方で使う判定結果をまとめて返す。"""
    api_result = context["api_result"]
    all_findings = context["danger_findings"] + context["untracked_result"]["findings"]
    warn_list = context["warn_list"]

    return {
        "js_ng": context["js_result"]["status"] in ("NG", "FAIL"),
        "py_ng": context["py_result"]["status"] in ("NG", "FAIL"),
        "untracked_sql": [f for f in all_findings if f["type"] in SQL_DANGER_TYPES and f["source"] == "untracked_file"],
        "tracked_sql": [f for f in all_findings if f["type"] in SQL_DANGER_TYPES and f["source"] == "tracked_diff"],
        "secret_findings": [f for f in all_findings if f["type"] in SECRET_TYPES],
        "personal_findings": [f for f in all_findings if f["type"] in PERSONAL_TYPES],
        "large_deletion": any(w["type"] == "large_deletion" for w in warn_list),
        "gitignore_changed": any(w["type"] == "gitignore_change" for w in warn_list),
        "api_diff": bool(api_result["only_front"] or api_result["only_back"]),
    }


def build_next_steps(context: dict) -> list[str]:
    steps = []
    a = analyze_findings(context)
    verdict = context["verdict"]

    if a["js_ng"]:
        steps.append("JavaScript構文エラーの修正")
    if a["py_ng"]:
        steps.append("Python構文エラーの修正")
    if a["untracked_sql"]:
        steps.append("未追跡SQLファイルで危険なSQL(DROP TABLE/TRUNCATE/WHERE句なしDELETE等)が検出されたため内容確認")
    if a["tracked_sql"]:
        steps.append("追跡済みファイルの差分で危険なSQLが検出されたため内容確認")
    if a["secret_findings"]:
        steps.append("秘密鍵・APIキーらしき文字列の候補確認(値はマスク済み、該当ファイル・行を直接確認してください)")
    if a["api_diff"]:
        steps.append("API候補差異の確認(フロント/サーバーいずれかにのみ存在する/api/候補)")
    if a["large_deletion"]:
        steps.append("大量削除の妥当性確認")
    if a["gitignore_changed"]:
        steps.append(".gitignoreの変更内容確認")
    if a["personal_findings"]:
        steps.append("個人情報候補(メールアドレス・電話番号・実名watchlist一致)の確認")

    if verdict == "PASS":
        steps.append("問題がなければ次の開発作業へ進む")
    else:
        steps.append("Codexレビューへ提出")

    return steps


# ---------------------------------------------------------------------------
# レポート生成(要約 report-finish-task-latest.md)
# ---------------------------------------------------------------------------

def format_js_result(js_result: dict) -> str:
    lines = []
    if js_result["status"] == "OK":
        lines.append(f"- 結果: OK (対象ブロック開始行: {js_result.get('start_line', '?')})")
    elif js_result["status"] == "NG":
        lines.append("- 結果: NG")
        lines.append(f"  - 行(推定): {js_result.get('line', '不明')}")
        lines.append(f"  - メッセージ: {js_result.get('message', '')}")
    else:
        lines.append(f"- 結果: FAIL — {js_result.get('detail', '')}")
    if js_result.get("note"):
        lines.append(f"  - 注記: {js_result['note']}")
    return "\n".join(lines)


def format_py_result(py_result: dict) -> str:
    if py_result["status"] == "OK":
        return "- 結果: OK"
    if py_result["status"] == "NG":
        return (
            f"- 結果: NG\n"
            f"  - 行: {py_result.get('line')} 列: {py_result.get('col')}\n"
            f"  - メッセージ: {py_result.get('message')}"
        )
    return f"- 結果: FAIL — {py_result.get('detail', '')}"


def format_api_result(api_result: dict) -> str:
    lines = [
        f"- フロント側 `/api/...` 候補: {api_result['front_count']}件",
        f"- サーバー側 `/api/...` 候補: {api_result['back_count']}件",
    ]
    if api_result["only_front"]:
        lines.append(f"- フロント側にのみ存在する候補: {', '.join(api_result['only_front'])}")
    else:
        lines.append("- フロント側にのみ存在する候補: なし")
    if api_result["only_back"]:
        lines.append(f"- サーバー側にのみ存在する候補: {', '.join(api_result['only_back'])}")
    else:
        lines.append("- サーバー側にのみ存在する候補: なし")
    lines.append("- 注記: 動的URL・パラメータを含む可能性があるため、差異は参考情報であり失敗扱いではありません。")
    return "\n".join(lines)


def format_danger_findings(tracked_findings: list, untracked_result: dict, warnings: list) -> str:
    lines = []

    lines.append("### 追跡済みファイル(git diff追加行)")
    if tracked_findings:
        for f in tracked_findings:
            loc = f"{f['file']}:{f['line']}" if f.get("file") else "(ファイル不明)"
            lines.append(f"- [{f['type']}] {loc} — {f['label']}(値は表示していません)")
    else:
        lines.append("検出なし")

    lines.append("")
    lines.append("### 未追跡ファイル")
    lines.append(
        f"- 検査対象件数: {len(untracked_result['scanned'])}件 "
        f"(未追跡合計{untracked_result['total_untracked']}件中、除外{len(untracked_result['skipped'])}件)"
    )
    if untracked_result["findings"]:
        for f in untracked_result["findings"]:
            lines.append(f"- [{f['type']}] {f['file']}:{f['line']} — {f['label']}(値は表示していません)")
    else:
        lines.append("検出なし")

    lines.append("")
    lines.append("### 構造的警告")
    if warnings:
        for w in warnings:
            loc = f" ({w['file']})" if w.get("file") else ""
            lines.append(f"- [{w['type']}] {w['label']}{loc}")
    else:
        lines.append("検出なし")

    return "\n".join(lines)


def format_next_steps(steps: list[str]) -> str:
    if not steps:
        return "(なし)"
    return "\n".join(f"- {s}" for s in steps)


def _finding_locations(findings: list, limit: int = 10) -> str:
    locs = [f"{f['file']}:{f['line']}" for f in findings[:limit]]
    text = ", ".join(locs)
    if len(findings) > limit:
        text += f" ほか{len(findings) - limit}件"
    return text


def build_codex_request_text(context: dict) -> str:
    """検出結果に応じて内容が変わる、Codexへのレビュー依頼文を組み立てる。値そのものは含めない。"""
    verdict = context["verdict"]
    a = analyze_findings(context)
    untracked_result = context["untracked_result"]
    insertions = context.get("insertions", 0)
    deletions = context.get("deletions", 0)
    status_text = context["status_text"]

    tracked_files = [l[3:].strip() for l in status_text.splitlines() if l[:2].strip() and l[:2] != "??"]
    untracked_files = [l[3:].strip() for l in status_text.splitlines() if l.startswith("??")]

    lines = [
        "以下はAI秘書(ai-secretary)リポジトリの未コミット変更(追跡済み差分+未追跡ファイル)に対する自動チェック結果です。",
        "構文チェック・API突合せ・危険パターン検出はいずれも簡易的な静的チェックであり、",
        "意味的な正しさやセキュリティの完全性を保証するものではありません。",
        "",
        f"- 総合判定: {verdict}",
        f"- 追跡済み変更: {len(tracked_files)}件(+{insertions}/-{deletions}行、全文は同梱の {DIFF_PATCH_NAME})",
        f"- 未追跡ファイル: {len(untracked_files)}件(うち検査対象 {len(untracked_result['scanned'])}件)",
        "",
        "レビューをお願いしたい観点:",
    ]

    points = []
    if a["js_ng"]:
        points.append("JavaScript構文エラー(index.html)の原因と修正方針")
    if a["py_ng"]:
        points.append("Python構文エラー(local_server.py)の原因と修正方針")
    if a["untracked_sql"]:
        points.append(f"未追跡SQLファイルで検出された危険なSQL操作の妥当性確認: {_finding_locations(a['untracked_sql'])}")
    if a["tracked_sql"]:
        points.append(f"追跡済み差分で検出された危険なSQL操作の妥当性確認: {_finding_locations(a['tracked_sql'])}")
    if a["secret_findings"]:
        points.append(f"秘密鍵・APIキーらしき文字列の候補確認(値はマスク済み): {_finding_locations(a['secret_findings'])}")
    if a["api_diff"]:
        points.append("API突合せで片側にのみ存在する`/api/...`候補が、意図した変更かどうか")
    if a["large_deletion"]:
        points.append("大量削除の妥当性確認")
    if a["gitignore_changed"]:
        points.append(".gitignoreの変更内容確認")
    if a["personal_findings"]:
        points.append(f"個人情報候補(メール/電話番号/実名watchlist)の確認: {_finding_locations(a['personal_findings'])}")
    if not points:
        points.append("構文エラー・危険パターンとも検出されていません。diff全体の設計・実装上の懸念があれば指摘してください。")

    for i, p in enumerate(points, start=1):
        lines.append(f"{i}. {p}")

    lines += [
        "",
        "参照ファイル:",
        f"- 追跡済み差分全文(マスク済み): {DIFF_PATCH_NAME}",
        "- 未追跡ファイルの内容そのものは本資料に含まれていません(ファイル名・行番号のみ)。必要であれば該当ファイルを直接参照してください。",
        "",
        "なお、シークレットらしき値・メールアドレス・電話番号らしき値は本資料内でマスク済みです。",
        "git add/commit/push、ファイル修正など、レビュー結果に基づく実際の変更はこの資料の生成時点では一切行っていません。",
    ]

    return "\n".join(lines)


def build_summary_report(context: dict) -> str:
    now = context["now"]
    verdict = context["verdict"]
    status_text = context["status_text"]
    diff_stat_text = context["diff_stat_text"]
    js_result = context["js_result"]
    py_result = context["py_result"]
    api_result = context["api_result"]
    danger_findings = context["danger_findings"]
    untracked_result = context["untracked_result"]
    warn_list = context["warn_list"]
    next_steps = context["next_steps"]
    patch_ignored = context["patch_ignored"]

    changed_files = status_text.strip("\n") if status_text.strip() else "(変更ファイルなし)"

    tracked_files = [l[3:].strip() for l in status_text.splitlines() if l[:2].strip() and l[:2] != "??"]
    untracked_files = [l[3:].strip() for l in status_text.splitlines() if l.startswith("??")]

    gitignore_note = (
        f"`{DIFF_PATCH_NAME}` は現在の`.gitignore`で除外されています(git check-ignoreで確認済み)。"
        if patch_ignored
        else (
            f"注意: `{DIFF_PATCH_NAME}` は現在の`.gitignore`では除外されません。"
            f"`git status`に表示される可能性があります。"
            f"除外するには `.gitignore` に `{DIFF_PATCH_NAME}`(または `report*.patch`)を追加する案がありますが、"
            f"今回は`.gitignore`を変更していません。"
        )
    )

    report = f"""---
date: {now.strftime('%Y-%m-%d %H:%M:%S')}
tags: [report, finish-task, auto-check]
project: ai-secretary
status: {verdict}
---

# 終了時チェック結果(概要)

## 実行日時
{now.strftime('%Y-%m-%d %H:%M:%S')}

## 総合判定
**{verdict}**

## 変更ファイル一覧 (git status --short)
```
{changed_files}
```
- 追跡済み(変更): {len(tracked_files)}件
- 未追跡(新規): {len(untracked_files)}件

## 構文チェック結果

### JavaScript (index.html インラインscript)
{format_js_result(js_result)}

### Python (local_server.py)
{format_py_result(py_result)}

## API突合せ結果 (簡易警告用)
{format_api_result(api_result)}

## 危険パターン検出結果
{format_danger_findings(danger_findings, untracked_result, warn_list)}

## git diff --stat
```
{diff_stat_text.strip() if diff_stat_text.strip() else '(差分なし)'}
```

## Codexへのレビュー依頼文
{build_codex_request_text(context)}

## 次に確認すべきこと
{format_next_steps(next_steps)}

## 差分ファイルへの案内
追跡済みファイルのマスク済みgit diff全文は `{DIFF_PATCH_NAME}` に分離して保存しています。
{gitignore_note}
"""
    return report


def print_terminal_summary(context: dict) -> None:
    verdict = context["verdict"]
    js_result = context["js_result"]
    py_result = context["py_result"]
    api_result = context["api_result"]
    danger_findings = context["danger_findings"]
    untracked_result = context["untracked_result"]
    warn_list = context["warn_list"]
    status_text = context["status_text"]
    summary_size = context["summary_size"]
    patch_size = context["patch_size"]

    changed_count = len([l for l in status_text.splitlines() if l.strip()])

    print("=" * 60)
    print(f"[終了時チェック] 判定: {verdict}")
    print("=" * 60)
    print(f"変更ファイル: {changed_count}件")
    print(f"JS構文チェック : {js_result['status']}")
    print(f"Python構文チェック: {py_result['status']}")
    print(
        f"API突合せ: front-only {len(api_result['only_front'])}件 / "
        f"back-only {len(api_result['only_back'])}件"
    )
    print(f"危険パターン検出(追跡済み): {len(danger_findings)}件")
    print(
        f"危険パターン検出(未追跡): {len(untracked_result['findings'])}件 "
        f"(検査対象 {len(untracked_result['scanned'])}/{untracked_result['total_untracked']}件)"
    )
    print(f"構造的警告: {len(warn_list)}件")
    print(f"概要レポート: {SUMMARY_REPORT_NAME} ({summary_size/1024:.1f} KB)")
    print(f"差分ファイル: {DIFF_PATCH_NAME} ({patch_size/1024:.1f} KB)")
    print("=" * 60)
    print("git operations (add/commit/push) や自動修正は行っていません。")


def main() -> int:
    now = datetime.now()
    try:
        config = load_config()
        repo_root = get_repo_root()

        status_text = get_git_status(repo_root)
        diff_stat_text = get_diff_stat(repo_root)
        diff_text = get_diff(repo_root)

        js_result = js_syntax_check(repo_root, config)
        py_result = python_syntax_check(repo_root, config)
        api_result = api_route_diff(repo_root, config)
        danger_findings = scan_diff_danger(diff_text, config)
        untracked_result = scan_untracked_files(repo_root, config)
        warn_list, insertions, deletions = structural_warnings(status_text, diff_stat_text, config)
        masked_diff = mask_diff(diff_text, config)
        patch_ignored = check_patch_ignored(repo_root)

        verdict = determine_verdict(
            js_result, py_result, danger_findings, untracked_result["findings"], warn_list, api_result
        )

        context = {
            "now": now,
            "verdict": verdict,
            "status_text": status_text,
            "diff_stat_text": diff_stat_text,
            "js_result": js_result,
            "py_result": py_result,
            "api_result": api_result,
            "danger_findings": danger_findings,
            "untracked_result": untracked_result,
            "warn_list": warn_list,
            "masked_diff": masked_diff,
            "patch_ignored": patch_ignored,
            "insertions": insertions,
            "deletions": deletions,
        }
        context["next_steps"] = build_next_steps(context)

        summary_text = build_summary_report(context)
        patch_text = (masked_diff.strip() + "\n") if masked_diff.strip() else ""

        summary_path = repo_root / SUMMARY_REPORT_NAME
        patch_path = repo_root / DIFF_PATCH_NAME
        summary_path.write_text(summary_text, encoding="utf-8")
        patch_path.write_text(patch_text, encoding="utf-8")

        context["summary_size"] = summary_path.stat().st_size
        context["patch_size"] = patch_path.stat().st_size

        print_terminal_summary(context)
        return 0

    except Exception as e:  # スクリプト自体の実行失敗 = FAIL
        print("=" * 60)
        print("[終了時チェック] 判定: FAIL (スクリプト実行中にエラー)")
        print(f"エラー内容: {e}")
        print("=" * 60)
        print("git operations や自動修正は行っていません。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
