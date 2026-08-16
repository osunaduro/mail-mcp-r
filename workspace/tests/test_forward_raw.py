"""Unit tests for mail_core.providers.imap_smtp._apply_resent_headers.

Pure function, no IMAP/SMTP involved — verifies the header-manipulation
logic in isolation from the network code in forward_raw().
"""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from mail_core.providers.imap_smtp import _apply_resent_headers


def _original_message() -> bytes:
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "original-recipient@example.com"
    msg["Subject"] = "Original subject"
    msg["Message-ID"] = "<original@example.com>"
    msg.set_content("Plain text body")
    msg.add_alternative("<p>HTML body</p>", subtype="html")
    msg.add_attachment(b"PDF-BYTES", maintype="application", subtype="pdf", filename="doc.pdf")
    return msg.as_bytes()


def test_apply_resent_headers_adds_the_four_resent_fields():
    raw = _original_message()

    result = _apply_resent_headers(raw, "wp@mekaconstrucciones.com.ar", ["log@mekaconstrucciones.com.ar"])

    assert result["Resent-From"] == "wp@mekaconstrucciones.com.ar"
    assert result["Resent-To"] == "log@mekaconstrucciones.com.ar"
    assert result["Resent-Date"] is not None
    assert result["Resent-Message-ID"] is not None


def test_apply_resent_headers_joins_multiple_recipients():
    raw = _original_message()

    result = _apply_resent_headers(
        raw, "wp@mekaconstrucciones.com.ar", ["a@example.com", "b@example.com"]
    )

    assert result["Resent-To"] == "a@example.com, b@example.com"


def test_apply_resent_headers_leaves_original_content_untouched():
    raw = _original_message()

    result = _apply_resent_headers(raw, "wp@mekaconstrucciones.com.ar", ["log@example.com"])

    # Original headers survive unchanged.
    assert result["From"] == "sender@example.com"
    assert result["To"] == "original-recipient@example.com"
    assert result["Subject"] == "Original subject"
    assert result["Message-ID"] == "<original@example.com>"

    # Body parts (plain + HTML) and the attachment survive intact.
    assert result.get_body(preferencelist=("plain",)).get_content().strip() == "Plain text body"
    assert "HTML body" in result.get_body(preferencelist=("html",)).get_content()
    attachments = list(result.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "doc.pdf"
    assert attachments[0].get_content() == b"PDF-BYTES"


def test_apply_resent_headers_roundtrips_through_bytes_unchanged():
    """The message returned must still serialize to valid, parseable RFC822."""
    raw = _original_message()

    result = _apply_resent_headers(raw, "wp@mekaconstrucciones.com.ar", ["log@example.com"])
    reparsed = BytesParser(policy=policy.default).parsebytes(result.as_bytes())

    assert reparsed["Resent-From"] == "wp@mekaconstrucciones.com.ar"
    assert reparsed["Subject"] == "Original subject"
