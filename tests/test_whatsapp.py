import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["ENV_FILE"] = str(Path(_tmp) / ".env")

from call_analyzer import whatsapp  # noqa: E402

TEMPLATE = {"name": "price_list", "language": "fr", "status": "APPROVED", "category": "MARKETING",
            "components": [{"type": "BODY", "text": "Bonjour {{1}}"}]}
NOT_A_WABA = {"error": {"message": "(#100) Tried accessing nonexisting field (message_templates)", "code": 100}}


class FakeGraph:
    """The Graph API for a Business portfolio 111 owning WhatsApp accounts 222 (other number) and 333 (ours)."""

    def __init__(self, owned=("222", "333")):
        self.owned = owned
        self.paths = []

    def __call__(self, method, url, **kwargs):
        path = url.split("/v23.0/", 1)[1]
        self.paths.append(path)
        status, body = 400, NOT_A_WABA
        if path == "111/owned_whatsapp_business_accounts":
            status, body = 200, {"data": [{"id": w} for w in self.owned]}
        elif path == "111/client_whatsapp_business_accounts":
            status, body = 200, {"data": []}
        elif path == "debug_token":
            status, body = 200, {"data": {"granular_scopes": []}}
        elif path == "222/phone_numbers":
            status, body = 200, {"data": [{"id": "999"}]}
        elif path == "333/phone_numbers":
            status, body = 200, {"data": [{"id": "444"}]}
        elif path in ("222/message_templates", "333/message_templates"):
            status, body = 200, {"data": [TEMPLATE]}
        res = mock.Mock(ok=status < 400, status_code=status)
        res.json.return_value = body
        return res


class TemplatesTest(unittest.TestCase):
    def setUp(self):
        whatsapp._templates_cache = None
        whatsapp._resolved_waba.clear()
        env = {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "444", "WHATSAPP_BUSINESS_ACCOUNT_ID": "111",
               "WHATSAPP_API_VERSION": "v23.0"}
        patcher = mock.patch.object(whatsapp, "_setting", lambda key, default="": env.get(key, default))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_business_portfolio_id_finds_the_account_with_the_number(self):
        graph = FakeGraph()
        with mock.patch.object(whatsapp.requests, "request", graph), self.assertLogs(whatsapp.log, "WARNING"):
            found = whatsapp.templates()
        self.assertEqual([t["name"] for t in found], ["price_list"])
        self.assertEqual(graph.paths[-1], "333/message_templates")
        whatsapp._templates_cache = None
        graph.paths.clear()
        with mock.patch.object(whatsapp.requests, "request", graph):
            whatsapp.templates()
        self.assertEqual(graph.paths, ["333/message_templates"])

    def test_explains_the_wrong_id_when_no_account_is_found(self):
        with mock.patch.object(whatsapp.requests, "request", FakeGraph(owned=())):
            with self.assertRaises(whatsapp.WhatsAppError) as ctx:
                whatsapp.templates()
        self.assertIn("isn't a WhatsApp Business Account ID", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
