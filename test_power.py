"""Power: report the rails that can be measured, and nothing else.

The one thing this module must never do is invent a number. EXT5V reports a
voltage and no current, and a plausible-looking guess at the missing half would
be exactly the "2.5 watts" mistake step 14f struck out of the README.

    python3 -m unittest test_power -v

Needs no Pi: vcgencmd is stubbed.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

import power

SAMPLE = """ 3V7_WL_SW_A current(0)=0.00097593A
   3V3_SYS_A current(1)=0.14736540A
  VDD_CORE_A current(7)=0.54473000A
 3V7_WL_SW_V volt(8)=3.70256000V
   3V3_SYS_V volt(9)=3.30168200V
  VDD_CORE_V volt(15)=0.76476110V
     EXT5V_V volt(24)=5.15498000V
      BATT_V volt(25)=0.00000000V
"""


class Rails(unittest.TestCase):

    def setUp(self):
        self._real = power._vcgencmd
        def fake(*args):
            if args and args[0] == "pmic_read_adc":
                return SAMPLE
            if args and args[0] == "measure_temp":
                return "temp=49.4'C"
            if args and args[0] == "get_throttled":
                return "throttled=0x0"
            if args and args[0] == "measure_clock":
                return "frequency(0)=1500016128"
            return ""
        power._vcgencmd = fake

    def tearDown(self):
        power._vcgencmd = self._real

    def test_only_rails_with_both_halves_are_counted(self):
        r = power.rails()
        self.assertEqual({"3V7_WL_SW", "3V3_SYS", "VDD_CORE"}, set(r))

    def test_the_rail_with_no_current_sense_is_not_guessed_at(self):
        self.assertNotIn("EXT5V", power.rails())
        self.assertNotIn("BATT", power.rails())

    def test_watts_are_amps_times_volts(self):
        self.assertAlmostEqual(0.14736540 * 3.30168200, power.rails()["3V3_SYS"], places=3)

    def test_a_reading_carries_its_scope(self):
        out = power.read()
        self.assertEqual(3, out["rails_n"])
        self.assertAlmostEqual(0.9068, out["board_w"], places=3)   # 0.0036 + 0.4866 + 0.4166
        self.assertEqual(49.4, out["temp_c"])
        self.assertEqual("0x0", out["throttled"])
        self.assertEqual(1500, out["arm_mhz"])

    def test_the_scope_note_says_what_is_missing(self):
        self.assertIn("NPU", power.COVERS)
        self.assertIn("not wall power", power.COVERS)


class NoVcgencmd(unittest.TestCase):
    """On anything that is not a Pi, it reports nothing rather than zero.

    Zero watts is a measurement. Nothing is the truth.
    """

    def setUp(self):
        self._real = power._vcgencmd
        power._vcgencmd = lambda *a: ""

    def tearDown(self):
        power._vcgencmd = self._real

    def test_no_rails_means_no_number(self):
        self.assertEqual({}, power.rails())
        out = power.read()
        self.assertIsNone(out["board_w"])
        self.assertEqual(0, out["rails_n"])
        self.assertIsNone(out["temp_c"])
        self.assertIsNone(out["arm_mhz"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
