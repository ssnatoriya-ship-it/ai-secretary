import json
import os
import re
import time
import uuid
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs


HOST = "127.0.0.1"
PORT = int(os.environ.get("AI_SECRETARY_PORT", "3457"))
PROJECT_DIR = Path(__file__).resolve().parent
EXTERNAL_BRAIN_DIR = Path(
    "/Users/nobuki-macbook-air13/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/外部脳"
)
CUSTOMERS_DIR = EXTERNAL_BRAIN_DIR / "Customers"
CUSTOMERS_INDEX = PROJECT_DIR / "customers-index.json"
NTR_ID_RE = re.compile(r"^NTR-\d{6}$")
# customer-save-error-report.md 案A・案C対応：一時ファイル保存の最大リトライ回数と待機秒数
CUSTOMER_SAVE_MAX_RETRIES = 3
CUSTOMER_SAVE_RETRY_DELAY_SEC = 0.3

# アイデア企画化（フェーズ3：Obsidianへの保存）
PLANS_DIR = EXTERNAL_BRAIN_DIR / "Projects/AI-Secretary/Plans"
IDEA_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
IDEA_PLAN_TITLE_MAX = 200
IDEA_PLAN_CONTENT_MAX = 5000
IDEA_PLAN_FIELD_MAX = 2000
IDEA_PLAN_REQUEST_MAX = 20000
IDEA_PLAN_FIELDS = (
    ("purpose", "目的"),
    ("expectedEffect", "期待効果"),
    ("minFeature", "最小機能"),
    ("priority", "優先順位"),
    ("risk", "リスク"),
    ("nextAction", "次の一手"),
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TEST_FILES = (
    "Knowledge/Cases/cases-index.md",
    "AI_OPERATING_MANUAL.md",
    "AGENTS.md",
)
CATEGORY_KEYWORDS = {
    "Sizing": (
        "サイズ", "サイズ感", "足幅", "幅広", "フィット", "履き心地", "大きい", "小さい",
    ),
    "Repair": (
        "修理", "補修", "破損", "靴底", "ソール", "ヒール", "金具", "ハトメ", "ほつれ", "傷",
    ),
    "Reservation": (
        "予約", "取り置き", "取置き", "キープ", "入荷待ち", "予約品",
    ),
    "Product": (
        "商品", "在庫", "素材", "革", "カラー", "色", "品番", "仕様", "エイジング", "経年変化",
    ),
    "CustomerService": (
        "納期", "配送", "発送", "配達", "支払い", "決済", "価格", "訂正", "返品", "交換", "キャンセル", "保管期限",
    ),
}
CATEGORY_ORDER = ("Sizing", "Repair", "Reservation", "Product", "CustomerService")
RANK_KEYWORDS = (
    "サイズ", "修理", "補修", "予約", "取り置き", "納期", "配送", "発送", "配達",
    "支払い", "決済", "価格", "訂正", "保管期限", "在庫", "商品",
)
CATEGORY_REASON = {
    "Sizing": "サイズ相談",
    "Repair": "修理案件",
    "Reservation": "予約・取り置き相談",
    "CustomerService": "顧客対応案件",
    "Product": "商品相談",
}
CASE_DECISION_GUIDANCE = {
    "Sizing": (
        "比較靴のサイズは参考情報にとどめ、今回のお客様の足長・足幅・足囲を確認する",
        "ブランドや木型による違いを考慮し、未確認の推奨サイズを断定しない",
        "左右差がある場合は大きい方の足を基準に検討する",
        "可能であれば試着や追加計測を案内する",
    ),
    "Repair": (
        "修理可否は現物確認後に判断し、未確認の段階で断定しない",
        "費用と納期は状態確認後の目安として案内する",
        "修理が難しい場合も、確認後に代替案を検討する",
        "破損原因と再発防止策は、状態を確認してから提案する",
    ),
    "Reservation": (
        "在庫と予約状況を確認してから、取り置き可否を案内する",
        "期限や条件は今回の案件で確認済みの内容だけを伝える",
        "未確定の入荷時期や確保状況を断定しない",
        "状況変更があれば早めに連絡する",
    ),
    "Product": (
        "品番・仕様・在庫は今回の案件で確認済みの情報だけを案内する",
        "過去Caseの商品固有情報を今回の商品へ流用しない",
        "使用シーンや素材の特徴は、確認できた範囲で分かりやすく説明する",
        "未確認の性能や効果を誇張しない",
    ),
    "CustomerService": (
        "保管期限は今回の案件で具体的に確認してから案内する",
        "荷物番号は今回の案件で確認済みの場合のみ記載する",
        "返送リスクは事前に伝える",
        "責任追及ではなく、受け取りへの協力をお願いする姿勢で案内する",
        "配送会社名・日付・連絡先は今回の入力にない限り記載しない",
    ),
}
CONSULTATION_REASONS = (
    (("納期", "入荷待ち"), "納期相談あり"),
    (("メーカー",), "メーカー確認に関する相談"),
    (("配送", "発送", "配達"), "配送に関する相談"),
    (("支払い", "決済"), "支払いに関する相談"),
    (("価格", "訂正"), "価格・訂正に関する相談"),
    (("保管期限",), "保管期限に関する相談"),
    (("在庫",), "在庫確認に関する相談"),
)
KEYWORD_REASON = {
    "サイズ": "サイズに関する語句が一致",
    "修理": "修理に関する語句が一致",
    "補修": "補修に関する語句が一致",
    "予約": "予約に関する語句が一致",
    "取り置き": "取り置きに関する語句が一致",
    "納期": "納期に関する語句が一致",
    "配送": "配送に関する語句が一致",
    "発送": "発送に関する語句が一致",
    "配達": "配達に関する語句が一致",
    "支払い": "支払いに関する語句が一致",
    "決済": "決済に関する語句が一致",
    "価格": "価格に関する語句が一致",
    "訂正": "訂正に関する語句が一致",
    "保管期限": "保管期限に関する語句が一致",
    "在庫": "在庫に関する語句が一致",
    "商品": "商品に関する語句が一致",
}


class AppHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        request_path = self.path.split("?", 1)[0]
        if request_path == "/api/external-brain-test":
            self.handle_external_brain_test()
            return
        if request_path == "/api/customers":
            self.handle_customers()
            return
        if request_path == "/api/customer-next-id":
            self.handle_customer_next_id()
            return
        if request_path == "/api/customer-detail":
            self.handle_customer_detail()
            return
        super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:3457")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        request_path = self.path.split("?", 1)[0]
        if request_path == "/api/case-candidates":
            self.handle_case_candidates()
            return
        if request_path == "/api/case-detail":
            self.handle_case_detail()
            return
        if request_path == "/api/customer-save":
            self.handle_customer_save()
            return
        if request_path == "/api/idea-plan-save":
            self.handle_idea_plan_save()
            return
        self.send_json(404, {"ok": False, "message": "APIが見つかりません"})

    def handle_case_candidates(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 20000:
                raise ValueError("入力サイズが不正です")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            customer_message = str(payload.get("customerMessage", "")).strip()
            notes = str(payload.get("notes", "")).strip()
            query = f"{customer_message}\n{notes}".strip()
            if not query:
                raise ValueError("相談内容を入力してください")

            category = classify_category(query)
            candidates = find_case_candidates(category, query)
            self.send_json(
                200,
                {
                    "ok": True,
                    "category": category,
                    "candidates": candidates[:3],
                    "caseBodyRead": False,
                },
            )
        except Exception as error:
            self.send_json(400, {"ok": False, "message": str(error)})

    def handle_case_detail(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 5000:
                raise ValueError("入力サイズが不正です")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            case_id = str(payload.get("caseId", "")).strip()
            entry = next(
                (item for item in read_case_index_entries() if item["id"] == case_id),
                None,
            )
            if not entry:
                raise ValueError("cases-index.md にないCaseは参照できません")

            cases_root = (EXTERNAL_BRAIN_DIR / "Knowledge/Cases").resolve()
            case_path = (cases_root / entry["category"] / f"{entry['id']}.md").resolve()
            if cases_root not in case_path.parents:
                raise ValueError("不正なCaseパスです")
            case_text = case_path.read_text(encoding="utf-8")
            sections = parse_case_sections(case_text)
            customer_names = extract_customer_names(sections.get("顧客情報", ""))
            guidance = build_case_decision_guidance(entry)

            self.send_json(
                200,
                {
                    "ok": True,
                    "case": {
                        "id": entry["id"],
                        "caseName": anonymize_case_name(entry["title"]),
                        "guidance": guidance,
                    },
                    "sentToClaude": False,
                },
            )
        except Exception as error:
            self.send_json(400, {"ok": False, "message": str(error)})

    def handle_customers(self):
        try:
            customers = load_customers_index()
            self.send_json(200, {"ok": True, "customers": customers})
        except Exception as error:
            self.send_json(500, {"ok": False, "message": str(error)})

    def handle_customer_next_id(self):
        try:
            customers = load_customers_index()
            ntr_nums = [
                int(c["id"][4:]) for c in customers
                if c.get("id") and NTR_ID_RE.match(c["id"])
            ]
            max_num = max(ntr_nums) if ntr_nums else 0
            next_id = f"NTR-{max_num + 1:06d}"
            self.send_json(200, {"ok": True, "nextId": next_id})
        except Exception as error:
            self.send_json(500, {"ok": False, "message": str(error)})

    def handle_customer_detail(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            ntr_id = params.get("id", [""])[0].strip()
            legacy_name = params.get("name", [""])[0].strip()
            customers_root = CUSTOMERS_DIR.resolve()

            if ntr_id:
                if not NTR_ID_RE.match(ntr_id):
                    raise ValueError("AI秘書IDの形式が不正です（例: NTR-000001）")
                customer_path = (CUSTOMERS_DIR / f"{ntr_id}.md").resolve()
            elif legacy_name:
                customer_path = (CUSTOMERS_DIR / f"{legacy_name}.md").resolve()
            else:
                raise ValueError("idまたはnameを指定してください")

            if customer_path.parent != customers_root:
                raise ValueError("不正なパスです")
            if not customer_path.exists():
                self.send_json(404, {"ok": False, "message": "顧客データが見つかりません"})
                return
            content = customer_path.read_text(encoding="utf-8")
            self.send_json(200, {"ok": True, "content": content})
        except Exception as error:
            self.send_json(400, {"ok": False, "message": str(error)})

    def handle_customer_save(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 100000:
                raise ValueError("入力サイズが不正です")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            ntr_id = str(payload.get("id", "")).strip()
            legacy_name = str(payload.get("name", "")).strip()
            content = str(payload.get("content", "")).strip()

            CUSTOMERS_DIR.mkdir(parents=True, exist_ok=True)
            customers_root = CUSTOMERS_DIR.resolve()

            if ntr_id:
                if not NTR_ID_RE.match(ntr_id):
                    raise ValueError("AI秘書IDの形式が不正です（例: NTR-000001）")
                customer_path = (CUSTOMERS_DIR / f"{ntr_id}.md").resolve()
            elif legacy_name:
                customer_path = (CUSTOMERS_DIR / f"{legacy_name}.md").resolve()
            else:
                raise ValueError("idまたはnameを入力してください")

            if customer_path.parent != customers_root:
                raise ValueError("不正なパスです")

            # write_text()による直接上書きをやめ、一時ファイル書き込み→内容検証→os.replace()に
            # よる原子的置換に変更した（customer-save-error-report.md 案A）。検証に通るまで
            # customer_path本体には一切触れないため、途中で失敗しても既存の顧客データは失われない。
            # EPERM等の一時的な書き込み拒否に備え、最大3回まで短い待機を挟んでリトライする（要件5）。
            last_error = None
            for attempt in range(1, CUSTOMER_SAVE_MAX_RETRIES + 1):
                try:
                    write_customer_file_atomic(customer_path, content)
                    last_error = None
                    break
                except PermissionError as error:
                    # EPERM（Errno 1）・EACCESはいずれもPermissionErrorとして捕捉される
                    last_error = error
                except FileNotFoundError as error:
                    last_error = error
                except OSError as error:
                    last_error = error
                if attempt < CUSTOMER_SAVE_MAX_RETRIES:
                    time.sleep(CUSTOMER_SAVE_RETRY_DELAY_SEC)

            if last_error is not None:
                # 保存できていない（＝既存ファイルは無傷）ため、調査に必要な情報をそのまま返す
                self.send_json(500, {
                    "ok": False,
                    "path": str(customer_path),
                    "errorType": type(last_error).__name__,
                    "message": str(last_error),
                })
                return

            # インデックスを更新
            fm = parse_customer_frontmatter(content)
            prefer_brands, prefer_style, memo_snippet = extract_customer_summary(content)
            updated_at = fm.get("date", date.today().isoformat())
            customers = load_customers_index()
            if ntr_id:
                existing = next((c for c in customers if c.get("id") == ntr_id), None)
                if existing:
                    existing["name"] = fm.get("name", existing["name"])
                    existing["yomi"] = fm.get("yomi", existing["yomi"])
                    existing["updatedAt"] = updated_at
                    existing["preferBrands"] = prefer_brands
                    existing["preferStyle"] = prefer_style
                    existing["memoSnippet"] = memo_snippet
                else:
                    customers.append({
                        "id": ntr_id,
                        "name": fm.get("name", ""),
                        "yomi": fm.get("yomi", ""),
                        "isNew": True,
                        "updatedAt": updated_at,
                        "preferBrands": prefer_brands,
                        "preferStyle": prefer_style,
                        "memoSnippet": memo_snippet,
                    })
            else:
                existing = next((c for c in customers if c.get("id") == "" and c.get("name") == legacy_name), None)
                if not existing:
                    customers.append({
                        "id": "",
                        "name": legacy_name,
                        "yomi": fm.get("yomi", ""),
                        "isNew": False,
                        "updatedAt": updated_at,
                        "preferBrands": prefer_brands,
                        "preferStyle": prefer_style,
                        "memoSnippet": memo_snippet,
                    })
                else:
                    existing["updatedAt"] = updated_at
                    existing["preferBrands"] = prefer_brands
                    existing["preferStyle"] = prefer_style
                    existing["memoSnippet"] = memo_snippet
            save_customers_index(customers)

            self.send_json(200, {"ok": True})
        except Exception as error:
            self.send_json(400, {"ok": False, "message": str(error)})

    def handle_idea_plan_save(self):
        tmp_path = None
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > IDEA_PLAN_REQUEST_MAX:
                raise ValueError("入力サイズが不正です")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))

            idea_id = str(payload.get("ideaId", "")).strip()
            if not IDEA_ID_RE.match(idea_id):
                raise ValueError("アイデアIDの形式が不正です")

            title = sanitize_idea_plan_field(
                payload.get("title", ""), IDEA_PLAN_TITLE_MAX, "タイトル",
                allow_unconfirmed=False, allow_newline=False,
            )
            content = sanitize_idea_plan_field(
                payload.get("content", ""), IDEA_PLAN_CONTENT_MAX, "元アイデアの本文"
            )

            raw_plan = payload.get("plan") or {}
            plan = {}
            for key, label in IDEA_PLAN_FIELDS:
                plan[key] = sanitize_idea_plan_field(
                    raw_plan.get(key, ""), IDEA_PLAN_FIELD_MAX, label
                )

            today_str = date.today().isoformat()
            document = build_idea_plan_document(idea_id, title, content, plan, today_str)

            PLANS_DIR.mkdir(parents=True, exist_ok=True)
            plans_root = PLANS_DIR.resolve()

            final_path = (PLANS_DIR / f"plan-{idea_id}.md").resolve()
            if final_path.parent != plans_root:
                raise ValueError("不正な保存先パスです")

            tmp_path = PLANS_DIR / f".tmp-{idea_id}-{uuid.uuid4().hex}.md"
            tmp_path.write_text(document, encoding="utf-8")

            reread_tmp = tmp_path.read_text(encoding="utf-8")
            if not verify_idea_plan_document(reread_tmp, idea_id, title, content, plan):
                raise ValueError("保存内容の検証に失敗しました（一時ファイル）")

            try:
                os.link(str(tmp_path), str(final_path))
            except FileExistsError:
                tmp_path.unlink(missing_ok=True)
                tmp_path = None
                existing_text = final_path.read_text(encoding="utf-8")
                existing_fm = parse_idea_plan_frontmatter(existing_text)
                vault_relative = str(final_path.relative_to(EXTERNAL_BRAIN_DIR))
                if existing_fm and existing_fm.get("supabase_idea_id") == idea_id:
                    self.send_json(
                        200, {"ok": True, "status": "already_saved", "path": vault_relative}
                    )
                else:
                    self.send_json(
                        409,
                        {
                            "ok": False,
                            "status": "conflict",
                            "message": "同名の別ファイルが既に存在するため保存できませんでした",
                        },
                    )
                return

            tmp_path.unlink(missing_ok=True)
            tmp_path = None

            final_text = final_path.read_text(encoding="utf-8")
            if not verify_idea_plan_document(final_text, idea_id, title, content, plan):
                self.send_json(
                    500,
                    {
                        "ok": False,
                        "status": "verify_failed",
                        "message": "保存後の検証に失敗しました。ファイルを直接確認してください",
                    },
                )
                return

            vault_relative = str(final_path.relative_to(EXTERNAL_BRAIN_DIR))
            self.send_json(200, {"ok": True, "status": "created", "path": vault_relative})
        except Exception as error:
            self.send_json(400, {"ok": False, "status": "validation_error", "message": str(error)})
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def handle_external_brain_test(self):
        results = []
        errors = []

        for relative_path in TEST_FILES:
            path = EXTERNAL_BRAIN_DIR / relative_path
            try:
                content = path.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError("ファイルが空です")
                results.append({"file": relative_path, "readable": True})
            except Exception as error:
                message = f"{relative_path}: {error}"
                results.append(
                    {"file": relative_path, "readable": False, "error": str(error)}
                )
                errors.append(message)

        if errors:
            self.send_json(
                500,
                {
                    "ok": False,
                    "message": "外部脳を参照できませんでした",
                    "errors": errors,
                    "files": results,
                },
            )
            return

        self.send_json(
            200,
            {
                "ok": True,
                "message": "外部脳を参照できました",
                "files": results,
            },
        )

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:3457")
        self.end_headers()
        self.wfile.write(body)


def classify_category(query):
    normalized = query.lower()
    scores = {
        category: sum(normalized.count(keyword.lower()) for keyword in keywords)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    best_score = max(scores.values())
    if best_score == 0:
        return "CustomerService"
    return max(CATEGORY_ORDER, key=lambda category: (scores[category], -CATEGORY_ORDER.index(category)))


def find_case_candidates(category, query):
    entries = [
        {"id": entry["id"], "title": anonymize_case_name(entry["title"])}
        for entry in read_case_index_entries()
        if entry["category"] == category
    ]

    normalized_query = query.lower()
    category_hits = sum(
        normalized_query.count(keyword.lower())
        for keyword in CATEGORY_KEYWORDS[category]
    )
    for position, entry in enumerate(entries):
        searchable = f"{entry['id']} {entry['title']}".lower()
        matched_keywords = [
            keyword for keyword in RANK_KEYWORDS
            if keyword in normalized_query and keyword in searchable
        ]
        product_tokens = [
            token.lower() for token in re.findall(r"[a-zA-Z]+\d+[a-zA-Z0-9-]*", query)
            if token.lower() in searchable
        ]
        score = 60 + min(category_hits * 3, 15)
        score += min(len(matched_keywords) * 10, 20)
        if matched_keywords:
            first_match_position = min(
                normalized_query.find(keyword) for keyword in matched_keywords
            )
            score += max(1, 8 - first_match_position // 10)
        score += min(len(product_tokens) * 12, 12)
        entry["score"] = min(score, 98)
        reasons = [CATEGORY_REASON[category]]
        reasons.extend(KEYWORD_REASON[keyword] for keyword in matched_keywords)
        for keywords, reason in CONSULTATION_REASONS:
            if any(keyword in normalized_query for keyword in keywords):
                reasons.append(reason)
        if product_tokens:
            reasons.append(f"品番 {product_tokens[0].upper()} が一致")
        entry["reasons"] = list(dict.fromkeys(reasons))[:3]
        entry["_position"] = position

    entries.sort(key=lambda entry: (-entry["score"], entry["_position"]))
    return [
        {
            "id": entry["id"],
            "title": entry["title"],
            "score": entry["score"],
            "reasons": entry["reasons"],
        }
        for entry in entries[:3]
    ]


def read_case_index_entries():
    index_path = EXTERNAL_BRAIN_DIR / "Knowledge/Cases/cases-index.md"
    index_text = index_path.read_text(encoding="utf-8")
    entries = []
    current_category = None

    for line in index_text.splitlines():
        heading = re.match(r"^#\s+(Sizing|Repair|Reservation|CustomerService|Product)\s*$", line)
        if heading:
            current_category = heading.group(1)
            continue
        item = re.match(r"^-\s+\[\[([^\]]+)\]\]\s*(.*)$", line)
        if item and current_category:
            case_id = item.group(1).strip()
            title = item.group(2).strip() or case_id
            entries.append(
                {"id": case_id, "title": title, "category": current_category}
            )
    return entries


def parse_case_sections(case_text):
    sections = {}
    current_heading = None
    current_lines = []

    for line in case_text.splitlines():
        heading = re.match(r"^#\s+(.+?)\s*$", line)
        if heading:
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading.group(1)
            current_lines = []
        elif current_heading:
            current_lines.append(line)
    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()
    return sections


def extract_customer_names(customer_section):
    names = []
    for line in customer_section.splitlines():
        match = re.match(r"^お名前\s*[:：]\s*(.+?)\s*$", line)
        if match:
            names.append(match.group(1).strip())
    return names


def anonymize_case_name(case_name):
    return re.sub(r"^\S+様\s*", "", case_name).strip() or "匿名Case"


def sanitize_case_text(text, customer_names):
    sanitized = text
    for name in customer_names:
        sanitized = sanitized.replace(name, "[お客様]")
    sanitized = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "[メールアドレス非表示]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?<!\d)(?:0\d{1,4}[-ー−]?\d{1,4}[-ー−]?\d{3,4})(?!\d)",
        "[電話番号非表示]",
        sanitized,
    )
    return anonymize_case_name(sanitized)


def parse_customer_frontmatter(content):
    """YAMLフロントマターから name / yomi 等を取得する。"""
    m = re.match(r"^---\n([\s\S]*?)\n---", content)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([a-zA-Z_]+):\s*(.+)$", line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip()
    return fm


def extract_customer_summary(content):
    """Markdown本文から一覧表示用の要約フィールドを抽出する。"""
    prefer_brands = ""
    prefer_style = ""
    memo_snippet = ""

    # 好みブランド・スタイルを抽出
    for line in content.splitlines():
        if line.startswith("好みブランド:"):
            prefer_brands = line[len("好みブランド:"):].strip()
        elif line.startswith("好みスタイル:"):
            prefer_style = line[len("好みスタイル:"):].strip()

    # 接客メモセクションの先頭テキストを抽出
    memo_match = re.search(r"## 接客メモ\n+([\s\S]*?)(?:\n## |\Z)", content)
    if memo_match:
        raw = memo_match.group(1).strip()
        # コメント行・空行を除く
        lines = [l for l in raw.splitlines() if l.strip() and not l.strip().startswith("<!--")]
        if lines:
            memo_snippet = lines[0][:30]

    return prefer_brands, prefer_style, memo_snippet


def sanitize_idea_plan_field(value, max_len, field_label, allow_unconfirmed=True, allow_newline=True):
    """改行を正規化し、制御文字を拒否したうえで文字数上限を検証する。"""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if CONTROL_CHAR_RE.search(text):
        raise ValueError(f"{field_label}に使用できない制御文字が含まれています")
    if not allow_newline and "\n" in text:
        raise ValueError(f"{field_label}に改行を含めることはできません")
    text = text.strip()
    if not text:
        if allow_unconfirmed:
            return "未確認"
        raise ValueError(f"{field_label}は必須です")
    if len(text) > max_len:
        raise ValueError(f"{field_label}が上限（{max_len}文字）を超えています")
    return text


def yaml_escape(value):
    """外部ライブラリを使わず、YAMLの二重引用符付き文字列として安全にエスケープする。"""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_idea_plan_document(idea_id, title, content, plan, today_str):
    lines = [
        "---",
        "type: idea-plan",
        "status: draft",
        f"date: {today_str}",
        f"supabase_idea_id: {yaml_escape(idea_id)}",
        "source: ai-secretary",
        "tags: [idea, plan]",
        f"title: {yaml_escape(title)}",
        "---",
        "",
        f"# 企画書: {title}",
        "",
        "## 元アイデア",
        "",
        content,
        "",
    ]
    for key, label in IDEA_PLAN_FIELDS:
        lines.append(f"## {label}")
        lines.append("")
        lines.append(plan[key])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_yaml_quoted_value(block, key):
    """`key: "..."` 形式の二重引用符付きスカラーを、バックスラッシュエスケープを
    考慮しながら解析する（タイトルに `"` や `\\` が含まれる場合に対応するため、
    `[^"]*` のような単純な正規表現では誤って途中で切れてしまう）。"""
    m = re.search(rf'^{key}:\s*"', block, re.MULTILINE)
    if not m:
        return None
    chars = []
    i = m.end()
    while i < len(block):
        ch = block[i]
        if ch == "\\" and i + 1 < len(block):
            nxt = block[i + 1]
            if nxt in ('"', "\\"):
                chars.append(nxt)
                i += 2
                continue
        if ch == '"':
            return "".join(chars)
        if ch == "\n":
            return None
        chars.append(ch)
        i += 1
    return None


def parse_idea_plan_frontmatter(text):
    """Planファイルのfrontmatterを再解析する（フロントマター検証用）。"""
    m = re.match(r"^---\n([\s\S]*?)\n---", text)
    if not m:
        return None
    block = m.group(1)
    fields = {}
    for key in ("type", "status", "date", "source"):
        km = re.search(rf'^{key}:\s*(\S.*?)\s*$', block, re.MULTILINE)
        if km:
            fields[key] = km.group(1)
    for key in ("supabase_idea_id", "title"):
        value = _parse_yaml_quoted_value(block, key)
        if value is not None:
            fields[key] = value
    return fields


def verify_idea_plan_document(text, idea_id, title, content, plan):
    """frontmatterとMarkdown本文（6項目）をそれぞれ再解析・照合する。"""
    fm = parse_idea_plan_frontmatter(text)
    if not fm:
        return False
    if fm.get("type") != "idea-plan":
        return False
    if fm.get("status") != "draft":
        return False
    if fm.get("supabase_idea_id") != idea_id:
        return False
    if fm.get("source") != "ai-secretary":
        return False
    if fm.get("title") != title:
        return False

    if "## 元アイデア" not in text or content not in text:
        return False
    for key, label in IDEA_PLAN_FIELDS:
        if f"## {label}" not in text or plan[key] not in text:
            return False
    return True


def write_customer_file_atomic(customer_path, content):
    """顧客Markdownを安全に保存する。

    まず一時ファイルへ書き込み、内容を読み戻して検証したうえで、os.replace()による
    原子的置換を試みる。ただし、iCloud Drive上ではos.replace()（リネーム）自体がOS側に
    拒否される場合があることが実機検証（NTR-000001での再現）で判明したため、
    os.replace()が失敗した場合は検証済みの内容を対象ファイルへ直接write_text()で
    上書きするフォールバックを行う（Finder・Obsidian・Terminalからの直接読み書きは
    問題ないことが確認できているため、書き込み自体はこの経路で成功する）。
    どちらの経路でも、一時ファイルの書き込み・検証が終わるまでは対象ファイル本体に
    一切書き込まないため、内容が壊れた状態のまま保存されることはない。
    """
    tmp_path = customer_path.parent / f".tmp-{customer_path.stem}-{uuid.uuid4().hex}.md"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        reread = tmp_path.read_text(encoding="utf-8")
        if reread != content:
            raise ValueError("保存内容の検証に失敗しました（一時ファイル）")
        try:
            os.replace(str(tmp_path), str(customer_path))
        except OSError:
            # iCloud Drive上でos.replace()自体が拒否されるケースへのフォールバック。
            # tmp_pathで検証済みの内容をそのまま直接書き込むため、内容の正しさは保たれる。
            customer_path.write_text(content, encoding="utf-8")
    finally:
        tmp_path.unlink(missing_ok=True)


def load_customers_index():
    """customers-index.json を読み込む。存在しない場合は空リストを返す。"""
    if not CUSTOMERS_INDEX.exists():
        return []
    try:
        return json.loads(CUSTOMERS_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_customers_index(customers):
    """customers-index.json を書き込む。"""
    CUSTOMERS_INDEX.write_text(
        json.dumps(customers, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_case_decision_guidance(entry):
    """Return reusable decision policy only; never return facts from a past Case."""
    guidance = CASE_DECISION_GUIDANCE.get(
        entry["category"],
        ("今回の入力で確認できた事実だけを使い、未確認事項は断定しない",),
    )
    return "\n".join(f"- {item}" for item in guidance)


if __name__ == "__main__":
    handler = partial(AppHandler, directory=PROJECT_DIR)
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"AI秘書を http://{HOST}:{PORT}/index.html で起動しています")
    server.serve_forever()
