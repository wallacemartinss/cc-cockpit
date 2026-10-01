import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "cockpit" / "web" / "index.html"
NODE = shutil.which("node")

# The dashboard's own formatters, stubbed to plain strings so the test reads
# the line's structure rather than the browser's number formatting.
STUBS = """
const T = {plan_roi: 'plano {name} · rendeu {roi}× este mês',
           month_equivalent: 'equivalente API no mês'};
const t = (k, v) => Object.entries(v || {}).reduce((s, [a, b]) => s.replace('{' + a + '}', b), T[k]);
const esc = s => String(s);
const LOCALE = 'pt-BR';
const money = v => 'US$ ' + v.toFixed(2);
let LOCAL = null;
const local = v => LOCAL ? ' · ' + LOCAL.symbol + ' ' + Math.round(v * LOCAL.rate) : '';
"""


def plan_line(plan, month_usd, local_currency=None):
    source = re.search(r"^function planLine\(.*?^}", HTML.read_text(), re.S | re.M).group(0)
    script = (STUBS + source + f"\nLOCAL = {json.dumps(local_currency)};\n"
              f"process.stdout.write(planLine({json.dumps(plan)}, {month_usd}));")
    return subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(NODE, "needs node")
class PlanLineTests(unittest.TestCase):
    PLAN = {"monthly_usd": 200.0, "name": "Max 20x", "roi": 11.8}
    BRL = {"code": "BRL", "symbol": "R$", "rate": 5.1991}

    def test_return_and_the_month_in_reais(self):
        self.assertEqual(plan_line(self.PLAN, 2359.03, self.BRL),
                         "plano Max 20x · rendeu 11,8× este mês · <b>US$ 2359.03</b> · R$ 12265")

    def test_return_and_the_month_without_a_local_currency(self):
        self.assertEqual(plan_line(self.PLAN, 2359.03),
                         "plano Max 20x · rendeu 11,8× este mês · <b>US$ 2359.03</b>")

    def test_the_return_follows_the_locale(self):
        self.assertIn("rendeu 12× este mês", plan_line({**self.PLAN, "roi": 12.0}, 2400))

    def test_no_plan_keeps_the_old_line(self):
        self.assertEqual(plan_line({"monthly_usd": None}, 2359.03, self.BRL),
                         "equivalente API no mês <b>US$ 2359.03</b> · R$ 12265")


if __name__ == "__main__":
    unittest.main()
