# Telegram Shop Bot

Bot ban hang Telegram dung Google Sheets de quan ly san pham, ton kho, don hang va SePay webhook de xu ly thanh toan.

## File chinh

- `main.py`: entrypoint tren Render, chay FastAPI webhook va Telegram bot.
- `bot_shop.py`: logic bot Telegram.
- `sepay_webhook.py`: endpoint xu ly webhook SePay va giao hang.
- `mail_reader.py`: doc mail Microsoft Graph khi dung lenh mail.
- `import_pool.py`: tien ich import stock vao Google Sheets.
- `backup_manager.py`: tien ich backup Google Sheets.

## Bien moi truong

Copy `.env.example` thanh `.env` khi chay local. Tren Render, them cac bien nay trong tab Environment:

```env
BOT_TOKEN=
GSHEET_ID=
GOOGLE_JSON_CONTENT=
SEPAY_API_KEY=
BANK_CODE=MB
BANK_NAME=MBBANK
BANK_OWNER=LE VAN KHOI
BANK_NUMBER=0329279225
NOTE_TEMPLATE={order_id}
```

`GOOGLE_JSON_CONTENT` la toan bo noi dung file Google service account JSON. Khong commit `.env` hoac `service_account.json`.

QR thanh toan duoc tao truc tiep trong bot cho BIDV va MB/MBBANK, khong can tai anh tu VietQR.
Voi ngan hang khac, dat `BANK_BIN` la ma BIN NAPAS 6 chu so de tao QR local;
neu khong co BIN, bot se thu dich vu anh VietQR nhu truoc.

## Chay local

```bash
pip install -r requirements.txt
python main.py
```

## Deploy Render

- Service type: Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`

Sau deploy, log dung se co:

```text
Nạp GSheet Creds từ Environment Variable
Sheets OK
Bot running
Uvicorn running on http://0.0.0.0:10000
```

## Bao mat

Neu token bot hoac Google service account key da lo, tao token/key moi va cap nhat lai Render Environment.

## Thanh toan, giao hang va phuc hoi

- Webhook SePay chi tra thanh cong sau khi ghi su kien vao tab `BOT_EVENTS`.
  Worker doc lai su kien chua xong sau restart va thu lai voi thoi gian cho tang dan.
- Don di qua `PAID` -> `DELIVERY_PENDING` -> `DELIVERED`. Chi danh dau da giao sau khi Telegram gui file thanh cong.
  Hang da cap duoc giu nguyen khi thu lai; khong lay them hang moi de gui lai.
- Phai du so luong va secret hop le truoc khi danh dau hang SOLD. Sai tien, thieu hang,
  giao dich khong ro don se vao dashboard **Thanh toan can xu ly** va bao admin neu da dat `ADMIN_IDS`.
- Co khoa chung giua bot, webhook va API trong mot tien trinh. Khi con dung Sheets,
  chay **mot instance, mot worker Uvicorn**. Khong tang replicas de mo rong tai.
  Chuyen don/kho/su kien sang PostgreSQL voi transaction va unique constraint truoc khi chay nhieu instance.
- Moi user mac dinh co toi da 2 don PENDING (`MAX_PENDING_PER_USER`), moi don toi da 20 item.
  Cung callback/update tao don se dung lai ma don da luu; hang giu mo coi het han se duoc quet tra kho.
- Telegram khong xoa update dang cho khi restart. Chi luu ID update da xu ly, khong luu noi dung mail/2FA vao ledger.

Gioi han: Telegram khong cung cap idempotency key cho `send_document`. Neu gui thanh cong
nhung mat ket noi truoc khi ghi trang thai, lan thu lai co the gui lai **cung file/cung hang**.
Van can doi soat giao dich va theo doi muc can xu ly; khong cam ket exactly-once qua mang.
Khong sua/xoa/sap xep dong trong `BOT_EVENTS` khi worker dang chay. Ledger va Sheets can duoc theo doi kich thuoc;
chuyen database khi luong giao dich tang, khong coi khoa trong RAM la khoa phan tan.

## Dang nhap dashboard

Mat khau chi gui khi POST `/admin/api/login`. Backend tao cookie HttpOnly, SameSite=Strict,
Secure tren Render, het han sau 8 gio. Khong luu mat khau vao sessionStorage va khong nhan `?key=`.
Sau 6 lan sai trong 10 phut, IP bi gioi han thu lai. Doi `ADMIN_PASSWORD` se vo hieu hoa cac phien cu.
Webhook Telegram luon co secret; neu khong dat `TELEGRAM_WEBHOOK_SECRET`, backend tu dan xuat secret tu BOT_TOKEN.

## Backup Drive

Backup hang ngay sau 03:00 theo `APP_TIMEZONE`, chay bu neu dich vu khoi dong muon.
Thu muc mac dinh la ID trong `BACKUP_DRIVE_FOLDER_ID`; dat rong de tat backup tu dong len Drive.
File `backup_slots.json` chua 14 file ZIP do chu tai khoan Drive so huu trong thu muc da chon.
Service account cap nhat luan phien mot file moi ngay, tai lai va so checksum SHA-256.
Cach nay khong can service account so huu file moi tren My Drive. Khong doi quyen chia se tu dong.
Phai giu quyen Editor cua service account tren cac file nay. Thu muc Shared Drive khac
co the duoc cau hinh bang `BACKUP_DRIVE_FOLDER_ID` (se tao ban ZIP moi neu khong co slot tuong ung).

Backup thieu tab hoac upload/kiem tra loi se bi bao that bai va thu lai, khong bao thanh cong gia.
Ban local giu theo `BACKUP_KEEP_DAYS` (mac dinh 14). 14 slot Drive giu toi da 14 ngay co backup;
slot hom nay duoc ghi de sau 14 ngay. Backup chua thong tin kho, can gioi han nguoi truy cap thu muc.
Khoi phuc chi khi da kiem tra ban backup va co yeu cau ro rang; khong tu dong ghi de Sheets nguon.

## Kiem thu

`python -m unittest test_reliability test_vietqr_local -v` chay kiem thu offline.
`npm ci --prefix fe` va `npm run build --prefix fe` build dashboard.
`/health` tra `release: dashboard-v2` va kiem tra worker; `/ping` la kiem tra song don gian.


## Dashboard v2

Tong quan uu tien doanh thu, don cho thanh toan, cho giao va cac truong hop can xu ly.
Trang Don hang tim toan bo lich su tren Sheets, phan trang 20 don, loc ngay/san pham/trang thai.
Bang desktop gom cac cot chinh; tren dien thoai dung the don hang. Chi tai noi dung giao hang khi bam Xem thong tin.
Doi soat thanh toan yeu cau ma giao dich ngan hang; thao tac huy/thu giao lai chi hien theo trang thai hop le.
Nhap mat khau sai, bi gioi han dang nhap, mat ket noi va loi may chu co thong bao rieng.
