import binascii
import io
import unittest

import png

from vietqr_local import build_payload, generate_png


def fields(payload):
    result = {}
    while payload:
        tag, size = payload[:2], int(payload[2:4])
        value, payload = payload[4:4 + size], payload[4 + size:]
        if len(value) != size:
            raise AssertionError("Truncated QR field")
        result[tag] = value
    return result


class LocalQRTests(unittest.TestCase):
    def test_payment_fields_and_checksum(self):
        payload = build_payload("BIDV", "TEST12345", 2000, "ORDTEST123")
        data = fields(payload)
        merchant = fields(data["38"])
        self.assertEqual(fields(merchant["01"]), {"00": "970418", "01": "TEST12345"})
        self.assertEqual(merchant["00"], "A000000727")
        self.assertEqual(merchant["02"], "QRIBFTTA")
        self.assertEqual(data["54"], "2000")
        self.assertEqual(data["53"], "704")
        self.assertEqual(data["58"], "VN")
        self.assertEqual(fields(data["62"])["08"], "ORDTEST123")
        self.assertEqual(data["63"], f"{binascii.crc_hqx(payload[:-4].encode(), 0xFFFF):04X}")
        self.assertEqual(binascii.crc_hqx(b"123456789", 0xFFFF), 0x29B1)

    def test_numeric_bin_and_alphanumeric_account(self):
        self.assertEqual(
            build_payload("970418", "TEST12345", 2000, "ORDTEST123"),
            build_payload("BIDV", "TEST12345", 2000, "ORDTEST123"),
        )

    def test_invalid_input(self):
        for bank, account, amount, note in (
            ("UNKNOWN", "123", 2000, "ORDTEST"),
            ("BIDV", "", 2000, "ORDTEST"),
            ("BIDV", "123", 0, "ORDTEST"),
            ("BIDV", "123", 2000, "X" * 26),
        ):
            with self.subTest(bank=bank, amount=amount, note=note):
                with self.assertRaises(ValueError):
                    build_payload(bank, account, amount, note)

    def test_png_is_readable(self):
        data = generate_png("BIDV", "TEST12345", 2000, "ORDTEST123")
        width, height, rows, _ = png.Reader(file=io.BytesIO(data)).read()
        self.assertEqual(width, height)
        self.assertGreater(width, 200)
        self.assertEqual(len(list(rows)), height)


if __name__ == "__main__":
    unittest.main()
