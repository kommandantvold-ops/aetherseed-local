"""No unit in the build depends on a person's account (build log step 45).

Andreas, 28 Sep 2026: "The llama stable shouldnt be dependent on my username
if its on git for pilots". Until step 45 the kiosk ran as andreas - his home
and UID 1000 written into the unit - and the keepalive ran as andreas from
his home. A pilot unit would have needed an account with his name, with
passwordless sudo, behind the screen.

These read the unit files as shipped and fail if one runs as, or names the
home or runtime directory of, anyone but the build's own two accounts.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES = os.path.join(HERE, "services")
ACCOUNTS = {"aetherseed", "aetherseed-kiosk"}      # created at install


def units():
    for name in sorted(os.listdir(SERVICES)):
        if name.endswith((".service", ".path")):
            with open(os.path.join(SERVICES, name), encoding="utf-8") as f:
                yield name, f.read()


def directives(text):
    """Every line that is not a comment - continuation lines included."""
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


def unit(name):
    with open(os.path.join(SERVICES, name), encoding="utf-8") as f:
        return directives(f.read())


class TestNoPersonInTheBuild(unittest.TestCase):

    def test_every_account_a_unit_runs_as_is_the_builds_own(self):
        seen = 0
        for name, text in units():
            for line in directives(text):
                m = re.match(r"(User|Group)=(\S+)$", line)
                if m:
                    seen += 1
                    self.assertIn(m.group(2), ACCOUNTS, "%s: %s" % (name, line))
        self.assertGreater(seen, 0)

    def test_no_unit_names_a_home_or_a_uid(self):
        for name, text in units():
            for line in directives(text):
                self.assertNotRegex(line, r"/home/", "%s: %s" % (name, line))
                self.assertNotRegex(line, r"/run/user/\d", "%s: %s" % (name, line))
                self.assertNotRegex(line, r"\bandreas\b", "%s: %s" % (name, line))

    def test_the_browser_waits_for_the_page_it_shows(self):
        # build log 53: started in the same second as the console server, the
        # browser asked too early and stayed on a blank page.
        d = unit("aetherseed-kiosk.service")
        text = " ".join(d)
        pre = text.index("ExecStartPre=/usr/bin/curl")
        self.assertLess(pre, text.index("ExecStart=/usr/bin/labwc"))
        wait = text[pre:text.index("ExecStart=/usr/bin/labwc")]
        self.assertIn("http://127.0.0.1:2077/", wait)
        self.assertIn("--retry-connrefused", wait)
        self.assertIn("--fail", wait)
        self.assertIn("--app=http://127.0.0.1:2077/", text)   # the same page
        self.assertIn("Restart=always", d)

    def test_the_kiosk_runs_as_its_own_account_with_its_own_profile(self):
        d = unit("aetherseed-kiosk.service")
        self.assertIn("User=aetherseed-kiosk", d)
        self.assertIn("PAMName=login", d)          # XDG_RUNTIME_DIR comes from here
        self.assertIn("RuntimeDirectory=aetherseed-kiosk", d)
        self.assertTrue(any("--user-data-dir=/run/aetherseed-kiosk/" in l for l in d))
        self.assertFalse(any(l.startswith("Environment=HOME=") for l in d))
        self.assertFalse(any(l.startswith("Environment=XDG_RUNTIME_DIR=") for l in d))

    def test_the_keepalive_runs_as_the_service_account_from_the_application(self):
        d = unit("aetherseed-keepalive.service")
        self.assertIn("User=aetherseed", d)
        self.assertIn("SupplementaryGroups=video", d)     # vcgencmd: /dev/vcio_gencmd
        self.assertIn("StateDirectory=aetherseed-keepalive", d)
        self.assertIn("Environment=KEEPALIVE_DIR=/var/lib/aetherseed-keepalive", d)
        self.assertIn("ExecStart=/usr/bin/python3 /opt/aetherseed/tools/keepalive.py", d)
        self.assertTrue(os.path.isfile(os.path.join(HERE, "tools", "keepalive.py")))
        self.assertTrue(os.path.isfile(os.path.join(HERE, "tools", "power.py")))


if __name__ == "__main__":
    unittest.main()
