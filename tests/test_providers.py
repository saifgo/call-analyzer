"""The CRM and phone system adapters: choosing one in Settings, adding a new one, and what the app gets from them.

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
for key in ("CRM_PROVIDER", "TELEPHONY_PROVIDER", "CRM_API_KEY", "GOVOICE_COOKIE", "GOVOICE_RECORDINGS_DIR",
            "SOFTPHONE_WS_URL", "SOFTPHONE_DOMAIN", "SOFTPHONE_USER_PREFIX"):
    os.environ.pop(key, None)

import pgtest  # noqa: E402,F401  (before call_analyzer: the test database)
from call_analyzer import crm, db, softphone, telephony  # noqa: E402
from call_analyzer.config import ENV_PATH  # noqa: E402
from call_analyzer.adapters.crm.base import CrmAdapter  # noqa: E402
from call_analyzer.adapters.telephony.base import SessionExpired, TelephonyAdapter  # noqa: E402
from call_analyzer.adapters.telephony.govoice import GoVoiceTelephony  # noqa: E402


class OtherCrm(CrmAdapter):
    """Another CRM, with its own lead stage and contact shapes already translated."""
    name, label, lead_stage = "other", "Other CRM", "open"

    def __init__(self):
        self.searches = []

    def is_configured(self):
        return True

    def find_people(self, key):
        self.searches.append(key)
        return [{"id": "c1", "name": "Amira", "phones": ["+216 22602716"], "opportunities": []}]

    def list_opportunities(self, stage, oldest_first, limit, after=None):
        return [{"id": "d1", "name": "Deal", "stage": stage, "created_at": None,
                 "contact": {"id": "c1", "name": "Amira", "phones": ["22602716"]}}], None


class FakePhoneSystem(TelephonyAdapter):
    name, label = "fakepbx", "Fake PBX"

    def __init__(self, session=True, fail=None):
        self.session, self.fail = session, fail

    def has_session(self):
        return self.session

    def check(self):
        if self.fail:
            raise self.fail
        return 42

    def iter_recordings(self, stop_before=None):
        yield {"id": "r1", "type": "OUT", "caller": "101", "called": "+21622602716", "date_call": "2026-10-16 10:00:00",
               "duration": 65, "size_kb": 512, "filename": "r1.wav", "raw": {"uid": "r1"}}

    def softphone_defaults(self):
        return {"ws_url": "wss://pbx.example.com/ws", "domain": "pbx.example.com", "prefix": "t1_"}


def write_env(test: unittest.TestCase, **values):
    """Save these in Settings for the test. The test modules share one .env (the first one imported sets it)."""
    before = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    ENV_PATH.write_text(before + "".join(f"\n{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
    test.addCleanup(ENV_PATH.write_text, before, encoding="utf-8")


class RegistryTests(unittest.TestCase):
    def tearDown(self):
        crm.forget()

    def test_the_built_in_crm_and_govoice_are_the_defaults(self):
        self.assertEqual((crm.adapter().name, telephony.adapter().name), ("internal", "govoice"))
        self.assertEqual(crm.lead_stage(), "NEW")

    def test_a_registered_crm_is_used_once_chosen_in_settings(self):
        crm.registry.register("other", OtherCrm)
        write_env(self, CRM_PROVIDER="other")
        self.assertIsInstance(crm.adapter(), OtherCrm)
        self.assertEqual(crm.lead_stage(), "open")
        found = crm.lookup("+216 22 602 716")
        self.assertEqual((found["searched"], found["people"][0]["name"]), (True, "Amira"))
        self.assertEqual(crm.adapter().searches, ["22602716"])  # matched on the last 8 digits, whatever the CRM
        crm.lookup("22602716")
        self.assertEqual(len(crm.adapter().searches), 1)  # cached
        self.assertEqual(crm.leads()["stage"], "open")

    def test_an_unknown_provider_says_which_ones_there_are(self):
        write_env(self, CRM_PROVIDER="nope")
        with self.assertRaisesRegex(RuntimeError, r"Unknown CRM 'nope' \(CRM_PROVIDER\).*twenty"):
            crm.adapter()

    def test_leads_handed_out_are_copies(self):
        crm.use(OtherCrm())
        self.addCleanup(crm.use, None)
        first = crm.leads()["leads"][0]
        first["calls"] = 3
        first["contact"]["extra"] = True
        again = crm.leads()["leads"][0]
        self.assertNotIn("calls", again)
        self.assertNotIn("extra", again["contact"])


class TelephonyTests(unittest.TestCase):
    def setUp(self):
        conn = db.connect()
        conn.execute("DELETE FROM calls")
        conn.commit()

    def use(self, phone_system):
        telephony.use(phone_system)
        self.addCleanup(telephony.use, None)

    def test_recordings_are_stored_from_the_adapters_shape(self):
        self.use(FakePhoneSystem())
        conn = db.connect()
        self.assertEqual(db.upsert_recordings(conn, list(telephony.iter_recordings())), 1)
        row = conn.execute("SELECT * FROM calls WHERE id = 'r1'").fetchone()
        self.assertEqual((row["agent"], row["customer"], row["duration"], row["size_kb"], row["raw"]),
                         ("101", "+21622602716", 65, 512, '{"uid": "r1"}'))

    def test_connection_status(self):
        self.use(FakePhoneSystem())
        self.assertEqual(telephony.check_connection()["message"], "Connected · 42 recordings")
        self.use(FakePhoneSystem(session=False))
        self.assertEqual(telephony.check_connection()["message"], "Not connected to Fake PBX yet")
        self.use(FakePhoneSystem(fail=SessionExpired("gone")))
        status = telephony.check_connection()
        self.assertEqual((status["connected"], status["message"]), (False, "Fake PBX session expired"))
        self.use(FakePhoneSystem(fail=OSError("no route")))
        self.assertIsNone(telephony.check_connection()["connected"])  # not a login problem

    def test_softphone_takes_the_adapters_defaults_unless_set(self):
        self.use(FakePhoneSystem())
        conf = softphone.settings()
        self.assertEqual((conf["ws_url"], conf["domain"], conf["prefix"]),
                         ("wss://pbx.example.com/ws", "pbx.example.com", "t1_"))
        write_env(self, SOFTPHONE_DOMAIN="sip.example.com")
        self.assertEqual(softphone.settings()["domain"], "sip.example.com")

    def test_a_phone_system_without_sip_sign_ins_says_so(self):
        self.use(FakePhoneSystem())
        with self.assertRaisesRegex(softphone.FetchError, "Fake PBX can't give SIP sign-ins"):
            softphone.fetch_sip_login("user", "pw")


class GoVoiceTests(unittest.TestCase):
    def test_govoice_rows_become_recordings(self):
        row = {"id": "77", "type": "IN", "caller": "+21622602716", "called": "100", "date_call": "2026-10-16 09:00:00",
               "duree": "31", "size": "120", "filename": "a.mp3"}

        class Client:
            def iter_recordings(self, perpage, stop_before):
                yield row

        govoice = GoVoiceTelephony()
        govoice._connect = lambda: Client()
        rec = next(govoice.iter_recordings())
        self.assertEqual((rec["duration"], rec["size_kb"], rec["raw"]), (31, 120, row))
        self.assertEqual(db.split_parties(rec), ("100", "+21622602716"))

    def test_no_saved_cookie_means_no_session(self):
        self.assertFalse(GoVoiceTelephony().has_session())
        with self.assertRaises(SessionExpired):
            GoVoiceTelephony().check()

    def test_recording_link_and_sip_prefix_follow_the_recordings_folder(self):
        write_env(self, GOVOICE_BASE_URL="https://pbx.example.com:4444", GOVOICE_RECORDINGS_DIR="govoice_enreg_1759")
        govoice = GoVoiceTelephony()
        self.assertEqual(govoice.recording_url("a.mp3"), "https://pbx.example.com:4444/govoice_enreg_1759/a.mp3")
        self.assertEqual(govoice.softphone_defaults()["prefix"], "1759_")


if __name__ == "__main__":
    unittest.main()
