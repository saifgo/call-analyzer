"""The call desk (operations.py), its campaigns, figures and recording links (campaigns.py, desk_stats.py), and the
encryption of the softphone credentials (vault.py). The CRM is a fake: nothing here talks to a real one.

    python -m unittest discover tests -v
"""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock
from datetime import datetime, timedelta
from pathlib import Path

# The settings are read when call_analyzer is imported, so point it at a scratch folder first.
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = str(Path(TMP.name) / "data")
os.environ["ENV_FILE"] = str(Path(TMP.name) / ".env")
for key in ("CRM_API_KEY", "CRM_BASE_URL", "SECRET_KEY", "RECORDING_CLOCK_OFFSET_MINUTES"):
    os.environ.pop(key, None)

from call_analyzer import campaigns, crm, db, desk_stats, floor, operations, vault  # noqa: E402
from call_analyzer.adapters.crm.base import CrmAdapter  # noqa: E402
from call_analyzer.campaigns import CampaignError  # noqa: E402
from call_analyzer.operations import OperationError  # noqa: E402

STAGES = [{"value": v, "label": v.title()} for v in
          ("NEW", "ATTEMPTED", "IN_TALK", "WAITING_REPLY", "ACCEPTED", "ACCOUNT_MADE", "REJECTED", "DEAD")]


def lead(i: int, phone: str | None = "2260271{i}", stage: str = "NEW") -> dict:
    contact = None if phone is None else {
        "id": f"p{i}", "name": f"Lead {i}", "email": None, "phones": [phone.format(i=i)], "job_title": None,
        "city": None, "company": None, "created_at": None, "last_contact_at": None, "url": None}
    return {"id": f"o{i}", "name": f"Lead {i} Facebook Lead", "stage": stage, "amount": None, "currency": None,
            "close_date": None, "company": None, "owner": None, "created_at": f"2026-10-0{i}T10:00:00Z",
            "updated_at": None, "url": f"https://crm.example.com/object/opportunity/o{i}", "contact": contact}


class FakeCrm(CrmAdapter):
    """A CRM adapter that records what would have been written. Whatever it doesn't implement raises
    NotImplementedError (CrmAdapter), so nothing reaches a real CRM."""
    name = "fake"
    label = "Fake CRM"

    def __init__(self, leads: list[dict]):
        self.by_stage: dict[str, list[dict]] = {}
        for item in leads:
            self.by_stage.setdefault(item["stage"], []).append(item)
        self.updates, self.people, self.notes_added = [], [], []
        self.fail_notes = False
        self.fetched = []  # (stage, limit, after) of each list_opportunities

    def install(self, test: unittest.TestCase):
        crm.use(self)
        test.addCleanup(crm.use, None)

    def is_configured(self):
        return True

    def list_opportunities(self, stage, oldest_first, limit, after=None):
        self.fetched.append((stage, limit, after))
        found = sorted(self.by_stage.get(stage, []), key=lambda x: x["created_at"], reverse=not oldest_first)
        start = int(after or 0)
        if limit is None:
            return found[start:], None
        return found[start:start + limit], str(start + limit) if start + limit < len(found) else None

    def stages(self):
        return STAGES

    def update_opportunity(self, opportunity_id, fields):
        self.updates.append((opportunity_id, fields))

    def update_person(self, person_id, fields):
        self.people.append((person_id, fields))

    def add_note(self, title, markdown, opportunity_id, person_id):
        if self.fail_notes:
            raise crm.CrmError("CRM down")
        self.notes_added.append((title, markdown, opportunity_id, person_id))
        return f"n{len(self.notes_added)}"

    def notes(self, opportunity_id, person_id, limit):
        return []

    def get_opportunity(self, opportunity_id):
        return next(x for items in self.by_stage.values() for x in items if x["id"] == opportunity_id)

    def find_people(self, key):
        return []


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


class DeskTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        for table in ("op_calls", "op_agents", "op_campaigns", "op_presence", "calls", "softphones", "user_agents",
                      "wa_messages", "op_targets", "op_pause_reasons", "op_pauses", "op_settings", "op_inbound"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        self.crm = FakeCrm([lead(1), lead(2, phone=None), lead(3), lead(4), lead(5, stage="ATTEMPTED"), lead(6),
                            lead(7)])
        self.crm.install(self)
        crm.forget_leads()
        for user in ("a1", "a2", "a3"):
            operations.set_ready(self.conn, user, True)

    def serve(self, user: str) -> dict:
        op, reason = operations.claim_next(user)
        self.assertIsNotNone(op, reason)
        return op

    def close(self, op: dict, outcome: str, **kwargs) -> dict:
        operations.start_call(op["id"], op["agent"])
        return operations.finish(op["id"], op["agent"], answers=kwargs.pop("answers", {}), outcome=outcome,
                                 note=kwargs.pop("note", ""), stage=kwargs.pop("stage", None), **kwargs)

    def backdate(self, op_id: int, minutes: int):
        """Make a closed call look like it happened `minutes` ago (callbacks and attempts go by time)."""
        when = iso(datetime.now() - timedelta(minutes=minutes))
        self.conn.execute("UPDATE op_calls SET finished_at = ?, call_started_at = ?, call_ended_at = ? WHERE id = ?",
                          (when, when, when, op_id))
        self.conn.commit()

    def campaign(self, **fields) -> dict:
        base = campaigns.get(self.conn, None)
        data = {**base, **fields}
        return campaigns.save(self.conn, base["id"] if "new" not in fields else None,
                              {k: v for k, v in data.items() if k != "new"})


class QueueTests(DeskTestCase):
    def test_contacts_are_served_oldest_first_one_agent_each_skipping_those_without_a_phone(self):
        served = [self.serve(u)["opportunity_id"] for u in ("a1", "a2", "a3")]
        self.assertEqual(served, ["o1", "o3", "o4"])
        # Asking again gives back the contact already held.
        self.assertEqual(self.serve("a1")["opportunity_id"], "o1")

    def test_a_closed_contact_is_not_served_again_and_the_queue_runs_dry(self):
        served = []
        while (op := operations.claim_next("a1")[0]) is not None:
            served.append(op["opportunity_id"])
            self.close(op, "not_interested")
        # The New contacts oldest first, then the Attempted one.
        self.assertEqual(served, ["o1", "o3", "o4", "o6", "o7", "o5"])
        self.assertEqual(operations.claim_next("a2"), (None, None))
        counts = operations.queue_counts(self.conn, campaigns.get(self.conn, None))
        self.assertEqual((counts["waiting"], counts["no_phone"]), (0, 1))

    def test_the_queue_reads_the_crm_a_batch_at_a_time(self):
        with mock.patch.dict(os.environ, {"CRM_QUEUE_BATCH": "2"}):
            crm.forget_leads()
            counts = operations.queue_counts(self.conn, campaigns.get(self.conn, None))
            # It holds o1 and o2 (no phone); the CRM has more.
            self.assertEqual((counts["waiting"], counts["no_phone"], counts["truncated"]), (1, 1, True))
            self.assertEqual(self.crm.fetched, [("NEW", 2, None)])
            served = []
            while (op := operations.claim_next("a1")[0]) is not None:
                served.append(op["opportunity_id"])
                self.close(op, "not_interested")
            # Contacts already handled still sit at New here: the queue reads past them, batch by batch.
            self.assertEqual(served, ["o1", "o3", "o4", "o6", "o7", "o5"])
            self.assertEqual({limit for _, limit, _ in self.crm.fetched}, {2})
            counts = operations.queue_counts(self.conn, campaigns.get(self.conn, None))
            self.assertEqual((counts["waiting"], counts["no_phone"], counts["truncated"]), (0, 1, False))

    def test_a_batch_of_0_reads_every_contact_at_once(self):
        with mock.patch.dict(os.environ, {"CRM_QUEUE_BATCH": "0"}):
            crm.forget_leads()
            counts = operations.queue_counts(self.conn, campaigns.get(self.conn, None))
            self.assertEqual((counts["waiting"], counts["no_phone"], counts["truncated"]), (6, 1, False))
            self.assertEqual(self.crm.fetched, [("NEW", None, None), ("ATTEMPTED", None, None)])
            self.assertEqual(self.serve("a1")["opportunity_id"], "o1")

    def test_the_queue_count_does_not_wait_for_a_slow_crm(self):
        campaign = campaigns.get(self.conn, None)
        self.assertEqual(operations.queue_counts(self.conn, campaign)["waiting"], 6)
        # The CRM gains a contact but hangs: the desk's count keeps the last list, fetched again in the background.
        release, fetched = threading.Event(), threading.Event()
        slow = self.crm.list_opportunities

        def hang(*args):
            release.wait(10)
            try:
                return slow(*args)
            finally:
                fetched.set()

        self.crm.list_opportunities = hang
        self.crm.by_stage["NEW"].append(lead(8))
        crm.forget_leads()
        started = time.monotonic()
        self.assertEqual(operations.queue_counts(self.conn, campaign)["waiting"], 6)
        self.assertLess(time.monotonic() - started, 2)
        release.set()
        self.assertTrue(fetched.wait(5))
        for _ in range(50):  # the background fetch stores its list right after returning it
            if operations.queue_counts(self.conn, campaign)["waiting"] == 7:
                break
            time.sleep(0.05)
        self.assertEqual(operations.queue_counts(self.conn, campaign)["waiting"], 7)

    def test_given_back_contact_goes_to_someone_else_not_back_to_the_same_agent(self):
        op = self.serve("a1")
        operations.give_back(op["id"], "a1")
        self.assertEqual(self.serve("a2")["opportunity_id"], "o1")
        self.assertEqual(self.serve("a1")["opportunity_id"], "o3")

    def test_a_started_call_cannot_be_given_back(self):
        op = self.serve("a1")
        operations.start_call(op["id"], "a1")
        with self.assertRaises(OperationError):
            operations.give_back(op["id"], "a1")

    def test_contacts_of_a_desk_gone_quiet_go_back_to_the_queue(self):
        op = self.serve("a1")
        self.conn.execute("UPDATE op_agents SET last_seen = ? WHERE username = 'a1'",
                          (iso(datetime.now() - timedelta(minutes=operations.STALE_MINUTES + 1)),))
        self.conn.commit()
        operations.release_stale(self.conn)
        self.assertEqual(operations.get_row(self.conn, op["id"])["status"], "released")
        self.assertEqual(self.serve("a2")["opportunity_id"], "o1")

    def test_only_the_agent_holding_a_contact_can_work_it(self):
        op = self.serve("a1")
        with self.assertRaises(OperationError) as ctx:
            operations.start_call(op["id"], "a2")
        self.assertEqual(ctx.exception.status, 409)


class CallbackTests(DeskTestCase):
    def test_a_callback_waits_until_due_then_comes_before_the_queue(self):
        first = self.serve("a1")
        later = iso(datetime.now() + timedelta(hours=2))
        self.close(first, "callback_requested", callback_at=later)
        # Not due: a2 gets the next contact from the queue.
        self.assertEqual(self.serve("a2")["opportunity_id"], "o3")
        self.conn.execute("UPDATE op_calls SET due_at = ? WHERE status = 'scheduled'",
                          (iso(datetime.now() - timedelta(minutes=1)),))
        self.conn.commit()
        callback = self.serve("a3")
        self.assertEqual((callback["opportunity_id"], callback["source"]), ("o1", "callback"))

    def test_a_callback_kept_for_an_agent_is_only_served_to_them(self):
        op = self.serve("a1")
        self.close(op, "callback_requested", callback_at=iso(datetime.now() + timedelta(minutes=5)), callback_mine=True)
        self.conn.execute("UPDATE op_calls SET due_at = ? WHERE status = 'scheduled'",
                          (iso(datetime.now() - timedelta(minutes=1)),))
        self.conn.commit()
        self.assertEqual(self.serve("a2")["source"], "queue")
        self.assertEqual(self.serve("a1")["source"], "callback")

    def test_a_callback_must_be_in_the_future(self):
        op = self.serve("a1")
        operations.start_call(op["id"], "a1")
        with self.assertRaises(OperationError):
            operations.finish(op["id"], "a1", answers={}, outcome="busy", note="", stage=None,
                              callback_at=iso(datetime.now() - timedelta(hours=1)))


    def book(self, user: str, **kwargs) -> dict:
        """Serve the user a contact and book a callback with them in two hours. Returns the waiting callback."""
        op = self.serve(user)
        self.close(op, "callback_requested", callback_at=iso(datetime.now() + timedelta(hours=2)), **kwargs)
        return operations.to_dict(self.conn.execute(
            "SELECT * FROM op_calls WHERE status = 'scheduled' AND scheduled_from = ?", (op["id"],)).fetchone(), {})

    def test_an_agent_can_call_their_callback_before_it_is_due(self):
        cb = self.book("a1")
        held = self.serve("a1")  # holding a queue contact they haven't called yet
        taken = operations.take_callback("a1", cb["id"])
        self.assertEqual((taken["id"], taken["status"], taken["agent"]), (cb["id"], "assigned", "a1"))
        self.assertEqual(operations.get_row(self.conn, held["id"])["status"], "released")
        self.close(taken, "interested")
        self.assertEqual(operations.get_row(self.conn, cb["id"])["status"], "done")

    def test_only_the_agent_who_booked_it_can_take_a_callback_early_and_not_during_a_call(self):
        cb = self.book("a1")
        with self.assertRaises(OperationError) as ctx:
            operations.take_callback("a2", cb["id"])
        self.assertEqual(ctx.exception.status, 403)
        operations.start_call(self.serve("a1")["id"], "a1")
        with self.assertRaises(OperationError) as ctx:
            operations.take_callback("a1", cb["id"])
        self.assertEqual(ctx.exception.status, 409)

    def test_a_given_back_early_callback_waits_again(self):
        cb = self.book("a1")
        operations.give_back(operations.take_callback("a1", cb["id"])["id"], "a1")
        self.assertEqual(operations.get_row(self.conn, cb["id"])["status"], "scheduled")

    def test_reaching_the_contact_another_way_closes_their_waiting_callback(self):
        cb = self.book("a1")
        op = operations.start_direct("a2", cb["opportunity_id"])
        self.close(op, "interested")
        self.assertEqual(operations.get_row(self.conn, cb["id"])["status"], "cancelled")

    def test_an_unanswered_call_another_way_keeps_the_callback_unless_it_books_a_new_one(self):
        cb = self.book("a1")
        self.close(operations.start_direct("a2", cb["opportunity_id"]), "no_answer")
        self.assertEqual(operations.get_row(self.conn, cb["id"])["status"], "scheduled")
        self.close(operations.start_direct("a2", cb["opportunity_id"]), "no_answer",
                   callback_at=iso(datetime.now() + timedelta(hours=3)))
        self.assertEqual(operations.get_row(self.conn, cb["id"])["status"], "cancelled")
        waiting = self.conn.execute("SELECT COUNT(*) FROM op_calls WHERE status = 'scheduled' AND opportunity_id = ?",
                                    (cb["opportunity_id"],)).fetchone()[0]
        self.assertEqual(waiting, 1)


class FinishTests(DeskTestCase):
    def test_closing_a_call_moves_the_stage_copies_answers_to_the_contact_and_writes_a_note(self):
        op = self.serve("a1")
        done = self.close(op, "account_created", stage="ACCOUNT_MADE", note="Signed up on the spot",
                          answers={"city": " Sfax ", "has_pos": 1, "shops_count": "3", "operators": ["orange", "xx"],
                                   "business_type": "not-an-option", "unknown": "dropped"})
        self.assertIsNone(done["crm_error"])
        self.assertEqual(done["answers"], {"city": "Sfax", "has_pos": True, "shops_count": 3, "operators": ["orange"]})
        self.assertEqual(self.crm.updates, [("o1", {"stage": "ACCOUNT_MADE"})])
        self.assertEqual(self.crm.people, [("p1", {"city": "Sfax", "havepos": True})])
        title, markdown, opportunity_id, person_id = self.crm.notes_added[0]
        self.assertEqual((title, opportunity_id, person_id), ("Call · Account created", "o1", "p1"))
        self.assertIn("Campaign: New leads", markdown)
        self.assertIn("Signed up on the spot", markdown)
        self.assertIn("Operators they sell: Orange", markdown)

    def test_a_failed_crm_write_is_kept_and_retrying_does_not_write_the_note_twice(self):
        self.crm.fail_notes = True
        done = self.close(self.serve("a1"), "interested")
        self.assertIn("Note not written", done["crm_error"])
        self.crm.fail_notes = False
        operations.sync_crm(done["id"])
        operations.sync_crm(done["id"])
        row = operations.get_row(self.conn, done["id"])
        self.assertIsNone(row["crm_error"])
        self.assertEqual(len(self.crm.notes_added), 1)

    def test_an_outcome_of_another_campaign_is_refused(self):
        op = self.serve("a1")
        operations.start_call(op["id"], "a1")
        with self.assertRaises(OperationError):
            operations.finish(op["id"], "a1", answers={}, outcome="made_up", note="", stage=None)

    def test_test_calls_never_reach_the_crm_nor_the_days_figures(self):
        op = operations.start_test("a1", "+216 20 123 456")
        self.assertTrue(op["test"])
        self.close(op, "account_created", stage="ACCOUNT_MADE")
        self.assertEqual((self.crm.updates, self.crm.notes_added), ([], []))
        self.assertEqual(operations.today(self.conn, "a1")["done"], 0)
        # Starting a test call pauses the agent, so no real contact follows it.
        self.assertFalse(operations.heartbeat(self.conn, "a1"))

    def test_the_days_figures_count_reached_contacts_and_wins(self):
        self.close(self.serve("a1"), "account_created")
        self.close(self.serve("a1"), "no_answer")
        self.close(self.serve("a1"), "not_interested")
        today = operations.today(self.conn, "a1")
        self.assertEqual((today["done"], today["reached"], today["success"]), (3, 2, 1))


class AttemptTests(DeskTestCase):
    def test_after_max_unanswered_calls_no_callback_is_booked_and_the_contact_moves_on(self):
        self.campaign(max_attempts=2, exhausted_stage="DEAD", retry_minutes=30)
        first = self.serve("a1")
        context = operations.context(self.conn, operations.get_row(self.conn, first["id"]))
        self.assertEqual((context["attempts"], context["last_try"]), (0, False))
        self.assertIsNotNone(context["retry_at"])
        done = self.close(first, "no_answer", callback_at=iso(datetime.now() + timedelta(minutes=30)))
        self.assertFalse(done["attempts_exhausted"])
        self.backdate(done["id"], 40)
        self.conn.execute("UPDATE op_calls SET due_at = ? WHERE status = 'scheduled'",
                          (iso(datetime.now() - timedelta(minutes=1)),))
        self.conn.commit()

        second = self.serve("a1")
        self.assertEqual(second["source"], "callback")
        context = operations.context(self.conn, operations.get_row(self.conn, second["id"]))
        self.assertEqual((context["attempts"], context["last_try"], context["retry_at"]), (1, True, None))
        done = self.close(second, "busy", callback_at=iso(datetime.now() + timedelta(minutes=30)))
        self.assertTrue(done["attempts_exhausted"])
        self.assertEqual(done["stage_after"], "DEAD")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM op_calls WHERE status = 'scheduled'").fetchone()[0], 0)

    def test_speaking_with_the_contact_resets_the_count(self):
        self.campaign(max_attempts=2)
        done = self.close(self.serve("a1"), "no_answer", callback_at=iso(datetime.now() + timedelta(minutes=1)))
        self.backdate(done["id"], 30)
        callback_id = self.conn.execute("SELECT id FROM op_calls WHERE status = 'scheduled'").fetchone()[0]
        self.conn.execute("UPDATE op_calls SET status = 'assigned', agent = 'a1', due_at = ? WHERE id = ?",
                          (iso(datetime.now()), callback_id))
        self.conn.commit()
        row = operations.get_row(self.conn, callback_id)
        self.assertEqual(operations.attempts(self.conn, row), 1)
        self.conn.execute("UPDATE op_calls SET outcome = 'interested' WHERE id = ?", (done["id"],))
        self.conn.commit()
        self.assertEqual(operations.attempts(self.conn, row), 0)


class AttemptedQueueTests(DeskTestCase):
    """New contacts we couldn't reach move to Attempted, and the New leads queue serves those after the New ones."""

    def serve_until(self, user: str, opportunity_id: str) -> dict:
        """Close every contact served before `opportunity_id` as not interested, and return that one."""
        while (op := self.serve(user))["opportunity_id"] != opportunity_id:
            self.close(op, "not_interested")
        return op

    def test_an_unanswered_new_contact_moves_to_attempted_even_if_the_agent_kept_its_stage(self):
        done = self.close(self.serve("a1"), "no_answer", stage=None)
        self.assertEqual((done["stage_before"], done["stage_after"]), ("NEW", "ATTEMPTED"))
        self.assertIn(("o1", {"stage": "ATTEMPTED"}), self.crm.updates)

    def test_a_rejected_or_reached_contact_does_not_move_to_attempted(self):
        self.assertEqual(self.close(self.serve("a1"), "wrong_number")["stage_after"], None)
        self.assertEqual(self.close(self.serve("a1"), "no_answer", stage="REJECTED")["stage_after"], "REJECTED")
        self.assertEqual(self.close(self.serve("a1"), "interested")["stage_after"], None)

    def test_an_unanswered_contact_at_a_later_stage_keeps_it(self):
        op = self.serve_until("a1", "o5")  # already Attempted
        self.assertEqual(self.close(op, "no_answer")["stage_after"], None)

    def test_an_attempted_contact_is_tried_again_after_the_retry_time_until_the_tries_run_out(self):
        self.campaign(max_attempts=2, retry_minutes=60)
        done = self.close(self.serve_until("a1", "o5"), "no_answer")
        self.assertEqual(operations.claim_next("a1"), (None, None))  # too soon
        self.backdate(done["id"], 61)
        again = self.serve("a1")
        self.assertEqual((again["opportunity_id"], again["source"]), ("o5", "queue"))
        done = self.close(again, "busy")
        self.assertTrue(done["attempts_exhausted"])
        self.backdate(done["id"], 61)
        self.assertEqual(operations.claim_next("a1"), (None, None))  # no tries left

    def test_attempted_contacts_never_tried_go_before_those_tried_again(self):
        self.crm.by_stage["ATTEMPTED"].append(lead(8, stage="ATTEMPTED"))
        crm.forget_leads()
        done = self.close(self.serve_until("a1", "o5"), "no_answer")
        self.backdate(done["id"], 200)
        self.assertEqual(self.serve("a1")["opportunity_id"], "o8")

    def test_the_new_leads_campaign_made_before_gets_attempted_once(self):
        first = campaigns.get(self.conn, None)
        self.conn.execute("UPDATE op_campaigns SET stages = '[\"NEW\"]' WHERE id = ?", (first["id"],))
        self.conn.execute("DELETE FROM op_settings")
        self.conn.commit()
        self.assertEqual(campaigns.get(self.conn, None)["stages"], ["NEW", "ATTEMPTED"])
        self.campaign(stages=["NEW"])  # an admin takes it out again: it stays out
        self.assertEqual(campaigns.get(self.conn, None)["stages"], ["NEW"])


class CampaignTests(DeskTestCase):
    def test_the_first_campaign_is_the_desk_as_it_was(self):
        first = campaigns.get(self.conn, None)
        self.assertEqual((first["name"], first["stages"]), ("New leads", ["NEW", "ATTEMPTED"]))
        self.assertEqual([q["key"] for q in first["questions"]],
                         [q["key"] for q in campaigns.DEFAULT_QUESTIONS])
        self.assertTrue(campaigns.outcome(first, "account_created")["success"])
        self.assertFalse(campaigns.outcome(first, "no_answer")["reached"])

    def test_agents_work_the_queue_of_the_campaign_they_pick(self):
        other = self.campaign(new=True, name="Retry the attempted", stages=["ATTEMPTED"])
        operations.set_campaign(self.conn, "a2", other["id"])
        op = self.serve("a2")
        self.assertEqual((op["opportunity_id"], op["campaign_id"]), ("o5", other["id"]))
        self.assertEqual(self.serve("a1")["opportunity_id"], "o1")

    def test_a_campaigns_own_questions_and_outcomes_are_used(self):
        other = self.campaign(new=True, name="Win-back", stages=["NEW"],
                              questions=[{"label": "Why did you leave?", "type": "text"}],
                              outcomes=[{"label": "Came back", "reached": True, "success": True, "stage": "ACCEPTED"},
                                        {"label": "No answer"}])
        operations.set_campaign(self.conn, "a1", other["id"])
        done = self.close(self.serve("a1"), "came_back", answers={"why_did_you_leave": "Price", "city": "Sfax"})
        self.assertEqual(done["answers"], {"why_did_you_leave": "Price"})
        self.assertEqual(self.crm.notes_added[0][0], "Call · Came back")

    def test_outside_calling_hours_only_callbacks_are_served(self):
        now = datetime.now()
        closed_day = now.isoweekday() % 7 + 1  # tomorrow: today is closed
        self.campaign(call_days=[closed_day])
        op, reason = operations.claim_next("a1")
        self.assertIsNone(op)
        self.assertIn("only called", reason)
        later = campaigns.next_open(campaigns.get(self.conn, None), now)
        self.assertEqual(later.isoweekday(), closed_day)

    def test_calling_hours(self):
        c = {"call_start": "09:00", "call_end": "18:00", "call_days": [1, 2, 3, 4, 5]}
        friday_evening, monday = datetime(2026, 10, 9, 18, 30), datetime(2026, 10, 12, 9, 0)
        self.assertTrue(campaigns.is_open(c, datetime(2026, 10, 9, 17, 59)))
        self.assertFalse(campaigns.is_open(c, friday_evening))
        self.assertEqual(campaigns.next_open(c, friday_evening), monday)
        self.assertEqual(campaigns.next_open(c, datetime(2026, 10, 12, 7, 0)), monday)

    def test_questions_are_checked_and_keys_made_from_labels(self):
        clean = campaigns.validate_questions([
            {"label": "Has a POS?", "type": "boolean"},
            {"label": "Which one?", "type": "select", "options": ["Ingenico", "PAX"],
             "show_if": {"has_a_pos": ["true"]}},
            {"label": "Has a POS?", "type": "text"},
        ])
        self.assertEqual([q["key"] for q in clean], ["has_a_pos", "which_one", "has_a_pos_2"])
        self.assertEqual(clean[1]["options"], [["ingenico", "Ingenico"], ["pax", "PAX"]])
        bad = [
            [{"label": "X", "type": "nope"}],
            [{"label": "X", "type": "select", "options": []}],
            [{"label": "A", "type": "text", "show_if": {"b": ["x"]}}, {"label": "B", "key": "b", "type": "select",
                                                                       "options": ["x"]}],
            [{"label": "A", "key": "k", "type": "text"}, {"label": "B", "key": "k", "type": "text"}],
            [{"label": "A", "type": "text", "crm": "company.name"}],
        ]
        for questions in bad:
            with self.subTest(questions=questions), self.assertRaises(CampaignError):
                campaigns.validate_questions(questions)

    def test_translations_keep_known_languages_fields_and_choices(self):
        [q] = campaigns.validate_questions([
            {"label": "Shop?", "type": "select", "options": [["a", "A"], ["b", "B"]],
             "tr": {"fr": {"label": "Commerce ?", "section": " ", "options": {"a": "Aa", "zz": "Z", "b": ""}},
                    "ar": {"help": "مساعدة", "colour": "x"}, "de": {"label": "Laden?"}}},
        ])
        self.assertEqual(q["tr"], {"fr": {"label": "Commerce ?", "options": {"a": "Aa"}}, "ar": {"help": "مساعدة"}})
        [o] = campaigns.validate_outcomes([{"label": "Won", "tr": {"ar": {"label": "ربح"}, "fr": {"label": ""}}}])
        self.assertEqual(o["tr"], {"ar": {"label": "ربح"}})
        [plain] = campaigns.validate_questions([{"label": "Plain", "type": "text", "tr": "junk"}])
        self.assertNotIn("tr", plain)

    def test_a_campaign_with_calls_is_archived_not_deleted_and_one_stays_active(self):
        first = campaigns.get(self.conn, None)
        with self.assertRaises(CampaignError):
            campaigns.delete(self.conn, first["id"])
        other = self.campaign(new=True, name="Other")
        self.assertEqual(campaigns.delete(self.conn, other["id"]), "deleted")
        other = self.campaign(new=True, name="Other")
        self.close(self.serve("a1"), "interested")
        self.assertEqual(campaigns.delete(self.conn, first["id"]), "archived")
        self.assertEqual(operations.agent_campaign(self.conn, "a1")["id"], other["id"])


class PresenceTests(DeskTestCase):
    def test_desk_time_counts_check_ins_while_ready_only(self):
        start = datetime.now().replace(microsecond=0)
        self.conn.execute("UPDATE op_agents SET last_seen = ? WHERE username = 'a1'", (iso(start - timedelta(seconds=15)),))
        self.conn.commit()
        operations.heartbeat(self.conn, "a1")
        operations.set_ready(self.conn, "a1", False)
        self.conn.execute("UPDATE op_agents SET last_seen = ? WHERE username = 'a1'", (iso(start - timedelta(seconds=15)),))
        self.conn.commit()
        operations.heartbeat(self.conn, "a1")  # paused: not counted
        self.conn.execute("UPDATE op_agents SET ready = 1, last_seen = ? WHERE username = 'a1'",
                          (iso(start - timedelta(minutes=10)),))
        self.conn.commit()
        operations.heartbeat(self.conn, "a1")  # a gap that long is a closed tab: not counted
        seconds = self.conn.execute("SELECT SUM(ready_seconds) FROM op_presence WHERE username = 'a1'").fetchone()[0]
        self.assertGreaterEqual(seconds, 15)
        self.assertLess(seconds, 20)


class PauseTests(DeskTestCase):
    def reason(self, label: str) -> dict:
        return next(r for r in floor.reasons(self.conn) if r["label"] == label)

    def test_a_pause_records_its_reason_and_ends_when_taking_calls_again(self):
        lunch = self.reason("Lunch")
        operations.set_ready(self.conn, "a1", False, lunch["id"])
        state = floor.pause_state(self.conn, "a1")
        self.assertEqual((state["label"], state["limit_minutes"], state["over"]), ("Lunch", 60, False))
        operations.set_ready(self.conn, "a1", True)
        self.assertIsNone(floor.pause_state(self.conn, "a1"))
        rows = self.conn.execute("SELECT label, closed FROM op_pauses WHERE username = 'a1'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Lunch", 1)])

    def test_a_pause_over_its_limit_shows_and_counts_in_the_kpis(self):
        brk = self.reason("Break")
        operations.set_ready(self.conn, "a1", False, brk["id"])
        started = iso(datetime.now().replace(microsecond=0) - timedelta(minutes=20))
        self.conn.execute("UPDATE op_pauses SET started_at = ? WHERE username = 'a1'", (started,))
        self.conn.commit()
        if started[:10] != datetime.now().date().isoformat():
            self.skipTest("too close to midnight")
        operations.heartbeat(self.conn, "a1")  # the pause lasts until now
        self.assertTrue(floor.pause_state(self.conn, "a1")["over"])
        board = {a["username"]: a for a in operations.board(self.conn)["agents"]}
        self.assertTrue(board["a1"]["pause"]["over"])
        team = desk_stats.kpis(self.conn)["team"]
        self.assertGreaterEqual(team["pause_seconds"], 20 * 60)
        self.assertEqual(team["pauses_over"], 1)
        self.assertIn("Break", team["pause_reasons"])

    def test_pausing_without_a_reason_keeps_the_current_pause(self):
        training = self.reason("Training")
        operations.set_ready(self.conn, "a1", False, training["id"])
        operations.start_test("a1", "22602710")
        self.assertEqual(floor.pause_state(self.conn, "a1")["label"], "Training")

    def test_a_pause_left_open_overnight_ends_at_its_last_check_in(self):
        operations.set_ready(self.conn, "a1", False, self.reason("Break")["id"])
        yesterday = iso(datetime.now() - timedelta(days=1))
        self.conn.execute("UPDATE op_pauses SET started_at = ?, ended_at = ?", (yesterday, yesterday))
        self.conn.commit()
        operations.heartbeat(self.conn, "a1")
        self.assertIsNone(floor.pause_state(self.conn, "a1"))
        self.assertEqual(self.conn.execute("SELECT ended_at FROM op_pauses").fetchone()[0], yesterday)

    def test_retired_reasons_cant_be_picked_and_unknown_ones_are_refused(self):
        kept = [r for r in floor.reasons(self.conn) if r["label"] != "Meeting"]
        meeting = self.reason("Meeting")
        floor.save_reasons(self.conn, [*kept, {"label": "Coaching", "limit_minutes": 30}])
        labels = [r["label"] for r in floor.reasons(self.conn)]
        self.assertNotIn("Meeting", labels)
        self.assertEqual(labels[-1], "Coaching")
        with self.assertRaises(OperationError):
            operations.set_ready(self.conn, "a1", False, meeting["id"])
        with self.assertRaises(floor.FloorError):
            floor.save_reasons(self.conn, [{"label": "Break"}, {"label": "break"}])


class TargetTests(DeskTestCase):
    def setUp(self):
        super().setUp()
        self.conn.execute("DELETE FROM users")
        for user in ("a1", "a2"):
            self.conn.execute("INSERT INTO users (username, password_hash, created_at, role) VALUES (?, '', ?, 'agent')",
                              (user, iso(datetime.now())))
        self.conn.commit()

    def test_agents_take_the_team_targets_unless_overridden(self):
        floor.save_targets(self.conn, {"team": {"calls": 60, "wins": 3}, "agents": {"a2": {"calls": 40, "wins": ""}},
                                       "workday": {"start": "08:00", "end": "16:00"}})
        self.assertEqual(floor.resolved(self.conn, "a1"), {"calls": 60, "reached": 0, "wins": 3, "desk_minutes": 0})
        self.assertEqual(floor.resolved(self.conn, "a2"), {"calls": 40, "reached": 0, "wins": 3, "desk_minutes": 0})
        self.assertEqual(floor.workday(self.conn), {"start": "08:00", "end": "16:00"})

    def test_progress_and_pace(self):
        floor.save_targets(self.conn, {"team": {"calls": 40, "wins": 4}, "workday": {"start": "09:00", "end": "17:00"}})
        self.assertEqual(floor.pace(self.conn, datetime(2026, 10, 12, 13, 0)), 0.5)
        self.assertEqual(floor.pace(self.conn, datetime(2026, 10, 12, 7, 0)), 0.0)
        self.close(self.serve("a1"), "interested")
        today = operations.today(self.conn, "a1")
        calls = next(p for p in floor.progress(today, floor.resolved(self.conn, "a1"), 0.5) if p["metric"] == "calls")
        self.assertEqual((calls["value"], calls["target"], calls["expected"]), (1, 40, 20.0))
        board = operations.board(self.conn)
        self.assertEqual(next(p for p in board["team_progress"] if p["metric"] == "calls")["target"], 120)

    def test_bad_targets_are_refused(self):
        with self.assertRaises(floor.FloorError):
            floor.save_targets(self.conn, {"team": {"calls": -1}, "workday": {"start": "09:00", "end": "17:00"}})
        with self.assertRaises(floor.FloorError):
            floor.save_targets(self.conn, {"team": {}, "workday": {"start": "17:00", "end": "09:00"}})


class RecordingTests(DeskTestCase):
    def add_recording(self, call_id: str, agent: str, customer: str, when: datetime, analysis: dict | None = None):
        self.conn.execute("INSERT INTO calls (id, type, agent, customer, date_call, duration, analysis) "
                          "VALUES (?, 'OUT', ?, ?, ?, 60, ?)",
                          (call_id, agent, customer, when.strftime("%Y-%m-%d %H:%M:%S"),
                           json.dumps(analysis) if analysis else None))
        self.conn.commit()

    def test_desk_calls_are_linked_to_their_recording(self):
        self.conn.execute("INSERT INTO softphones (username, extension, password, updated_at) VALUES "
                          "('a1', '103', '', '')")
        self.conn.commit()
        op = self.close(self.serve("a1"), "interested")
        started = datetime.fromisoformat(op["call_started_at"])
        self.add_recording("r-other-agent", "105", "22602711", started)
        self.add_recording("r-other-number", "103", "99999999", started)
        self.add_recording("r-too-late", "103", "+21622602711", started + timedelta(minutes=20))
        self.add_recording("r-match", "103", "+21622602711", started + timedelta(seconds=20))
        self.assertEqual(desk_stats.link_recordings(self.conn), 1)
        self.assertEqual(operations.get_row(self.conn, op["id"])["call_id"], "r-match")
        self.assertEqual(desk_stats.link_recordings(self.conn), 0)
        desk = desk_stats.desk_call_for_recording(self.conn, "r-match")
        self.assertEqual((desk["outcome_label"], desk["campaign"]), ("Interested", "New leads"))

    def test_kpis_and_how_outcomes_line_up_with_ai_scores(self):
        def analysis(score, closing):
            return {"call_kind": "sales", "overall_score": score, "outcome": "sale",
                    "scores": {"opening": 6, "closing": closing}}

        results = [("a1", "account_created", 9, 9), ("a1", "not_interested", 5, 3), ("a2", "no_answer", None, None),
                   ("a2", "interested", 6, 4)]
        for i, (user, outcome, score, closing) in enumerate(results):
            op = self.close(self.serve(user), outcome)
            if score:
                self.add_recording(f"r{i}", "100", f"2260271{op['opportunity_id'][1:]}",
                                   datetime.fromisoformat(op["call_started_at"]), analysis(score, closing))
        self.conn.execute("INSERT INTO op_presence (username, day, ready_seconds) VALUES ('a1', ?, 3600)",
                          (datetime.now().date().isoformat(),))
        self.conn.commit()

        k = desk_stats.kpis(self.conn)
        team = k["team"]
        self.assertEqual((team["calls"], team["reached"], team["success"]), (4, 3, 1))
        self.assertEqual(team["contact_rate"], 0.75)
        a1 = next(a for a in k["agents"] if a["username"] == "a1")
        self.assertEqual((a1["calls_per_hour"], a1["success_per_hour"], a1["avg_score"]), (2.0, 1.0, 7.0))
        self.assertEqual(k["days"][0]["calls"], 4)
        mine = desk_stats.kpis(self.conn, username="a2")
        self.assertEqual([a["username"] for a in mine["agents"]], ["a2"])

        found = desk_stats.insights(self.conn)
        self.assertEqual((found["total"], found["linked"], found["rated"]), (4, 3, 3))
        self.assertEqual(found["overall"], {"criterion": "overall_score", "won": 9.0, "other": 5.5, "gap": 3.5})
        self.assertEqual(found["drivers"][0]["criterion"], "closing")
        self.assertEqual(found["drivers"][0]["gap"], 5.5)
        bands = {b["band"]: b for b in found["bands"]}
        self.assertEqual((bands["9-10"]["success_rate"], bands["5-6"]["success_rate"]), (1.0, 0.0))
        won = next(o for o in found["outcomes"] if o["outcome"] == "account_created")
        self.assertEqual((won["avg_score"], won["ai_outcomes"]), (9.0, {"sale": 1}))


class VaultTests(unittest.TestCase):
    def test_secrets_round_trip_and_unknown_tokens_read_as_missing(self):
        secret = vault.encrypt("s3cret")
        self.assertTrue(secret.startswith(vault.PREFIX))
        self.assertNotIn("s3cret", secret)
        self.assertEqual(vault.decrypt(secret), "s3cret")
        self.assertEqual(vault.decrypt("legacy-plain"), "legacy-plain")
        self.assertIsNone(vault.encrypt(None))
        self.assertEqual(vault.encrypt(""), "")
        self.assertIsNone(vault.decrypt(vault.PREFIX + "not-a-token"))

    def test_softphone_passwords_saved_in_clear_are_encrypted_when_the_database_opens(self):
        conn = db.connect()
        conn.execute("DELETE FROM softphones")
        conn.execute("INSERT INTO softphones (username, extension, password, account_password, access_token, "
                     "updated_at) VALUES ('ons', '103', 'sip-pass', 'gv-pass', NULL, '')")
        conn.commit()
        db._ready.clear()  # the migrations run once per process: as if the app restarted after an upgrade
        row = db.connect().execute("SELECT * FROM softphones WHERE username = 'ons'").fetchone()
        self.assertTrue(vault.is_encrypted(row["password"]) and vault.is_encrypted(row["account_password"]))
        self.assertIsNone(row["access_token"])
        self.assertEqual((vault.decrypt(row["password"]), vault.decrypt(row["account_password"])),
                         ("sip-pass", "gv-pass"))


if __name__ == "__main__":
    unittest.main()
