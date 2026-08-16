import asyncio

from mcp_server.stdio import mcp

EXPECTED_TOOLS = {
    "list_accounts",
    "get_account",
    "list_folders",
    "create_folder",
    "rename_folder",
    "delete_folder",
    "list_messages",
    "get_message",
    "search_messages",
    "move_message",
    "copy_message",
    "delete_message",
    "mark_read",
    "mark_flagged",
    "send_message",
    "reply_message",
    "forward_message",
    "forward_message_raw",
    "save_draft",
    "list_attachments",
    "download_attachment",
}


def test_herramientas_mcp_registradas():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names)


def test_no_hay_herramientas_prohibidas():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    prohibited = {"create_account", "delete_account", "update_config", "set_credentials"}
    assert not (names & prohibited)
