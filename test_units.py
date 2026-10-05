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
        # and for the network to settle first: a load cut off by the address
        # arriving left the blank page, 3 boots of 3. Failing must not stop
        # the screen ("-"), and it waits for start-up, not for a connection.
        net = text.index("ExecStartPre=-/usr/bin/nm-online -s -q")
        self.assertLess(net, pre)
        self.assertIn("Restart=always", d)

    def test_the_screen_is_restarted_when_the_console_is_not_on_it(self):
        # build log 53: now, kiosk since, console server since, last poll -> restart?
        import subprocess
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "kiosk_watch.sh")
        self.assertEqual(subprocess.run(["bash", "-n", sh]).returncode, 0)
        cases = (((1000, 0, 900, 0), 0),       # the screen is not running
                 ((1000, 950, 0, 0), 0),       # no console server to show
                 ((1000, 950, 900, 0), 0),     # the browser has only just started
                 ((1000, 800, 800, 0), 1),     # up 200 s and never polled: the blank page
                 ((1000, 800, 800, 995), 0),   # polling
                 ((1000, 800, 800, 905), 1),   # stopped polling 95 s ago
                 ((1000, 100, 990, 50), 0),    # the console server was just restarted
                 ((1000, 100, 100, 911), 0))   # 89 s: not yet
        for args, want in cases:
            with self.subTest(args=args):
                r = subprocess.run(["bash", sh, "--decide"] + [str(a) for a in args])
                self.assertEqual(r.returncode, want)
        text = open(sh).read()
        self.assertEqual(text.count("systemctl restart"), 1)
        self.assertNotIn("rm ", text)

    def test_the_watch_unit_runs_the_installed_script_and_nothing_else(self):
        d = unit("aetherseed-kiosk-watch.service")
        self.assertIn("ExecStart=/bin/bash /opt/aetherseed/tools/kiosk_watch.sh", d)
        self.assertIn("Restart=always", d)
        self.assertIn("WantedBy=multi-user.target", d)
        self.assertFalse(any(l.startswith("User=") for l in d))   # root: it restarts a unit

    def test_the_scale_of_the_screen_is_the_units_own(self):
        # build log 63: Stella's monitor wants 1.5, Lyra's television 3. One
        # unit file for every unit; a unit that was told nothing runs at 3.
        d = unit("aetherseed-kiosk.service")
        self.assertIn("Environment=AETHERSEED_SCALE=3", d)
        self.assertIn("EnvironmentFile=-/etc/aetherseed/kiosk.env", d)     # "-": it may be absent
        self.assertLess(d.index("Environment=AETHERSEED_SCALE=3"),
                        d.index("EnvironmentFile=-/etc/aetherseed/kiosk.env"))   # the file wins
        flags = [l for l in d if "--force-device-scale-factor" in l and not l.startswith("#")]
        self.assertEqual([l.strip() for l in flags],
                         ["--force-device-scale-factor=${AETHERSEED_SCALE} \\"])
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "cartridge.sh")
        with open(sh, encoding="utf-8") as f:
            self.assertIn("emit kiosk.scale", f.read())

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


def chain(rules, name):
    """The directives of one chain of services/nftables.conf."""
    i = rules.index("chain %s {" % name)
    return rules[i + 1:rules.index("}", i)]


class TheUnitsOwnWifi(unittest.TestCase):
    """Build log 54: a phone on the unit's own Wi-Fi is a second screen.

    The console unit and the firewall are two halves of one line: the console
    listens on every address, and the firewall names who reaches it.
    """

    def setUp(self):
        with open(os.path.join(SERVICES, "nftables.conf"), encoding="utf-8") as f:
            self.rules = directives(f.read())

    def test_the_console_listens_beyond_loopback(self):
        d = unit("aetherseed-gui.service")
        self.assertIn("Environment=AETHERSEED_GUI_BIND=0.0.0.0", d)
        self.assertIn("Environment=AETHERSEED_BACKEND=http://127.0.0.1:8001", d)
        # the proxy and the model stay where they were
        self.assertFalse(any("0.0.0.0" in l for l in unit("aetherseed-proxy.service")))
        self.assertFalse(any("0.0.0.0" in l for l in unit("hailo-ollama.service")))

    def test_the_console_is_admitted_from_the_units_wifi_and_nowhere_else(self):
        port = [l for l in self.rules if "2077" in l]
        self.assertEqual(port, ['iifname "wlan0" tcp dport 2077 accept'])
        dhcp = [l for l in chain(self.rules, "input") if "dport 67" in l]
        self.assertEqual(dhcp, ['iifname "wlan0" udp dport 67 accept'])
        # everything admitted, line by line: a new one is added here on purpose
        accepts = [l for l in chain(self.rules, "input") if l.endswith("accept")]
        self.assertEqual(accepts, [
            'iif "lo" accept',
            "ct state established,related accept",
            "meta l4proto icmpv6 accept",
            "meta l4proto icmp accept",
            "udp dport 68 accept",
            "tcp dport 22 ip saddr @lan4 accept",
            "tcp dport 22 ip6 saddr @lan6 accept",
            'iifname "wlan0" udp dport 67 accept',
            'iifname "wlan0" tcp dport 2077 accept',
        ])
        self.assertFalse(any("dport 53" in l for l in self.rules))   # no name service

    def test_nothing_passes_through_the_unit(self):
        # NetworkManager's shared mode switches forwarding on; this is what
        # keeps a phone on the unit's Wi-Fi out of the cable network.
        self.assertEqual(chain(self.rules, "forward"),
                         ["type filter hook forward priority filter; policy drop;"])
        self.assertIn("type filter hook input priority filter; policy drop;", self.rules)

    def test_the_hotspot_tool_checks_what_it_is_given(self):
        import subprocess
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "hotspot.sh")
        self.assertEqual(subprocess.run(["bash", "-n", sh]).returncode, 0)

        def check(name, key):
            return subprocess.run(["bash", sh, "--check", name], input=key + "\n",
                                  text=True, capture_output=True).returncode
        self.assertEqual(check("Stella", "eight888"), 0)
        self.assertEqual(check("My Companion", "x" * 63), 0)
        for name, key in (("", "eight888"), ("x" * 33, "eight888"),
                          ("Stella", "seven77"), ("Stella", "x" * 64),
                          ('St"ella', "eight888"), ("St\\ella", "eight888"),
                          (" Stella", "eight888"), ("Stélla", "eight888"),
                          ("Stella", "eight88\u00e9"), ("Stella", "")):
            with self.subTest(name=name, key=len(key)):
                self.assertEqual(check(name, key), 2)

    def test_the_passkey_is_nowhere_but_the_profile(self):
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "hotspot.sh")
        text = open(sh, encoding="utf-8").read()
        self.assertEqual(text.count('wifi-sec.psk "$key"'), 1)
        self.assertNotIn("echo \"$key", text)
        self.assertNotIn("tee", text)
        # wlan0 only, WPA2 only, and it does not touch the firewall itself
        self.assertIn("wifi-sec.proto rsn", text)
        self.assertNotIn("nft ", text)


class ItsWifiOnlyWhileNoCableIsLinked(unittest.TestCase):
    """Build log 60. Andreas, 4 Oct 2026: "I want the wifi update, but with
    only transmission when lan is disconnected."

    tools/hotspot.sh is run here with a NetworkManager made of files: what it
    would switch is recorded, and nothing is switched.
    """

    FAKE_NMCLI = r'''#!/bin/bash
echo "nmcli $*" >> "$LOG"
case "$*" in
  "-t -f NAME connection show") [ -e "$STATE/profile" ] && echo aetherseed-hotspot ;;
  "-t -f NAME connection show --active") [ -e "$STATE/up" ] && echo aetherseed-hotspot ;;
  "radio wifi") [ -e "$STATE/radio" ] && echo enabled || echo disabled ;;
  "radio wifi on") touch "$STATE/radio" ;;
  "radio wifi off") rm -f "$STATE/radio" ;;
  "connection up aetherseed-hotspot") [ -e "$STATE/radio" ] && touch "$STATE/up" || exit 4 ;;
  "connection down aetherseed-hotspot") rm -f "$STATE/up" ;;
esac
exit 0
'''

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="hotspot-")
        self.bin = os.path.join(self.tmp, "bin")
        self.state = os.path.join(self.tmp, "state")
        self.net = os.path.join(self.tmp, "net")
        for d in (self.bin, self.state):
            os.makedirs(d)
        for name, body in (("nmcli", self.FAKE_NMCLI), ("id", "#!/bin/bash\necho 0\n"),
                           ("sleep", "#!/bin/bash\nexit 0\n")):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        # a wired port, the radio, the loopback - as the kernel shows them
        self._port("eth0", kind="1", carrier="1", device=True)
        self._port("wlan0", kind="1", carrier="1", device=True, wireless=True)
        self._port("lo", kind="772", carrier="1", device=False)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _port(self, name, kind, carrier, device, wireless=False):
        d = os.path.join(self.net, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "type"), "w") as f:
            f.write(kind + "\n")
        if carrier is not None:
            with open(os.path.join(d, "carrier"), "w") as f:
                f.write(carrier + "\n")
        elif os.path.exists(os.path.join(d, "carrier")):
            os.remove(os.path.join(d, "carrier"))
        if device:
            os.makedirs(os.path.join(d, "device"), exist_ok=True)
        if wireless:
            os.makedirs(os.path.join(d, "wireless"), exist_ok=True)

    def _have(self, *names):
        for n in names:
            open(os.path.join(self.state, n), "w").close()

    def _sync(self, what="sync", settle="30"):
        import subprocess
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "hotspot.sh")
        log = os.path.join(self.tmp, "log")
        open(log, "w").close()
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], LOG=log,
                   STATE=self.state, AETHERSEED_NET_DIR=self.net, AETHERSEED_SETTLE=settle,
                   NET=self.net)
        r = subprocess.run(["bash", sh, what], env=env, text=True, capture_output=True)
        with open(log) as f:
            did = [l.strip()[6:] for l in f if not l.startswith("nmcli -t") and l.strip() != "nmcli radio wifi"]
        return r, did, sorted(os.listdir(self.state))

    def test_a_cable_with_a_link_switches_the_radio_off(self):
        self._have("profile", "radio", "up")
        r, did, state = self._sync()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(did, ["connection down aetherseed-hotspot", "radio wifi off"])
        self.assertEqual(state, ["profile"])
        self.assertIn("the radio is off", r.stdout)
        # ... and once it is off, nothing more is switched or said
        r, did, _ = self._sync()
        self.assertEqual((did, r.stdout), ([], ""))

    def test_no_cable_with_a_link_brings_it_up(self):
        self._have("profile")
        self._port("eth0", kind="1", carrier="0", device=True)
        r, did, state = self._sync()
        self.assertEqual(did, ["radio wifi on", "connection up aetherseed-hotspot"])
        self.assertEqual(state, ["profile", "radio", "up"])
        self.assertIn("Wi-Fi is up", r.stdout)
        r, did, _ = self._sync()                       # already up: left alone
        self.assertEqual((did, r.stdout), ([], ""))

    def test_a_port_that_cannot_be_read_is_no_link(self):
        self._have("profile")
        self._port("eth0", kind="1", carrier=None, device=True)    # the port is switched off
        _, did, state = self._sync()
        self.assertIn("up", state)

    def test_the_radio_is_not_a_cable(self):
        # wlan0 has a carrier while the access point is up; it must not count
        self._have("profile", "radio", "up")
        self._port("eth0", kind="1", carrier="0", device=True)
        _, did, state = self._sync()
        self.assertEqual((did, state), ([], ["profile", "radio", "up"]))

    def test_a_unit_with_no_wifi_of_its_own_is_left_alone(self):
        self._have("radio")                             # no profile
        self._port("eth0", kind="1", carrier="0", device=True)
        r, did, state = self._sync()
        self.assertEqual((r.returncode, did, state), (0, [], ["radio"]))

    def test_at_start_a_cable_is_given_time_to_find_its_link(self):
        # On Lyra the port found its link fifteen seconds after the unit came
        # up, and the Wi-Fi was up with the cable in for fourteen of them.
        self._have("profile")
        self._port("eth0", kind="1", carrier="0", device=True)
        # a second passes; at the third the cable has its link
        with open(os.path.join(self.bin, "sleep"), "w") as f:
            f.write('#!/bin/bash\necho x >> "$STATE/../slept"\n'
                    '[ "$(wc -l < "$STATE/../slept")" -ge 3 ] && echo 1 > "$NET/eth0/carrier"\nexit 0\n')
        r, did, state = self._sync("start")
        self.assertEqual((did, state), ([], ["profile"]))          # the radio never came on
        with open(os.path.join(self.tmp, "slept")) as f:
            self.assertEqual(len(f.read().split()), 3)

    def test_at_start_with_no_cable_it_comes_up_after_the_wait(self):
        self._have("profile")
        self._port("eth0", kind="1", carrier="0", device=True)
        with open(os.path.join(self.bin, "sleep"), "w") as f:
            f.write('#!/bin/bash\necho x >> "$STATE/../slept"\nexit 0\n')
        r, did, state = self._sync("start", settle="5")
        self.assertEqual(did, ["radio wifi on", "connection up aetherseed-hotspot"])
        with open(os.path.join(self.tmp, "slept")) as f:
            self.assertEqual(len(f.read().split()), 5)             # waited the whole of it first

    def test_networkmanager_never_raises_it_by_itself(self):
        sh = os.path.join(os.path.dirname(SERVICES), "tools", "hotspot.sh")
        text = open(sh, encoding="utf-8").read()
        self.assertIn("connection.autoconnect no", text)
        self.assertNotIn("connection.autoconnect yes", text)

    def test_the_unit_that_applies_it(self):
        d = unit("aetherseed-hotspot.service")
        self.assertIn("ExecStart=/bin/bash /opt/aetherseed/tools/hotspot.sh watch", d)
        self.assertIn("After=NetworkManager.service", d)
        self.assertIn("Restart=always", d)
        self.assertIn("WantedBy=multi-user.target", d)


class NothingTheUnitStartsLeavesIt(unittest.TestCase):
    """Build log 55. Andreas, 4 Oct 2026: "nothing at all should go out".

    Measured that day on Lyra with a cable in: the kiosk's browser held a
    connection to Google, the clock was synced over the network, package lists
    were fetched daily, the unit announced itself - and the firewall's output
    chain was "policy accept".
    """

    def setUp(self):
        with open(os.path.join(SERVICES, "nftables.conf"), encoding="utf-8") as f:
            self.out = chain(directives(f.read()), "output")

    def test_outbound_is_dropped_unless_named(self):
        self.assertEqual(self.out[0], "type filter hook output priority filter; policy drop;")
        accepts = [l for l in self.out if l.endswith("accept")]
        # everything let out, line by line: a new one is added here on purpose
        self.assertEqual(accepts, [
            'oif "lo" accept',
            "ct state established,related accept",
            "udp sport 68 udp dport 67 accept",
            'oifname "wlan0" udp sport 67 udp dport 68 accept',
            "icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, "
            "mld-listener-report, mld2-listener-report } accept",
        ])

    def test_no_name_lookup_no_clock_no_web_is_let_out(self):
        text = " ".join(self.out)
        for port in ("dport 53", "dport 123", "dport 80", "dport 443", "dport 5353"):
            self.assertNotIn(port, text)
        self.assertNotIn("ct state new", text)

    def test_what_tried_is_named_and_counted(self):
        self.assertEqual(self.out[-2],
                         'limit rate 6/minute log prefix "aetherseed out-drop: " flags skuid')
        self.assertEqual(self.out[-1], 'counter comment "outbound dropped by policy"')

    def test_the_browser_can_look_up_no_name(self):
        d = unit("aetherseed-kiosk.service")
        self.assertTrue(any("--host-resolver-rules='MAP * ~NOTFOUND , EXCLUDE 127.0.0.1'" in l
                            for l in d))
        self.assertTrue(any("--app=http://127.0.0.1:2077/" in l for l in d))

    def test_the_browser_may_open_the_console_and_nothing_else(self):
        import json
        with open(os.path.join(os.path.dirname(SERVICES), "kiosk", "chromium-policy.json"),
                  encoding="utf-8") as f:
            p = json.load(f)
        self.assertEqual(p["URLBlocklist"], ["*"])
        self.assertEqual(p["URLAllowlist"], ["127.0.0.1:2077"])
        for off in ("BackgroundModeEnabled", "MetricsReportingEnabled", "ComponentUpdatesEnabled",
                    "SearchSuggestEnabled", "TranslateEnabled", "PrintingEnabled",
                    "AllowFileSelectionDialogs", "BrowserNetworkTimeQueriesEnabled"):
            self.assertIs(p[off], False, off)
        self.assertIs(p["SyncDisabled"], True)
        self.assertEqual(p["DeveloperToolsAvailability"], 2)     # not available
        self.assertEqual(p["DownloadRestrictions"], 3)           # all blocked
        self.assertEqual(p["ExtensionInstallBlocklist"], ["*"])

    def test_the_clock_asks_nobody(self):
        with open(os.path.join(SERVICES, "timesyncd-aetherseed.conf"), encoding="utf-8") as f:
            d = directives(f.read())
        self.assertEqual(d, ["[Time]", "NTP=", "FallbackNTP=", "SaveIntervalSec=60"])

    def test_the_cartridge_sees_all_of_it(self):
        with open(os.path.join(os.path.dirname(SERVICES), "tools", "cartridge.sh"),
                  encoding="utf-8") as f:
            text = f.read()
        for needle in ("/etc/chromium/policies/managed/aetherseed.json",
                       "/etc/systemd/timesyncd.conf.d/aetherseed.conf",
                       "service.avahi.enabled", "timer.apt_daily.enabled",
                       "timer.apt_daily_upgrade.enabled"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
