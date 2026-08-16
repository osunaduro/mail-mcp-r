from mail_core.domain import Account, Folder, Message, Recipient


def test_recipient_to_dict():
    r = Recipient(email="a@example.com", name="Ana")
    assert r.to_dict() == {"email": "a@example.com", "name": "Ana"}


def test_message_to_dict_oculta_cuerpo_cuando_no_se_pide():
    m = Message(
        message_id="1",
        folder_id="INBOX",
        subject="Hola",
        body_text="cuerpo secreto",
        has_attachments=False,
    )
    summary = m.to_dict(include_body=False)
    assert "body_text" not in summary
    assert summary["subject"] == "Hola"


def test_message_to_dict_con_cuerpo():
    m = Message(message_id="1", folder_id="INBOX", body_text="hola")
    full = m.to_dict()
    assert full["body_text"] == "hola"


def test_account_no_expone_datos_sensibles():
    a = Account(alias="work", name="Trabajo", email_address="work@example.com")
    data = a.to_dict()
    assert data == {
        "alias": "work",
        "name": "Trabajo",
        "email_address": "work@example.com",
    }


def test_folder_to_dict():
    f = Folder(folder_id="INBOX", name="INBOX", delimiter="/")
    data = f.to_dict()
    assert data["folder_id"] == "INBOX"
    assert data["name"] == "INBOX"
