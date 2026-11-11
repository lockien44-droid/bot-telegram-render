"""Generate NAPAS account-transfer QR images without a network request."""

import binascii
import io
import re

import qrcode
from qrcode.image.pure import PyPNGImage


BANK_BINS = {"BIDV": "970418", "MB": "970422", "MBBANK": "970422"}


def _tlv(tag: str, value: str) -> str:
    if not value.isascii() or len(value) > 99:
        raise ValueError(f"Invalid VietQR field {tag}")
    return f"{tag}{len(value):02d}{value}"


def build_payload(bank: str, account: str, amount: int, note: str) -> str:
    bank = bank.strip().upper()
    bank_bin = BANK_BINS.get(bank, bank)
    if not re.fullmatch(r"[0-9]{6}", bank_bin):
        raise ValueError("Local VietQR needs a supported BANK_CODE or six-digit BANK_BIN")
    account = account.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{1,19}", account):
        raise ValueError("Invalid VietQR account number")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount < 10**13:
        raise ValueError("Invalid VietQR amount")
    if not re.fullmatch(r"[A-Za-z0-9 ]{1,25}", note):
        raise ValueError("VietQR transfer note must contain 1-25 ASCII letters/digits/spaces")
    recipient = _tlv("00", bank_bin) + _tlv("01", account)
    merchant = _tlv("00", "A000000727") + _tlv("01", recipient) + _tlv("02", "QRIBFTTA")
    payload = (
        _tlv("00", "01") + _tlv("01", "12") + _tlv("38", merchant)
        + _tlv("53", "704") + _tlv("54", str(amount)) + _tlv("58", "VN")
        + _tlv("62", _tlv("08", note)) + "6304"
    )
    return payload + f"{binascii.crc_hqx(payload.encode('ascii'), 0xFFFF):04X}"


def generate_png(bank: str, account: str, amount: int, note: str) -> bytes:
    payload = build_payload(bank, account, amount, note)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    output = io.BytesIO()
    qr.make_image(image_factory=PyPNGImage).save(output)
    return output.getvalue()
