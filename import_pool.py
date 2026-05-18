import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set

import gspread
from google.oauth2.service_account import Credentials

GSHEET_ID = os.getenv("GSHEET_ID", "").strip()
GSVC_JSON = os.getenv("GSVC_JSON", "").strip()
POOL_SHEET_NAME = "POOL"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ===== Parser =====
SEP_RE = re.compile(r"=+\s*$")
EMAIL_RE = re.compile(r"Account\s*ChatGPT:\s*(\S+)", re.IGNORECASE)
PASS_RE = re.compile(r"pass:\s*(\S+)", re.IGNORECASE)
ANY_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

def is_hotmail(email: str, include_outlook: bool = True) -> bool:
    e = (email or "").lower().strip()
    return e.endswith("@hotmail.com") or (include_outlook and e.endswith("@outlook.com"))

def parse_blocks(raw: str) -> List[str]:
    lines = raw.splitlines()
    blocks, cur = [], []
    for line in lines:
        if SEP_RE.match(line.strip()):
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b.strip()]

def extract_item(block: str, only_hotmail: bool = False) -> Optional[Dict[str, str]]:
    email = None
    pw = None
    mail_code = None

    m = EMAIL_RE.search(block)
    if m:
        email = m.group(1).strip()

    m = PASS_RE.search(block)
    if m:
        pw = m.group(1).strip()

    pipe_lines = [ln.strip() for ln in block.splitlines() if "|" in ln]
    if pipe_lines:
        mail_code = max(pipe_lines, key=len)

    if not email or not pw or not mail_code:
        return None

    if only_hotmail and (not is_hotmail(email, include_outlook=True)):
        return None

    return {"email": email, "pw": pw, "mail_code": mail_code}

def build_secret(template: str, it: Dict[str, str]) -> str:
    # ⚠️ dùng {pw} thay vì {pass}
    return template.format(
        email=it["email"],
        pw=it["pw"],
        mail_code=it["mail_code"],
    )

# ===== Sheet helpers =====
def connect_ws():
    if not GSHEET_ID:
        raise RuntimeError("Missing GSHEET_ID env")
    if not GSVC_JSON or not os.path.exists(GSVC_JSON):
        raise RuntimeError(f"GSVC_JSON not found: {GSVC_JSON}")

    creds = Credentials.from_service_account_file(GSVC_JSON, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GSHEET_ID)
    return sh.worksheet(POOL_SHEET_NAME)

def next_item_ids(existing_ids: List[str], n: int) -> List[str]:
    mx = 0
    for s in existing_ids:
        s = (s or "").strip()
        m = re.match(r"I(\d+)$", s)
        if m:
            mx = max(mx, int(m.group(1)))
    start = mx + 1
    return [f"I{(start+i):03d}" for i in range(n)]

def normalize_mail_code(mc: str) -> str:
    return (mc or "").strip()

def extract_email_from_secret(secret: str) -> Optional[str]:
    if not secret:
        return None
    m = ANY_EMAIL_RE.search(secret)
    return m.group(1).lower() if m else None

def extract_mailcode_from_secret(secret: str) -> Optional[str]:
    if not secret:
        return None
    pipe_lines = [ln.strip() for ln in secret.splitlines() if "|" in ln]
    if not pipe_lines:
        return None
    return normalize_mail_code(max(pipe_lines, key=len))

def build_existing_sets(ws) -> Tuple[Set[str], Set[str]]:
    col_c = ws.col_values(3)[1:]  # bỏ header
    emails, mailcodes = set(), set()
    for s in col_c:
        em = extract_email_from_secret(s)
        if em:
            emails.add(em)
        mc = extract_mailcode_from_secret(s)
        if mc:
            mailcodes.add(mc)
    return emails, mailcodes

def find_next_empty_rows(ws, start_row: int, needed: int) -> List[int]:
    col_a = ws.col_values(1)
    col_c = ws.col_values(3)

    def cell_value(col: List[str], row: int) -> str:
        idx = row - 1
        if idx < 0:
            return ""
        if idx >= len(col):
            return ""
        return (col[idx] or "").strip()

    rows = []
    r = max(2, int(start_row))
    while len(rows) < needed:
        a = cell_value(col_a, r)
        c = cell_value(col_c, r)
        if a == "" and c == "":
            rows.append(r)
        r += 1
        if r > 200000:
            raise RuntimeError("Cannot find enough empty rows (sheet too large).")
    return rows

def batch_write_rows(ws, row_numbers: List[int], rows_values: List[List[str]], chunk_size: int = 30):
    """
    Ghi nhiều row rời rạc nhưng giảm request bằng batch_update theo từng chunk.
    Giữ logic 'không ghi đè' vì row_numbers là các hàng trống đã chọn.
    """
    if not row_numbers or not rows_values:
        return

    if len(row_numbers) != len(rows_values):
        raise ValueError("row_numbers và rows_values phải cùng độ dài")

    for i in range(0, len(row_numbers), chunk_size):
        rows_chunk = row_numbers[i:i + chunk_size]
        vals_chunk = rows_values[i:i + chunk_size]

        data = []
        for r, vals in zip(rows_chunk, vals_chunk):
            data.append({
                "range": f"A{r}:J{r}",
                "values": [vals],
            })

        # 1 request cho cả chunk
        ws.batch_update(data, value_input_option="USER_ENTERED")



# ===== Main import =====
def import_pool(
    data_file: str,
    stock_code: str,
    template: str,
    start_row: int = 2,
    only_hotmail: bool = False,
    dedupe_by_email: bool = True,
    dedupe_by_mailcode: bool = True,
):
    ws = connect_ws()

    with open(data_file, "r", encoding="utf-8") as f:
        raw = f.read()

    blocks = parse_blocks(raw)

    parsed = []
    for b in blocks:
        it = extract_item(b, only_hotmail=only_hotmail)
        if it:
            parsed.append(it)

    if not parsed:
        print("❌ Không parse được item nào (hoặc bị lọc hết).")
        return

    existing_emails, existing_mailcodes = build_existing_sets(ws)

    unique_items = []
    skipped = 0
    seen_emails = set()
    seen_mailcodes = set()

    for it in parsed:
        em = it["email"].lower().strip()
        mc = normalize_mail_code(it["mail_code"])

        if dedupe_by_email and (em in existing_emails or em in seen_emails):
            skipped += 1
            continue
        if dedupe_by_mailcode and (mc in existing_mailcodes or mc in seen_mailcodes):
            skipped += 1
            continue

        seen_emails.add(em)
        seen_mailcodes.add(mc)
        unique_items.append(it)

    if not unique_items:
        print("⚠️ Tất cả item đều bị trùng, không có gì để nạp.")
        return

    existing_ids = ws.col_values(1)[1:]
    new_ids = next_item_ids(existing_ids, len(unique_items))
    target_rows = find_next_empty_rows(ws, start_row=start_row, needed=len(unique_items))

    rows_values = []
    for i, it in enumerate(unique_items):
        secret = build_secret(template, it)
        rows_values.append([
            new_ids[i],
            stock_code,
            secret,
            "READY",
            "", "", "", "", "", ""
        ])

    batch_write_rows(ws, target_rows, rows_values, chunk_size=20)
    
    print(f"✅ Nạp {len(rows_values)} item vào POOL (stock_code={stock_code}) từ row >= {start_row}")
    print(f"⛔ Bỏ qua trùng: {skipped}")
    print(f"⏱ {datetime.now()}")

if __name__ == "__main__":
    stock_code = input("Nhập stock_code (vd ChatGptTeam_1m): ").strip()
    start_row = int(input("Nhập start row (vd 100): ").strip() or "2")

    only_hotmail_input = input("Chỉ lấy hotmail/outlook? (y/n): ").strip().lower()
    only_hotmail = (only_hotmail_input == "y")

    print("\nDán TEMPLATE lưu vào cột secret.")
    print("Biến dùng: {email}, {pw}, {mail_code}")
    print("Kết thúc bằng dòng: END\n")

    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    template = "\n".join(lines).strip()

    import_pool(
        data_file="data.txt",
        stock_code=stock_code,
        template=template,
        start_row=start_row,
        only_hotmail=only_hotmail,
        dedupe_by_email=True,
        dedupe_by_mailcode=True,
    )
