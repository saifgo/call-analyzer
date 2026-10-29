"""The built-in CRM (adapters/crm/internal.py), on its own and behind the call desk.

    python -m unittest tests.test_internal_crm -v
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

from call_analyzer import auth, campaigns, crm, db, operations  # noqa: E402
from call_analyzer.adapters.crm.internal import InternalCrm  # noqa: E402

CRM_TABLES = ("crm_people", "crm_phones", "crm_opportunities", "crm_notes", "crm_stages", "crm_fields")


class InternalCrmCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        for table in CRM_TABLES:
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        self.crm = InternalCrm()
        crm.use(self.crm)
        self.addCleanup(crm.use, None)

    def contact(self, name="Ali", phone="22 602 716", stage="NEW", created=None) -> tuple[str, str]:
        person = self.crm.create_person(name, phone, "Tunis", "")["id"]
        opp = self.crm.create_opportunity(f"{name} lead", person, stage, None)["id"]
        if created:
            self.conn.execute("UPDATE crm_opportunities SET created_at = ? WHERE id = ?", (created, opp))
            self.conn.commit()
        return person, opp


class AdapterTests(InternalCrmCase):
    def test_a_new_database_gets_the_stages_and_the_fields_the_default_campaigns_write(self):
        stages = self.crm.stages()
        self.assertEqual(stages[0], {"value": "NEW", "label": "New", "locked": True})
        self.assertIn({"value": "ATTEMPTED", "label": "Attempted", "locked": True}, stages)
        self.assertEqual({f["key"]: f["type"] for f in self.crm.fields()}, {"havepos": "boolean"})

    def test_a_contact_is_found_by_its_number_however_it_is_written(self):
        person, opp = self.contact(phone="+216 22-602-716")
        for number in ("22602716", "0021622602716", "+21622602716"):
            people = crm.lookup(number)["people"]
            self.assertEqual([p["id"] for p in people], [person], number)
        self.assertEqual(people[0]["phones"], ["+216 22602716"])
        self.assertEqual([o["id"] for o in people[0]["opportunities"]], [opp])
        self.assertEqual(crm.lookup("99999999")["people"], [])

    def test_leads_are_listed_by_stage_a_batch_at_a_time(self):
        made = [self.contact(f"C{i}", f"2000000{i}", created=f"2026-10-0{i}T10:00:00.000Z")[1] for i in range(1, 6)]
        self.contact("Other", "21000000", stage="ATTEMPTED")
        seen, cursor = [], None
        while True:
            batch, cursor = self.crm.list_opportunities("NEW", True, 2, cursor)
            seen += [lead["id"] for lead in batch]
            if not cursor:
                break
        self.assertEqual(seen, made)
        newest, cursor = self.crm.list_opportunities("NEW", False, None)
        self.assertEqual([lead["id"] for lead in newest], made[::-1])
        self.assertIsNone(cursor)
        self.assertEqual(newest[0]["contact"]["phones"], ["+216 20000005"])

    def test_the_stage_must_be_in_the_pipeline(self):
        _, opp = self.contact()
        self.crm.update_opportunity(opp, {"stage": "IN_TALK"})
        self.assertEqual(crm.opportunity(opp)["stage"], "IN_TALK")
        with self.assertRaises(crm.CrmError):
            self.crm.update_opportunity(opp, {"stage": "NOPE"})

    def test_custom_fields_are_checked_against_their_type(self):
        person, _ = self.contact()
        self.crm.update_person(person, {"city": "Sfax", "havepos": "true"})
        found = crm.lookup("22602716")["people"][0]
        self.assertEqual((found["city"], found["fields"]), ("Sfax", {"havepos": True}))
        with self.assertRaises(crm.CrmError):
            self.crm.update_person(person, {"havepos": "maybe"})
        with self.assertRaises(crm.CrmError):
            self.crm.update_person(person, {"shoe_size": 42})

    def test_notes_are_read_newest_first(self):
        person, opp = self.contact()
        first = crm.add_note("Call · No answer", "**Outcome:** no answer", opp, person)
        second = crm.add_note("Contact note", "Prefers mornings", None, person)
        self.assertEqual([n["id"] for n in crm.notes(opp, person)], [second, first])
        self.assertEqual([n["id"] for n in crm.notes(opp, None)], [first])

    def test_the_app_accounts_are_the_crm_users(self):
        auth.create_user("crm_owner", "a-long-password", role="agent", display_name="Sami")
        self.addCleanup(lambda: (self.conn.execute("DELETE FROM users WHERE username = 'crm_owner'"),
                                 self.conn.commit()))
        self.assertIn({"id": "crm_owner", "name": "Sami", "email": None}, crm.workspace_members())
        self.assertEqual(crm.member_id("crm_owner"), "crm_owner")
        person, _ = self.contact()
        opp = crm.create_opportunity("Desk lead", person, owner_id="crm_owner")["id"]
        self.assertEqual(crm.opportunity(opp)["owner"], "Sami")


class ProviderTests(unittest.TestCase):
    def test_the_built_in_crm_is_the_default_unless_twenty_was_set_up(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CRM_API_KEY", None)
            self.assertEqual(crm.registry.active_name(), "internal")
            os.environ["CRM_API_KEY"] = "key"
            self.assertEqual(crm.registry.active_name(), "twenty")
            os.environ["CRM_PROVIDER"] = "internal"
            self.assertEqual(crm.registry.active_name(), "internal")


class DeskTests(InternalCrmCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(operations, "SYNC_IN_BACKGROUND", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for table in ("op_calls", "op_agents", "op_campaigns", "op_presence", "calls", "softphones", "user_agents",
                      "wa_messages", "op_targets", "op_pause_reasons", "op_pauses", "op_settings", "op_inbound",
                      "op_shifts"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        operations.set_ready(self.conn, "a1", True)

    def test_the_desk_calls_the_built_in_crm_leads_and_writes_the_results_back(self):
        person, opp = self.contact()
        op, reason = operations.claim_next("a1")
        self.assertIsNotNone(op, reason)
        self.assertEqual(op["opportunity_id"], opp)
        operations.start_call(op["id"], "a1")
        operations.finish(op["id"], "a1", answers={"has_pos": "true", "city": "Sousse"}, outcome="not_interested",
                          note="Has a supplier", stage="REJECTED")
        self.assertEqual(crm.opportunity(opp)["stage"], "REJECTED")
        found = crm.lookup("22602716")["people"][0]
        self.assertEqual((found["city"], found["fields"]), ("Sousse", {"havepos": True}))
        self.assertEqual(len(crm.notes(opp, person)), 1)
        self.assertEqual(operations.claim_next("a1"), (None, None))


if __name__ == "__main__":
    unittest.main()
