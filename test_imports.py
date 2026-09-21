"""Nothing the service can write can shadow its code.

    python3 -m unittest test_imports -v

The service runs with HOME=/var/lib/aetherseed, its WRITABLE state directory.
Until 2026-09-21 trust_evolution put HOME first on the import path, and
intent_detection added "~/aetherseed-ai" on every call - so a .py file in the
state directory would have been imported instead of the application's own
module (build log, step 22). Found because a stale ~/honesty_check.py on the
dev unit was being imported by the tests. Standard library only.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

PROBE = textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, %r)
    import trust_evolution, honesty_check, intent_detection
    try:
        intent_detection._trust_status()
    except Exception:
        pass
    home = os.path.realpath(os.environ["HOME"])
    print(json.dumps({
        "honesty_check": os.path.realpath(honesty_check.__file__),
        "home_on_path": [p for p in sys.path
                         if p and os.path.realpath(p).startswith(home)],
        "planted_ran": "PLANTED" in os.environ.get("PLANTED_FLAG", "")
                       or os.path.exists(os.path.join(home, "planted_ran")),
    }))
""") % HERE


class TestAWritableHomeCannotShadowTheApp(unittest.TestCase):

    def test_a_planted_module_in_home_is_not_imported(self):
        home = tempfile.mkdtemp()
        # Hostile copies of two application modules, in the service's HOME.
        for name in ("honesty_check.py", "aetherroot.py", "trust_evolution.py"):
            with open(os.path.join(home, name), "w") as f:
                f.write("open(__import__('os').path.join(__import__('os').environ['HOME'],"
                        " 'planted_ran'), 'w').close()\n")
        os.makedirs(os.path.join(home, "aetherseed-ai"))
        with open(os.path.join(home, "aetherseed-ai", "trust_evolution.py"), "w") as f:
            f.write("open(__import__('os').path.join(__import__('os').environ['HOME'],"
                    " 'planted_ran'), 'w').close()\n")
        env = dict(os.environ, HOME=home)
        out = subprocess.run([sys.executable, "-c", PROBE], env=env, cwd=HERE,
                             capture_output=True, text=True, timeout=60)
        # First, the thing that matters: did code from the writable HOME run?
        self.assertFalse(os.path.exists(os.path.join(home, "planted_ran")),
                         "a module planted in the service's writable HOME was executed")
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        import json
        d = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(d["honesty_check"], os.path.realpath(os.path.join(HERE, "honesty_check.py")))
        self.assertEqual(d["home_on_path"], [], "a writable HOME is on the import path")
        self.assertFalse(d["planted_ran"], "a planted module was executed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
