"""Build log 56: the offline proof - what counts as isolated, and what it may claim.

Andreas's DIANA-readiness checklist, item 1: a "written, repeatable test
protocol/log - something a DIANA test centre could rerun independently".
"""
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "training"))
import offline_proof as op  # noqa: E402


def snap(link=False, route=False, bt_blocked=True, wifi_blocked=True, tx=100, sockets=()):
    return {"at": "2026-10-04T03:00:00+0200", "mono": 1.0,
            "interfaces": {"eth0": {"carrier": link, "operstate": "up" if link else "down",
                                    "tx_packets": tx, "rx_packets": 5},
                           "wlan0": {"carrier": False, "operstate": "down",
                                     "tx_packets": 0, "rx_packets": 0}},
            "radios": [{"name": "hci0", "type": "bluetooth", "blocked": bt_blocked},
                       {"name": "phy0", "type": "wlan", "blocked": wifi_blocked}],
            "default_routes": ["default via 192.168.1.1 dev eth0"] if route else [],
            "off_unit_sockets": list(sockets), "drops": {"output": 0, "input": 0}}


GOOD = {"turns": 20, "failed": 0, "answered": 19}


class WhatCountsAsIsolated(unittest.TestCase):

    def test_no_link_no_route_every_radio_blocked(self):
        self.assertEqual(op.isolated(snap()), (True, []))

    def test_a_cable_is_not_isolated(self):
        ok, why = op.isolated(snap(link=True, route=True))
        self.assertFalse(ok)
        self.assertEqual(why, ["eth0 has a link", "a default route exists"])

    def test_an_unblocked_radio_is_not_isolated(self):
        # Lyra, 4 Oct 2026: Wi-Fi blocked, Bluetooth not - its service was
        # disabled, which is not the radio being off.
        ok, why = op.isolated(snap(bt_blocked=False))
        self.assertFalse(ok)
        self.assertEqual(why, ["radio hci0 (bluetooth) is not blocked"])

    def test_a_route_left_behind_is_not_isolated(self):
        self.assertFalse(op.isolated(snap(route=True))[0])


class WhatItMayClaim(unittest.TestCase):

    def test_passed(self):
        v = op.verdict([snap(), snap(), snap()], GOOD, attempts=0)
        self.assertTrue(v["passed"])
        self.assertEqual(v["packets_sent"], {"eth0": 0, "wlan0": 0})

    def test_one_sample_with_a_link_and_it_has_not_passed(self):
        v = op.verdict([snap(), snap(link=True), snap()], GOOD, 0)
        self.assertFalse(v["passed"])
        self.assertEqual(len(v["isolation_broken"]), 1)

    def test_one_packet_sent_and_it_has_not_passed(self):
        v = op.verdict([snap(tx=100), snap(tx=101)], GOOD, 0)
        self.assertFalse(v["passed"])
        self.assertEqual(v["packets_sent"]["eth0"], 1)

    def test_a_failed_question_and_it_has_not_passed(self):
        self.assertFalse(op.verdict([snap(), snap()], dict(GOOD, failed=1), 0)["passed"])

    def test_no_question_asked_and_it_has_not_passed(self):
        self.assertFalse(op.verdict([snap(), snap()], {"turns": 0, "failed": 0, "answered": 0}, 0)["passed"])
        self.assertFalse(op.verdict([], GOOD, 0)["passed"])

    def test_a_leftover_socket_is_listed_but_packets_are_the_claim(self):
        v = op.verdict([snap(sockets=["tcp ESTAB 0 0 192.168.1.51:22 192.168.1.160:5"]), snap()],
                       GOOD, 0)
        self.assertTrue(v["passed"])
        self.assertEqual(len(v["off_unit_sockets"]), 1)

    def test_attempts_the_firewall_stopped_are_counted_not_failed(self):
        v = op.verdict([snap(), snap()], GOOD, attempts=3)
        self.assertTrue(v["passed"])
        self.assertEqual(v["attempts_dropped"], 3)

    def test_the_report_says_what_passed_means_and_how_to_rerun(self):
        v = op.verdict([snap(), snap()], GOOD, 0)
        ident = {"companion": "Lyra", "hostname": "aetherseed", "kernel": "k", "app_digest": "a",
                 "firewall_sha256": "f", "model_files": ["m (1 bytes)"]}
        text = op.report_text({"started": "t0", "isolated_at": "t1", "soak_start": "t2",
                               "soak_end": "t3", "samples": 2}, ident,
                              snap(link=True, route=True), v, "the soak's own report")
        self.assertIn("RESULT: PASSED", text)
        self.assertIn("link yes", text)
        self.assertIn("questions asked 20, failed 0", text)
        self.assertIn("sudo bash /opt/aetherseed/training/run-offline-proof.sh", text)
        self.assertIn("nothing about voice", text)
        self.assertIn("the soak's own report", text)
        bad = op.report_text({"started": "t0", "samples": 0}, ident, snap(link=True),
                             op.verdict([], {"turns": 0, "failed": 0, "answered": 0}, 0), "")
        self.assertIn("RESULT: NOT PASSED", bad)
        self.assertIn("isolated from  never", bad)


class TheWholeRun(unittest.TestCase):
    """main(), with the unit's state and the soak stood in for - the code
    itself has no switch that fakes its conditions."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="offline-")
        self.saved = (op.snapshot, op.identity, op.SERVICE_USER, op.subprocess.Popen,
                      op.time.sleep, op.sh)
        op.identity = lambda: {"companion": "Lyra", "hostname": "h", "kernel": "k",
                               "app_digest": "a", "firewall_sha256": "f", "model_files": []}
        op.SERVICE_USER = getpass.getuser()
        op.time.sleep = lambda s: None
        op.sh = lambda cmd, timeout=20: ""

    def tearDown(self):
        (op.snapshot, op.identity, op.SERVICE_USER, op.subprocess.Popen,
         op.time.sleep, op.sh) = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def _fake_soak(self):
        test = self

        class Soak:
            def __init__(self, cmd, **kw):
                test.cmd = cmd
                d = cmd[cmd.index("--dir") + 1]
                with open(os.path.join(d, "ecosoak.jsonl"), "w") as f:
                    f.write(json.dumps({"kind": "status"}) + "\n")
                    for i in range(3):
                        f.write(json.dumps({"kind": "probe", "turn": i + 1, "failures": [],
                                            "score": {"answered": True}}) + "\n")
                with open(os.path.join(d, "report.txt"), "w") as f:
                    f.write("Ecosystem soak - stand-in\n")
                self.polls = 0

            def poll(self):
                self.polls += 1
                return None if self.polls < 3 else 0
        return Soak

    def test_cable_in_then_pulled_then_back(self):
        seq = [snap(link=True, route=True)] * 2 + [snap()] * 8 + [snap(link=True, route=True)]
        it = iter(seq)
        op.snapshot = lambda: dict(next(it))
        op.subprocess.Popen = self._fake_soak()
        self.assertEqual(op.main(["--dir", self.dir, "--minutes", "1", "--wait", "1"]), 0)
        text = open(os.path.join(self.dir, "report.txt")).read()
        self.assertIn("RESULT: PASSED", text)
        self.assertIn("questions asked 3, failed 0", text)
        self.assertNotIn("not while this was written", text)       # the link came back
        self.assertEqual(self.cmd[:3], ["runuser", "-u", getpass.getuser()])
        self.assertIn("--copy-from", self.cmd)                      # a copy, never her memory
        v = json.load(open(os.path.join(self.dir, "verdict.json")))
        self.assertTrue(v["verdict"]["passed"])
        phases = [json.loads(l)["phase"] for l in open(os.path.join(self.dir, "samples.jsonl"))]
        self.assertEqual(phases[0], "before")
        self.assertEqual(phases[-1], "after")
        self.assertGreaterEqual(phases.count("during"), 3)
        sums = open(os.path.join(self.dir, "SHA256SUMS")).read()
        self.assertIn("soak/ecosoak.jsonl", sums)

    def test_the_cable_is_never_pulled(self):
        op.snapshot = lambda: snap(link=True, route=True)
        ticks = iter(range(0, 100000, 30))
        saved, op.time.monotonic = op.time.monotonic, lambda: next(ticks)
        try:
            self.assertEqual(op.main(["--dir", self.dir, "--minutes", "1", "--wait", "1"]), 0)
        finally:
            op.time.monotonic = saved
        text = open(os.path.join(self.dir, "report.txt")).read()
        self.assertIn("RESULT: NOT PASSED", text)
        self.assertIn("isolated from  never", text)


class TheRunner(unittest.TestCase):

    def test_it_parses_and_changes_nothing_on_the_unit(self):
        sh = os.path.join(HERE, "training", "run-offline-proof.sh")
        self.assertEqual(subprocess.run(["bash", "-n", sh]).returncode, 0)
        with open(os.path.join(HERE, "training", "offline_proof.py"), encoding="utf-8") as f:
            code = f.read()
        # a proof that arranges its own conditions proves less
        for word in ("rfkill block", "ip link set", "nmcli", "nft insert", "nft add",
                     "nft delete", "nft flush"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
