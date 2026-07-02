import json
import os
import re
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
            CUSTOMERS_DIR.mkdir(parents=True, exist_ok=True)
            customers = sorted(
                f.stem for f in CUSTOMERS_DIR.glob("*.md")
                if not f.name.startswith("_")
            )
            self.send_json(200, {"ok": True, "customers": customers})
        except Exception as error:
            self.send_json(500, {"ok": False, "message": str(error)})

    def handle_customer_detail(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            name = params.get("name", [""])[0].strip()
            if not name:
                raise ValueError("顧客名を指定してください")
            customers_root = CUSTOMERS_DIR.resolve()
            customer_path = (CUSTOMERS_DIR / f"{name}.md").resolve()
            if customers_root not in customer_path.parents and customer_path.parent != customers_root:
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
            name = str(payload.get("name", "")).strip()
            content = str(payload.get("content", "")).strip()
            if not name:
                raise ValueError("顧客名を入力してください")
            CUSTOMERS_DIR.mkdir(parents=True, exist_ok=True)
            customers_root = CUSTOMERS_DIR.resolve()
            customer_path = (CUSTOMERS_DIR / f"{name}.md").resolve()
            if customers_root not in customer_path.parents and customer_path.parent != customers_root:
                raise ValueError("不正なパスです")
            customer_path.write_text(content, encoding="utf-8")
            self.send_json(200, {"ok": True})
        except Exception as error:
            self.send_json(400, {"ok": False, "message": str(error)})

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
