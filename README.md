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
