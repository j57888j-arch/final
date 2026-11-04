from cryptography.fernet import Fernet

from app.core.crypto import decrypt_resource, decrypt_sensitive_text, encrypt_resource, encrypt_sensitive_text
from app.services.reports_service import csv_bytes


def test_resource_is_encrypted_masked_and_roundtrips():
    key = Fernet.generate_key().decode()
    ciphertext, fingerprint, mask = encrypt_resource("+998 90 123 45 67", key)
    assert "+998 90" not in ciphertext
    assert mask.endswith("4567")
    assert len(fingerprint) == 64
    assert decrypt_resource(ciphertext, key) == "+998 90 123 45 67"


def test_csv_report_has_utf8_bom_and_formula_injection_guard():
    raw = csv_bytes([{
        "order_number": "=HYPERLINK(\"bad\")", "created_at": "2026-11-04T12:00:00",
        "user_telegram_id": 123, "username": "", "service": "Test", "quantity": 1,
        "total_minor": 1000, "currency": "UZS", "status": "completed",
        "payment_method": "wallet", "completed_at": "",
    }])
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"'=HYPERLINK" in raw


def test_sensitive_outbox_text_preserves_newlines():
    key = Fernet.generate_key().decode()
    source = "Buyurtma bajarildi\nResurs: +998901234567\nFaqat xizmat uchun"
    encrypted = encrypt_sensitive_text(source, key)
    assert source not in encrypted
    assert decrypt_sensitive_text(encrypted, key) == source
