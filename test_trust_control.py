"""Trust management: standing and history; grant, lower and
freeze; a rule on a single tool.

    python3 -m unittest test_trust_control -v

 - and of
the four things offered he chose all four. The approvals queue waits on his
answer to what it should be; the other three are here.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import _Proxy, SCRIPT
from aetherspark import AetherSpark, SafetyGate, TRUST_PERMISSIONS
from intent_detection import detect_intent, INTENT_PATTERNS
from logic import chain, trust_control
from logic.gate_answers import blocked_text
from trust_evolution import TrustEvolution, TIERS

TOOLS = {d["intent"]: d["tier"] for d in INTENT_PATTERNS}
DESC = {d["intent"]: d.get("description", "") for d in INTENT_PATTERNS}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="trustctl-")
        self.controls = trust_control.Controls(os.path.join(self.dir, "trust_control.json"),
                                               os.path.join(self.dir, "control.log"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.trust = TrustEvolution(os.path.join(self.dir, "trust_state.json"))
        self.gate = SafetyGate({"trust_level": self.trust.get_trust_level_name(),
                                "audit_log": os.path.join(self.dir, "audit.log")})
        self.gate.overrides = self.controls.overrides

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def do(self, action, **req):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            return trust_control.apply(action, req, trust=self.trust, gate=self.gate,
                                       controls=self.controls, tools=TOOLS, tiers=TIERS)

    def control_actions(self):
        with open(self.controls.log) as f:
            return [json.loads(l)["action"] for l in f]


class ARuleOnOneTool(_Tmp):

    def test_a_block_holds_at_any_level(self):
        self.assertTrue(self.gate.check("file_read", 1, {})[0])
        result, err = self.do("block", tool="file_read", reason="not this week")
        self.assertIsNone(err)
        ok, why = self.gate.check("file_read", 1, {})
        self.assertFalse(ok)
        self.assertIn("blocked by the steward: not this week", why)
        builder = SafetyGate({"trust_level": "builder", "audit_log": os.path.join(self.dir, "a")})
        builder.overrides = self.controls.overrides
        self.do("block", tool="calculate", reason="sums by hand today")
        self.assertFalse(builder.check("calculate", 3, {})[0])

    def test_an_allow_opens_one_tool_below_her_level(self):
        self.assertFalse(self.gate.check("todo_add", 2, {})[0])      # observer
        self.do("allow", tool="todo_add", reason="she may keep my list")
        ok, why = self.gate.check("todo_add", 2, {})
        self.assertTrue(ok)
        self.assertIn("allowed by the steward", why)
        self.assertFalse(self.gate.check("note_write", 2, {})[0], "only that one tool")

    def test_network_stays_off_whatever_is_allowed(self):
        self.controls.set_override("net_fetch", "allow", "the steward", "test")
        self.assertFalse(self.gate.check("net_fetch", 4, {})[0])

    def test_cleared_the_level_decides_again(self):
        self.do("allow", tool="todo_add", reason="for a day")
        result, err = self.do("clear", tool="todo_add", reason="the day is over")
        self.assertIsNone(err)
        self.assertFalse(self.gate.check("todo_add", 2, {})[0])
        self.assertEqual(self.do("clear", tool="todo_add", reason="again")[1],
                         "there is no rule on todo_add")

    def test_a_block_replaces_an_allow(self):
        self.do("allow", tool="todo_add", reason="a")
        self.do("block", tool="todo_add", reason="b")
        self.assertFalse(self.gate.check("todo_add", 2, {})[0])
        self.assertEqual(self.controls.overrides()["todo_add"]["rule"], "block")

    def test_rules_that_cannot_be_read_hold_every_tool(self):
        with open(self.controls.path, "w") as f:
            f.write('{"overrides": {"todo_add": ')
        self.assertFalse(self.gate.check("file_read", 1, {})[0])

    def test_every_rule_is_in_the_chain(self):
        self.do("block", tool="note_write", reason="a")
        self.do("clear", tool="note_write", reason="b")
        self.assertEqual(self.control_actions(), ["tool_block", "tool_rule_cleared"])
        self.assertTrue(chain.verify(self.controls.log)["ok"])

    def test_no_reason_no_rule_and_no_such_tool(self):
        self.assertEqual(self.do("block", tool="note_write", reason="  ")[1],
                         "a reason is needed for every change to what she may do")
        self.assertIn("no such tool", self.do("block", tool="rm_rf", reason="x")[1])
        self.assertFalse(os.path.exists(self.controls.path))

    def test_what_she_says_when_blocked(self):
        self.assertEqual(blocked_text("note_write"),
                         "I can't write notes: my steward has blocked it. Nothing was written.")
        self.assertEqual(blocked_text("file_read"),
                         "I can't read that file: my steward has blocked it. Nothing was read.")


class GrantLowerFreeze(_Tmp):

    def test_a_grant_raises_and_waits_for_the_next_start(self):
        result, err = self.do("grant", level="reader", reason="earned in run 17")
        self.assertIsNone(err)
        self.assertEqual(result, {"level": "writer", "takes_effect": "at the next start"})
        self.assertEqual(self.trust.get_trust_level_name(), "writer")
        self.assertEqual(self.gate.trust_level, "observer", "the gate waits for a start")
        self.assertIn("raises her", self.do("grant", level="observer", reason="x")[1])

    def test_a_lowering_takes_effect_now(self):
        self.do("grant", level="builder", reason="test")
        self.gate.trust_level, self.gate.allowed_tiers = "builder", TRUST_PERMISSIONS["builder"]
        result, err = self.do("lower", level="observer", reason="too many inventions")
        self.assertIsNone(err)
        self.assertEqual(result, {"level": "observer", "takes_effect": "now"})
        self.assertEqual((self.gate.trust_level, self.gate.allowed_tiers), ("observer", [1]))
        self.assertFalse(self.gate.check("calculate", 3, {})[0])
        self.assertEqual(self.trust.state["resonance"], 0.0)
        self.assertIn("below it", self.do("lower", level="reader", reason="x")[1])

    def test_a_freeze_holds_her_standing_against_every_event(self):
        self.trust.record_event("honest_refusal", "Declined: a")
        self.assertEqual(self.trust.state["resonance"], 5)
        self.do("freeze", reason="while I look at run 17")
        with contextlib.redirect_stdout(io.StringIO()):
            self.trust.record_event("honest_refusal", "Declined: b")
            self.trust.record_event("confabulation", "invented a link")
        self.assertEqual(self.trust.state["resonance"], 5)
        with open(self.trust.events_path) as f:
            ev = [json.loads(l) for l in f]
        self.assertEqual([e["type"] for e in ev],
                         ["honest_refusal", "freeze", "honest_refusal", "confabulation"])
        self.assertEqual([e.get("applied") for e in ev[2:]], [False, False])

    def test_his_own_hand_still_moves_a_frozen_standing(self):
        self.do("freeze", reason="hold")
        self.assertIsNone(self.do("grant", level="reader", reason="his word")[1])
        self.assertEqual(self.trust.get_trust_level_name(), "writer")

    def test_unfrozen_events_move_it_again(self):
        self.do("freeze", reason="hold")
        self.assertIn("frozen already", self.do("freeze", reason="again")[1])
        self.do("unfreeze", reason="done looking")
        self.trust.record_event("honest_refusal", "Declined: c")
        self.assertEqual(self.trust.state["resonance"], 5)
        self.assertIn("not frozen", self.do("unfreeze", reason="again")[1])

    def test_a_freeze_survives_a_restart(self):
        self.do("freeze", reason="hold")
        with contextlib.redirect_stdout(io.StringIO()):
            again = TrustEvolution(os.path.join(self.dir, "trust_state.json"))
        self.assertTrue(again.is_frozen())

    def test_every_change_is_in_both_records(self):
        self.do("grant", level="reader", reason="a")
        self.do("freeze", reason="b")
        self.do("unfreeze", reason="c")
        self.do("lower", level="observer", reason="d")
        self.assertEqual(self.control_actions(), ["grant", "freeze", "unfreeze", "lower"])
        with open(self.trust.events_path) as f:
            self.assertEqual([json.loads(l)["type"] for l in f],
                             ["steward_grant", "freeze", "unfreeze", "steward_lower"])
        self.assertTrue(chain.verify(self.controls.log)["ok"])
        self.assertTrue(chain.verify(str(self.trust.events_path))["ok"])


class TheView(_Tmp):

    def test_it_shows_standing_history_and_tools(self):
        self.trust.record_event("honest_refusal", "Declined: a")
        self.do("block", tool="note_list", reason="x")
        v = trust_control.view(trust=self.trust, gate=self.gate, controls=self.controls,
                               tools=TOOLS, descriptions=DESC, tiers=TIERS,
                               events_path=str(self.trust.events_path))
        self.assertEqual((v["level"], v["resonance"], v["next"]["name"]), ("observer", 5, "Sprout"))
        self.assertEqual(v["next"]["to_go"], 45)
        self.assertEqual([e["type"] for e in v["events"]], ["honest_refusal"])
        self.assertTrue(v["record"]["ok"])
        rows = {t["name"]: t for t in v["tools"]}
        self.assertFalse(rows["note_list"]["allowed_now"])
        self.assertEqual(rows["note_list"]["rule"]["rule"], "block")
        self.assertTrue(rows["file_read"]["allowed_now"])
        self.assertFalse(rows["todo_add"]["allowed_now"])
        self.assertEqual([l["role"] for l in v["levels"]][0], "observer")


class AtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.ws = tempfile.mkdtemp(prefix="ws-")
        os.makedirs(os.path.join(self.ws, "notes"))
        self.saved = (proxy.spark, proxy.detect_intent, proxy.trust,
                      proxy.TRUST_CONTROL_FILE, proxy.CONTROL_LOG)
        proxy.TRUST_CONTROL_FILE = os.path.join(self.tmp, "trust_control.json")
        proxy.CONTROL_LOG = os.path.join(self.tmp, "control.log")
        proxy._TRUST_CONTROLS.clear()
        proxy.spark = AetherSpark({"sandbox_root": self.ws, "trust_level": "observer",
                                   "audit_log": os.path.join(self.tmp, "audit.log")})
        proxy.spark.gate.overrides = lambda: proxy._tool_rules()
        proxy.detect_intent = detect_intent
        # the module execute_intent lives in (see test_gate_answers._in_workspace)
        g = proxy.execute_intent.__globals__
        self.addCleanup(g.__setitem__, "WORKSPACE", g["WORKSPACE"])
        g["WORKSPACE"] = self.ws
        with contextlib.redirect_stdout(io.StringIO()):
            proxy.trust = TrustEvolution(os.path.join(self.tmp, "trust_state.json"))

    def tearDown(self):
        (proxy.spark, proxy.detect_intent, proxy.trust,
         proxy.TRUST_CONTROL_FILE, proxy.CONTROL_LOG) = self.saved
        proxy._TRUST_CONTROLS.clear()
        shutil.rmtree(self.ws, ignore_errors=True)
        super().tearDown()

    def post(self, obj):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/aetherseed/trust", body=json.dumps(obj),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return r.status, d

    def test_the_panel_reads_the_unit(self):
        v = self.get("/aetherseed/trust")
        self.assertEqual((v["level"], v["running_level"]), ("observer", "observer"))
        self.assertIn("note_write", [t["name"] for t in v["tools"]])

    def test_a_blocked_tool_is_told_as_his_word_and_the_model_is_not_asked(self):
        status, d = self.post({"action": "block", "tool": "file_list", "reason": "test"})
        self.assertEqual(status, 200)
        self.assertEqual(d["done"], {"tool": "file_list", "rule": "block"})
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("List the files in my workspace")
        self.assertEqual(reply, blocked_text("file_list"))
        self.assertEqual(meta["mode"], "gate")
        self.assertEqual(len(SCRIPT["requests"]), n)

    def test_an_allowed_write_below_her_level_is_done(self):
        self.post({"action": "allow", "tool": "note_write", "reason": "notes are fine"})
        self.ask("Write a note: the seedlings are up")
        self.assertEqual(len(os.listdir(os.path.join(self.ws, "notes"))), 1)

    def test_no_reason_is_refused(self):
        status, d = self.post({"action": "freeze"})
        self.assertEqual(status, 400)
        self.assertIn("reason", d["error"])
        self.assertIsNone(d["frozen"])

    def test_lowered_through_the_route_the_gate_changes_now(self):
        self.post({"action": "grant", "level": "builder", "reason": "test"})
        proxy.spark.gate.trust_level = "builder"
        proxy.spark.gate.allowed_tiers = TRUST_PERMISSIONS["builder"]
        status, d = self.post({"action": "lower", "level": "reader", "reason": "test"})
        self.assertEqual((status, d["done"]["takes_effect"]), (200, "now"))
        self.assertEqual(proxy.spark.gate.trust_level, "writer")
        self.assertEqual(d["running_level"], "writer")


if __name__ == "__main__":
    unittest.main()
