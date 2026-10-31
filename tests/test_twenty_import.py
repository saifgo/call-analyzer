"""Importing Twenty's records into the built-in CRM (twenty_import.py).

    python -m unittest tests.test_twenty_import -v
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ.setdefault("DATA_DIR", str(Path(TMP.name) / "data"))
os.environ.setdefault("ENV_FILE", str(Path(TMP.name) / ".env"))
for key in ("CRM_API_KEY", "CRM_PROVIDER", "CRM_BASE_URL"):
    os.environ.pop(key, None)

import pgtest  # noqa: E402,F401  (before call_analyzer: the test database)
from call_analyzer import auth, crm, db, twenty_import  # noqa: E402
from call_analyzer.adapters.crm import twenty as twenty_module  # noqa: E402
from call_analyzer.adapters.crm.internal import InternalCrm  # noqa: E402
from call_analyzer.adapters.crm.twenty import TwentyCrm  # noqa: E402

CRM_TABLES = ("crm_people", "crm_phones", "crm_opportunities", "crm_notes", "crm_stages", "crm_fields")
MEMBER = "11111111-0000-0000-0000-000000000001"


def person(i: int, phone: str, updated="2026-10-01T10:00:00.000Z", **extra) -> dict:
    return {"id": f"00000000-0000-0000-0000-00000000000{i}", "name": {"firstName": f"Person {i}", "lastName": "Ben"},
            "phones": {"primaryPhoneNumber": phone, "primaryPhoneCallingCode": "+216",
                       "additionalPhones": [{"number": "98111222", "callingCode": "+216"}] if i == 1 else []},
            "emails": {"primaryEmail": f"p{i}@example.com"}, "jobTitle": "Owner", "city": "Sfax",
            "company": {"name": "Kiosk SARL"}, "createdAt": "2026-09-01T08:00:00Z", "updatedAt": updated, **extra}


def opportunity(i: int, person_id: str | None, stage="NEW", updated="2026-10-01T10:00:00.000Z") -> dict:
    return {"id": f"0000000a-0000-0000-0000-00000000000{i}", "name": f"Lead {i}", "stage": stage,
            "amount": {"amountMicros": 1500000000, "currencyCode": "TND"}, "closeDate": "2026-12-01T00:00:00.000Z",
            "pointOfContactId": person_id, "ownerId": MEMBER, "createdAt": "2026-09-02T08:00:00Z",
            "updatedAt": updated}


def note(i: int, **target) -> dict:
    return {"id": f"t{i}", **target, "note": {
        "id": f"0000000b-0000-0000-0000-00000000000{i}", "title": f"Note {i}", "createdAt": "2026-09-03T08:00:00Z",
        "bodyV2": {"markdown": f"**Outcome:** {i}"}, "createdBy": {"workspaceMemberId": MEMBER, "name": "Sami T"}}}


METADATA = [
    {"nameSingular": "opportunity", "fields": [{"name": "stage", "options": [
        {"value": "NEW", "label": "New", "position": 0}, {"value": "DEMO", "label": "Demo booked", "position": 1}]}]},
    {"nameSingular": "person", "fields": [
        {"name": "city", "isCustom": False, "type": "TEXT"},
        {"name": "havepos", "isCustom": True, "type": "BOOLEAN", "label": "Has a POS"},
        {"name": "shopType", "isCustom": True, "type": "SELECT", "label": "Shop type",
         "options": [{"value": "KIOSK", "label": "Kiosk", "position": 0}, {"value": "CAFE", "label": "Café",
                                                                            "position": 1}]},
        {"name": "visits", "isCustom": True, "type": "NUMBER", "label": "Visits"},
        {"name": "oldField", "isCustom": True, "type": "TEXT", "isActive": False}]},
]


class FakeTwenty(TwentyCrm):
    """The real adapter, with Twenty's REST API answered from `data`, in pages of `twenty_import.LEADS_PAGE`."""

    def __init__(self, data: dict):
        self.data, self.requests = data, []

    def _config(self):
        return "https://crm.example.com", "test-key", True

    def _get_json(self, path, params):
        return {"data": METADATA}

    def _get_page(self, path, params):
        self.requests.append(path)
        records, start = self.data.get(path, []), int(params.get("starting_after") or 0)
        end = start + params["limit"]
        return records[start:end], {"hasNextPage": end < len(records), "endCursor": str(end)}


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        for table in (*CRM_TABLES, "op_calls"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM users WHERE username = 'sami'")
        self.conn.commit()
        auth.create_user("sami", "a-long-password", role="agent", display_name="Sami")
        self.conn.execute("UPDATE users SET crm_member_id = ? WHERE username = 'sami'", (MEMBER,))
        self.conn.commit()
        self.addCleanup(lambda: (self.conn.execute("DELETE FROM users WHERE username = 'sami'"), self.conn.commit()))
        self.crm = InternalCrm()
        crm.use(self.crm)
        self.addCleanup(crm.use, None)
        patcher = mock.patch.object(twenty_import, "LEADS_PAGE", 2)  # several pages from a few records
        patcher.start()
        self.addCleanup(patcher.stop)

        p1, p2, p3 = (person(1, "22602716", havepos=True, shopType="KIOSK", visits=3), person(2, "55111222"),
                      person(3, "20000000", deletedAt="2026-10-02T00:00:00Z"))
        self.data = {
            "people": [p1, p2, p3],
            "opportunities": [opportunity(1, p1["id"]), opportunity(2, p2["id"], stage="LOST"),
                              opportunity(3, None)],
            "noteTargets": [note(1, targetPersonId=p1["id"]), note(2, targetCompanyId="c1"),
                            note(3, targetOpportunityId=opportunity(2, None)["id"]),
                            {**note(1, targetOpportunityId=opportunity(1, None)["id"]), "id": "t9"}],
        }
        self.p1, self.o1 = p1["id"], opportunity(1, None)["id"]

    def run_import(self) -> dict:
        result = twenty_import.start(FakeTwenty(self.data), background=False)
        self.assertIsNone(result["error"])
        self.assertFalse(result["running"])
        return result["counts"]

    def test_contacts_opportunities_and_notes_come_over_with_their_ids(self):
        counts = self.run_import()
        self.assertEqual({k: counts.get(k) for k in ("people_added", "opportunities_added", "notes_added",
                                                      "notes_skipped", "fields", "stages")},
                         {"people_added": 2, "opportunities_added": 3, "notes_added": 2, "notes_skipped": 1,
                          "fields": 2, "stages": 2})  # havepos was there already; LOST is seen on an opportunity

        found = crm.lookup("22602716")["people"]
        self.assertEqual([p["id"] for p in found], [self.p1])
        contact = self.crm.get_person(self.p1)
        self.assertEqual((contact["name"], contact["email"], contact["company"], contact["source"], contact["phones"]),
                         ("Person 1 Ben", "p1@example.com", "Kiosk SARL", "twenty", ["+216 22602716", "+216 98111222"]))
        self.assertEqual(contact["fields"], {"havepos": True, "shopType": "KIOSK", "visits": 3})
        self.assertEqual(contact["created_at"], "2026-09-01T08:00:00.000Z")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM crm_people WHERE id LIKE '%3'").fetchone())

        lead = crm.opportunity(self.o1)
        self.assertEqual((lead["stage"], lead["amount"], lead["currency"], lead["close_date"], lead["owner"]),
                         ("NEW", 1500, "TND", "2026-12-01", "Sami"))
        self.assertIn({"value": "DEMO", "label": "Demo booked", "locked": False}, self.crm.stages())
        self.assertIn("LOST", [s["value"] for s in self.crm.stages()])
        self.assertIsNone(crm.opportunity(opportunity(3, None)["id"])["contact"])

        notes = contact["notes"]  # note 1 is about both the contact and their opportunity
        self.assertEqual([(n["title"], n["text"], n["author"], n["opportunity_id"]) for n in notes],
                         [("Note 1", "**Outcome:** 1", "Sami", self.o1)])

    def test_running_it_again_keeps_what_was_edited_here_and_takes_what_changed_in_twenty(self):
        self.run_import()
        self.crm.update_person(self.p1, {"city": "Sousse", "havepos": False})
        counts = self.run_import()
        self.assertEqual((counts.get("people_added"), counts.get("people_unchanged"), counts.get("notes_unchanged")),
                         (None, 2, 2))
        self.assertEqual(self.crm.get_person(self.p1)["city"], "Sousse")

        self.data["people"][0] = person(1, "22602716", updated="2099-01-01T00:00:00Z", city="Monastir",
                                        shopType="CAFE")
        self.data["opportunities"][0] = opportunity(1, self.p1, stage="DEMO", updated="2099-01-01T00:00:00Z")
        counts = self.run_import()
        self.assertEqual((counts.get("people_updated"), counts.get("opportunities_updated")), (1, 1))
        contact = self.crm.get_person(self.p1)
        self.assertEqual(contact["city"], "Monastir")
        self.assertEqual(contact["fields"], {"havepos": False, "shopType": "CAFE", "visits": 3})  # not sent: kept
        self.assertEqual(crm.opportunity(self.o1)["stage"], "DEMO")

    def test_the_desk_calls_stay_linked(self):
        self.conn.execute("INSERT INTO op_calls (opportunity_id, person_id, source, status, created_at) "
                          "VALUES (?, ?, 'queue', 'done', '2026-10-01T10:00:00')", (self.o1, self.p1))
        self.conn.commit()
        self.run_import()
        row = self.conn.execute("SELECT opportunity_id FROM op_calls").fetchone()
        self.assertEqual(crm.opportunity(row[0])["contact"]["id"], self.p1)

    def test_it_needs_twenty_and_runs_once_at_a_time(self):
        class Unset(FakeTwenty):
            def is_configured(self):
                return False
        with self.assertRaises(crm.CrmError):
            twenty_import.start(Unset(self.data), background=False)
        with mock.patch.dict(twenty_import._state, {"running": True}):
            with self.assertRaises(crm.CrmError):
                twenty_import.start(FakeTwenty(self.data), background=False)

    def test_a_failure_is_reported_and_what_was_imported_stays(self):
        twenty = FakeTwenty(self.data)
        real = twenty._get_page

        def failing(path, params):
            if path == "opportunities":
                raise crm.CrmError("The CRM answered 500 for opportunities.")
            return real(path, params)
        twenty._get_page = failing
        result = twenty_import.start(twenty, background=False)
        self.assertEqual(result["error"], "The CRM answered 500 for opportunities.")
        self.assertEqual(self.crm.search_people()["total"], 2)


class RateLimitTests(unittest.TestCase):
    def test_a_long_read_waits_when_twenty_limits_requests_and_the_desk_doesnt(self):
        limited = mock.Mock(status_code=429, ok=False, headers={"Retry-After": "2"})
        fine = mock.Mock(status_code=200, ok=True, headers={})
        fine.json.return_value = {"data": {"people": []}}
        twenty = TwentyCrm()
        twenty._config = lambda: ("https://crm.example.com", "test-key", True)
        session = mock.Mock()
        with mock.patch.object(twenty_module, "_http", return_value=session), \
                mock.patch.object(twenty_module.time, "sleep") as sleep:
            session.get.side_effect = [limited, fine]
            with self.assertRaises(crm.CrmError):
                twenty._get_json("people", {})
            twenty.wait_when_limited = True
            session.get.side_effect = [limited, fine]
            self.assertEqual(twenty._get_json("people", {}), {"data": {"people": []}})
            sleep.assert_called_once_with(2.0)


if __name__ == "__main__":
    unittest.main()
