"""Which model this unit serves - the unit's own setting (build log 68).

Andreas, 8 Oct 2026, on the plan claude/runtime-540-llama1b-plan.md (§4, the
model as a unit's own setting, "All of that looks good"): Lyra and the pilots
serve Llama 3.2 3B on HailoRT 5.1.1; Xena, on HailoRT 5.4.0, serves Llama 3.2
1B - there is no 3B for 5.4.0. One build serves both, as one build already
carries each unit's screen scale (/etc/aetherseed/kiosk.env, 5 Oct).

The setting is one line, written by whoever installs the unit (INSTALL §20),
never from the console:

    /etc/aetherseed/model.env      AETHERSEED_MODEL=llama3.2:1b

The services read it as an EnvironmentFile; a tool run by hand reads the file
itself. With neither, the unit serves the 3B, as every unit did before.

A name this build has no profile for, or whose prompt ceiling has not been
measured, is REFUSED - the proxy does not start - rather than served on a
guess: the guard in logic/token_budget.py exists to enforce exactly that one
number (build log steps 5, 42).
"""
import os

DEFAULT_MODEL = "llama3.2:3b"
MODEL_ENV = "AETHERSEED_MODEL"
MODEL_FILE = "/etc/aetherseed/model.env"


class UnknownModel(ValueError):
    pass


def _from_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(MODEL_ENV + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def configured_model(environ=None, path=None):
    """The name the unit is set to serve: the environment, else the file,
    else the default. Not checked."""
    environ = os.environ if environ is None else environ
    name = (environ.get(MODEL_ENV) or "").strip()
    if not name:
        name = _from_file(path or environ.get("AETHERSEED_MODEL_FILE") or MODEL_FILE) or ""
    return name or DEFAULT_MODEL


def served_model(environ=None, path=None):
    """The model this unit serves - checked: it must have a profile in
    logic/token_budget.MODELS and a measured ceiling."""
    from logic.token_budget import MODELS
    name = configured_model(environ, path)
    profile = MODELS.get(name)
    if profile is None:
        raise UnknownModel("%s=%r: this build has no profile for that model (known: %s)"
                           % (MODEL_ENV, name, ", ".join(sorted(MODELS))))
    if profile.get("ceiling") is None:
        raise UnknownModel("%s=%r: its prompt ceiling has not been measured on this "
                           "hardware - it cannot be served" % (MODEL_ENV, name))
    return name
