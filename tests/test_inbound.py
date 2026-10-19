"""Incoming calls (inbound.py): the desk call opened when an agent picks up, the missed calls list and who calls them
back, ring groups, linking a caller to the CRM, and the figures. The CRM is a fake.

    python -m unittest discover tests -v
"""
import unittest
from datetime import datetime, timedelta

from test_operations import DeskTestCase, FakeCrm, iso, lead  # noqa: F401  (sets up the scratch data folder first)

from call_analyzer import alerts, campaigns, crm, inbound, operations
from call_analyzer.campaigns import CampaignError
from call_analyzer.operations import OperationError

KNOWN = "+216 22602718"  # Lead 8: in the CRM, not in the queue
QUEUED = "22602711"  # Lead 1: first in the queue
UNKNOWN = "98765432"


class PeopleCrm(FakeCrm):
    """The fake CRM, which also finds contacts by number and adds new ones."""

    def __init__(self, leads):
        super().__init__(leads)
        self.created = []

    def _all(self):
        return [x for items in self.by_stage.values() for x in items]

    def find_people(self, key):
        people = {}
        for item in self._all():
            contact = item.get("contact")
            if contact and any(crm.match_key(p) == key for p in contact["phones"]):
                person = people.setdefault(contact["id"], {**contact, "opportunities": []})
                person["opportunities"].append({k: v for k, v in item.items() if k != "contact"})
        return list(people.values())

    def create_person(self, name, phone, city, email):
        self.created.append(("person", name, phone))
        return {"id": f"new-p{len(self.created)}"}

    def create_opportunity(self, name, person_id, stage, owner_id):
        self.created.append(("opportunity", name, person_id))
        oid = f"new-o{len(self.created)}"
        contact = {"id": person_id, "name": name.removesuffix(" Call Desk Lead"), "email": None,
                   "phones": [UNKNOWN], "job_title": None, "city": None, "company": None, "created_at": None,
                   "last_contact_at": None, "url": None}
        self.by_stage.setdefault(stage, []).append(
            {"id": oid, "name": name, "stage": stage, "amount": None, "currency": None, "close_date": None,
             "company": None, "owner": None, "created_at": "2026-10-09T10:00:00Z", "updated_at": None, "url": None,
             "contact": contact})
        return {"id": oid}


class InboundTestCase(DeskTestCase):
    def setUp(self):
        super().setUp()
        self.conn.execute("DELETE FROM op_inbound")
        self.conn.commit()
        self.crm = PeopleCrm([lead(1), lead(3), lead(4), lead(8, stage="IN_TALK")])
        self.crm.install(self)

    def ring(self, user: str, number: str, minutes_ago: float = 0) -> int:
        found = inbound.ring(user, number)
        if minutes_ago:
            self.age(found["id"], minutes_ago)
        return found["id"]

    def age(self, inbound_id: int, minutes: float):
        self.conn.execute("UPDATE op_inbound SET rang_at = ? WHERE id = ?",
                          (iso(datetime.now() - timedelta(minutes=minutes)), inbound_id))
        self.conn.commit()

    def miss(self, user: str, number: str, minutes_ago: float = 1) -> int:
        inbound_id = self.ring(user, number)
        inbound.end(user, inbound_id, answered=False)
        self.age(inbound_id, minutes_ago)
        return inbound_id


class AnsweringTests(InboundTestCase):
    def test_picking_up_a_known_caller_opens_a_desk_call_on_their_opportunity(self):
        found = inbound.ring("a1", KNOWN)
        self.assertEqual(found["caller"]["people"][0]["name"], "Lead 8")
        served = self.serve("a1")  # a queue contact they haven't called yet
        op = inbound.answer("a1", found["id"])
        self.assertEqual((op["source"], op["opportunity_id"], op["status"], op["in_crm"]),
                         ("inbound", "o8", "in_call", True))
        self.assertEqual(op["campaign_id"], campaigns.inbound_id(self.conn))
        # The contact they were served goes back to the queue, and the caller is now their current contact.
        self.assertEqual(operations.get_row(self.conn, served["id"])["status"], "released")
        self.assertEqual(operations.claim_next("a1")[0]["id"], op["id"])

        inbound.end("a1", found["id"], answered=True)
        self.assertIsNotNone(operations.get_row(self.conn, op["id"])["call_ended_at"])
        done = operations.finish(op["id"], "a1", answers={"call_reason": "prices"}, outcome="visit_booked", note="",
                                 stage="ACCEPTED")
        self.assertIsNone(done["crm_error"])
        self.assertEqual(self.crm.updates, [("o8", {"stage": "ACCEPTED"})])
        title, markdown, opportunity_id, _ = self.crm.notes_added[0]
        self.assertEqual((title, opportunity_id), ("Call · Salesman visit booked", "o8"))
        self.assertIn("Campaign: Incoming calls", markdown)

    def test_answering_twice_gives_the_same_desk_call(self):
        inbound_id = self.ring("a1", KNOWN)
        self.assertEqual(inbound.answer("a1", inbound_id)["id"], inbound.answer("a1", inbound_id)["id"])

    def test_only_the_agent_whose_phone_rang_can_answer(self):
        inbound_id = self.ring("a1", KNOWN)
        with self.assertRaises(OperationError):
            inbound.answer("a2", inbound_id)

    def test_an_unknown_caller_stays_on_the_desk_until_added_to_the_crm(self):
        op = inbound.answer("a1", self.ring("a1", UNKNOWN))
        self.assertFalse(op["in_crm"])
        self.assertTrue(op["opportunity_id"].startswith(operations.LOCAL_PREFIX))
        self.assertEqual(op["lead"]["contact"]["phones"], [UNKNOWN])
        done = operations.finish(op["id"], "a1", answers={}, outcome="wrong_number", note="", stage="REJECTED")
        self.assertIsNone(done["stage_after"])  # no stage to move
        self.assertEqual((self.crm.updates, self.crm.notes_added), ([], []))
        self.assertEqual(operations.today(self.conn, "a1")["done"], 1)  # a real call: it counts

    def test_an_unknown_caller_added_during_the_call_is_written_to_the_crm(self):
        op = inbound.answer("a1", self.ring("a1", UNKNOWN))
        linked = operations.link(op["id"], "a1", name="Sami Ben Ali", city="Sousse")
        self.assertTrue(linked["in_crm"])
        self.assertEqual(self.crm.created[0], ("person", "Sami Ben Ali", UNKNOWN))
        operations.finish(op["id"], "a1", answers={}, outcome="interested", note="", stage=None)
        self.assertEqual(self.crm.notes_added[0][2], linked["opportunity_id"])

    def test_a_caller_is_linked_to_another_of_their_opportunities(self):
        op = inbound.answer("a1", self.ring("a1", KNOWN))
        linked = operations.link(op["id"], "a1", opportunity_id="o3")
        self.assertEqual((linked["opportunity_id"], linked["lead"]["name"]), ("o3", "Lead 3 Facebook Lead"))

    def test_the_contact_served_to_another_agent_is_taken_back_when_they_call_in(self):
        held = self.serve("a2")
        self.assertEqual(held["opportunity_id"], "o1")
        op = inbound.answer("a1", self.ring("a1", QUEUED))
        self.assertEqual(op["opportunity_id"], "o1")
        self.assertEqual(operations.get_row(self.conn, held["id"])["status"], "released")


class MissedTests(InboundTestCase):
    def test_a_missed_call_is_listed_once_per_number_until_called_back(self):
        self.miss("a1", KNOWN, minutes_ago=3)
        self.miss("a2", KNOWN, minutes_ago=2)
        listed = inbound.missed(self.conn)
        self.assertEqual(len(listed), 1)
        self.assertEqual((listed[0]["tries"], listed[0]["contact_name"]), (2, None))
        self.assertEqual(listed[0]["prefer"], "a2")  # whose phone rang last, nobody knows them yet

    def test_a_missed_call_is_served_first_to_the_agent_whose_phone_rang_then_called_back(self):
        self.miss("a1", KNOWN)
        # a2 asks first: a1 is taking calls, so it waits for them for a few minutes; a2 gets the queue.
        self.assertEqual(self.serve("a2")["source"], "queue")
        op = self.serve("a1")
        self.assertEqual((op["source"], op["opportunity_id"]), ("missed", "o8"))
        self.assertEqual(inbound.missed(self.conn)[0]["serving"]["agent"], "a1")
        operations.start_call(op["id"], "a1")
        self.assertEqual(inbound.missed(self.conn), [])
        row = self.conn.execute("SELECT * FROM op_inbound").fetchone()
        self.assertEqual((row["resolution"], row["resolved_by"], row["followup_op_id"]), ("called_back", "a1", op["id"]))

    def test_after_a_few_minutes_or_when_that_agent_is_away_anyone_calls_back(self):
        self.miss("a1", KNOWN, minutes_ago=inbound.MISSED_EXCLUSIVE_MINUTES + 1)
        self.assertEqual(self.serve("a2")["source"], "missed")
        self.conn.execute("DELETE FROM op_calls")
        self.conn.execute("DELETE FROM op_inbound")
        self.conn.commit()
        self.miss("a1", KNOWN)
        operations.set_ready(self.conn, "a1", False)
        self.assertEqual(self.serve("a2")["source"], "missed")

    def test_a_missed_call_given_back_goes_to_someone_else(self):
        self.miss("a1", KNOWN)
        op = self.serve("a1")
        operations.give_back(op["id"], "a1")
        self.assertEqual(self.serve("a1")["source"], "queue")
        self.assertEqual(self.serve("a2")["source"], "missed")

    def test_a_fresh_missed_call_waits_a_moment_for_a_ring_group_answer(self):
        self.miss("a1", KNOWN, minutes_ago=0)
        self.assertEqual(self.serve("a1")["source"], "queue")

    def test_the_agent_who_knows_the_contact_gets_it_first(self):
        spoke = self.close(operations.start_direct("a3", "o8"), "interested")  # a3 spoke with Lead 8 before
        self.backdate(spoke["id"], 60)
        self.miss("a1", KNOWN)
        self.assertEqual(inbound.missed(self.conn)[0]["prefer"], "a3")
        self.assertEqual(self.serve("a1")["source"], "queue")
        self.assertEqual(self.serve("a3")["source"], "missed")

    def test_ring_group_agents_who_did_not_pick_up_leave_no_missed_call(self):
        answered = self.ring("a1", KNOWN)
        other = self.ring("a2", KNOWN)
        inbound.answer("a1", answered)
        inbound.end("a2", other, answered=False)
        self.assertEqual(inbound.missed(self.conn), [])
        stats = inbound.stats(self.conn, datetime.now().date().isoformat(),
                              (datetime.now() + timedelta(days=1)).date().isoformat())
        self.assertEqual((stats["team"]["calls"], stats["team"]["answered"], stats["team"]["missed"]), (1, 1, 0))

    def test_a_caller_who_gets_through_later_is_no_longer_waiting(self):
        self.miss("a1", KNOWN, minutes_ago=10)
        inbound.answer("a2", self.ring("a2", KNOWN))
        self.assertEqual(inbound.missed(self.conn), [])
        self.assertEqual(self.conn.execute("SELECT resolution FROM op_inbound WHERE result = 'missed'").fetchone()[0],
                         "got_through")

    def test_busy_turned_away_and_never_ended_rings_are_missed_too(self):
        inbound.busy("a1", KNOWN)
        stuck = self.ring("a2", UNKNOWN, minutes_ago=inbound.STUCK_RINGING_MINUTES + 1)
        listed = {m["key"]: m for m in inbound.missed(self.conn)}
        self.assertTrue(listed["22602718"]["busy"])
        self.assertIn("98765432", listed)
        self.assertEqual(self.conn.execute("SELECT result FROM op_inbound WHERE id = ?", (stuck,)).fetchone()[0],
                         "missed")

    def test_declined_and_answered_elsewhere(self):
        declined = self.ring("a1", KNOWN)
        inbound.end("a1", declined, answered=False, declined=True)
        elsewhere = self.ring("a2", UNKNOWN)
        inbound.end("a2", elsewhere, answered=False, elsewhere=True)
        self.assertEqual([m["key"] for m in inbound.missed(self.conn)], ["22602718"])

    def test_a_missed_call_can_be_dismissed_or_taken_now(self):
        self.miss("a1", KNOWN)
        self.miss("a1", UNKNOWN)
        inbound.dismiss("a2", "22602718")
        with self.assertRaises(OperationError):
            inbound.dismiss("a2", "22602718")
        op = inbound.take("a2", "98765432")
        self.assertEqual((op["source"], op["in_crm"]), ("missed", False))
        with self.assertRaises(OperationError):
            inbound.take("a3", "98765432")

    def test_a_missed_call_left_waiting_raises_an_alert(self):
        self.miss("a1", KNOWN, minutes_ago=3)
        self.assertFalse([a for a in alerts.current(self.conn) if a["kind"] == "missed_call"])
        self.age(self.conn.execute("SELECT id FROM op_inbound").fetchone()[0], 30)
        found = [a for a in alerts.current(self.conn) if a["kind"] == "missed_call"]
        self.assertEqual([(a["level"], a["agent"]) for a in found], [("critical", "a1")])

    def test_figures_count_calls_answered_missed_and_how_fast_they_were_called_back(self):
        inbound.answer("a1", self.ring("a1", KNOWN))
        self.miss("a2", UNKNOWN, minutes_ago=30)
        op = inbound.take("a3", "98765432")
        operations.start_call(op["id"], "a3")
        today = datetime.now().date()
        stats = inbound.stats(self.conn, today.isoformat(), (today + timedelta(days=1)).isoformat())
        team = stats["team"]
        self.assertEqual((team["calls"], team["answered"], team["missed"], team["called_back"], team["waiting"]),
                         (2, 1, 1, 1, 0))
        self.assertEqual(team["answer_rate"], 0.5)
        self.assertGreaterEqual(team["avg_callback_minutes"], 29)
        by_agent = {a["username"]: a for a in stats["agents"]}
        self.assertEqual((by_agent["a2"]["missed"], by_agent["a3"]["called_back"]), (1, 1))
        mine = inbound.stats(self.conn, today.isoformat(), (today + timedelta(days=1)).isoformat(), "a1")
        self.assertEqual([a["username"] for a in mine["agents"]], ["a1"])


class InboundCampaignTests(InboundTestCase):
    def test_the_incoming_calls_campaign_is_not_picked_nor_deleted_and_has_no_queue(self):
        inbound_id = campaigns.inbound_id(self.conn)
        with self.assertRaises(OperationError):
            operations.set_campaign(self.conn, "a1", inbound_id)
        with self.assertRaises(CampaignError):
            campaigns.delete(self.conn, inbound_id)
        saved = campaigns.save(self.conn, inbound_id, {**campaigns.get(self.conn, inbound_id), "name": "Hotline",
                                                       "stages": [], "active": False})
        self.assertEqual((saved["name"], saved["kind"], saved["active"], saved["stages"]),
                         ("Hotline", "inbound", True, []))
        self.assertNotEqual(campaigns.default_id(self.conn), inbound_id)
        self.assertEqual(operations.agent_campaign(self.conn, "a1")["kind"], "outbound")

    def test_callbacks_booked_on_an_incoming_call_go_to_anyone(self):
        op = inbound.answer("a1", self.ring("a1", KNOWN))
        operations.finish(op["id"], "a1", answers={}, outcome="callback_requested", note="", stage=None,
                          callback_at=iso(datetime.now() + timedelta(minutes=5)))
        self.conn.execute("UPDATE op_calls SET due_at = ? WHERE status = 'scheduled'",
                          (iso(datetime.now() - timedelta(minutes=1)),))
        self.conn.commit()
        callback = self.serve("a2")
        self.assertEqual((callback["source"], callback["opportunity_id"]), ("callback", "o8"))


if __name__ == "__main__":
    unittest.main()
