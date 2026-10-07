"""Leads to call: opportunities at the NEW stage from Twenty, with their contact's number and our calls to it.

    python -m unittest discover tests -v
"""
import os
import tempfile
import unittest
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")

from call_analyzer import crm, db  # noqa: E402
from call_analyzer.web.server import get_crm_leads  # noqa: E402


def opportunity(i: int, phone: str | None) -> dict:
    contact = None if phone is None else {
        "id": f"p{i}", "name": {"firstName": f"Lead {i}", "lastName": ""},
        "phones": {"primaryPhoneNumber": phone, "primaryPhoneCallingCode": "+216", "additionalPhones": []},
        "emails": {"primaryEmail": ""}, "city": "Sfax"}
    return {"id": f"o{i}", "name": f"Lead {i} Facebook Lead", "stage": "NEW", "createdAt": f"2026-10-0{i}T10:00:00Z",
            "amount": {"amountMicros": None, "currencyCode": "TND"}, "pointOfContact": contact,
            "owner": {"name": {"firstName": "Cyrine", "lastName": "Soui"}}}


class LeadsTests(unittest.TestCase):
    def setUp(self):
        crm._leads_cache.clear()
        self.requests = []
        pages = [
            ([opportunity(1, "22602716"), opportunity(2, None)], {"hasNextPage": True, "endCursor": "c1"}),
            ([opportunity(3, "98123456")], {"hasNextPage": False, "endCursor": "c2"}),
        ]

        def fake_page(path, params):
            self.requests.append((path, dict(params)))
            return pages[len(self.requests) - 1]

        self._get_page, self._config = crm._get_page, crm._config
        crm._get_page = fake_page
        crm._config = lambda: ("https://crm.example.com", "test-key", True)
        conn = db.connect()
        conn.execute("DELETE FROM calls")
        for call_id, customer, date in (("10", "+21622602716", "2026-10-02 09:00:00"),
                                        ("11", "22602716", "2026-10-05 11:00:00"), ("12", "105", "2026-10-05")):
            conn.execute("INSERT INTO calls (id, customer, date_call) VALUES (?, ?, ?)", (call_id, customer, date))
        conn.commit()

    def tearDown(self):
        crm._get_page, crm._config = self._get_page, self._config

    def test_all_pages_of_new_opportunities_with_their_contacts_and_our_calls(self):
        result = get_crm_leads()
        self.assertEqual([lead["id"] for lead in result["leads"]], ["o1", "o2", "o3"])
        self.assertFalse(result["truncated"])
        first_page, second_page = (params for _, params in self.requests)
        self.assertEqual(first_page["filter"], "stage[eq]:NEW")
        self.assertNotIn("starting_after", first_page)
        self.assertEqual(second_page["starting_after"], "c1")

        lead1, lead2, lead3 = result["leads"]
        self.assertEqual((lead1["contact"]["name"], lead1["contact"]["phones"]), ("Lead 1", ["+216 22602716"]))
        self.assertEqual(lead1["owner"], "Cyrine Soui")
        self.assertEqual(lead1["url"], "https://crm.example.com/object/opportunity/o1")
        # Both ways the number was written in our calls count; the latest call is linked.
        self.assertEqual(lead1["calls"], {"count": 2, "match": "22602716", "last_id": "11",
                                          "last_date": "2026-10-05 11:00:00"})
        self.assertIsNone(lead2["contact"])
        self.assertEqual(lead2["calls"]["count"], 0)
        self.assertEqual(lead3["calls"], {"count": 0, "match": "98123456", "last_id": None, "last_date": None})

    def test_the_crm_is_asked_again_only_on_refresh(self):
        get_crm_leads()
        get_crm_leads()
        self.assertEqual(len(self.requests), 2)  # two pages, once
        crm._get_page = lambda path, params: ([opportunity(4, "55111222")], {"hasNextPage": False})
        self.assertEqual([lead["id"] for lead in get_crm_leads(refresh=True)["leads"]], ["o4"])

    def test_without_an_api_key_nothing_is_asked(self):
        crm._get_page = lambda *a: self.fail("the CRM must not be queried")
        crm._config = lambda: ("https://crm.example.com", "", True)
        self.assertEqual(get_crm_leads(), {"configured": False, "stage": "NEW", "leads": [], "truncated": False})


if __name__ == "__main__":
    unittest.main()
