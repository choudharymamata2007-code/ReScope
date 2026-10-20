"""Runs every dashboard tab for every demo company against stand-ins for streamlit and plotly.
Catches Python errors (bad keys, missing data paths). It does NOT check real Streamlit/Plotly API behaviour:
open the dashboard once to confirm that."""
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Ctx:
    st = None  # set to the FakeSt so widgets called on a column or tab behave like st.*
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, n): return getattr(Ctx.st, n)
    def __iter__(self): return iter([])


class FakeSt:
    company_index = 0
    def __init__(self): self.calls = 0
    def columns(self, spec, **k): return [Ctx() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def tabs(self, labels): return [Ctx() for _ in labels]
    def selectbox(self, label, options, index=0, key=None, **k):
        opts = list(options)
        return opts[self.company_index if key == "company" else min(index or 0, len(opts) - 1)] if opts else None
    def radio(self, label, options, **k): return list(options)[0]
    def multiselect(self, label, options, default=None, **k): return list(default if default is not None else [])
    def toggle(self, *a, **k): return False
    def button(self, *a, **k): return False
    def text_input(self, *a, **k): return ""
    def spinner(self, *a, **k): return Ctx()
    def expander(self, *a, **k): return Ctx()
    def empty(self): return Ctx()
    def __getattr__(self, n): return lambda *a, **k: Ctx()


def install():
    fake = FakeSt()
    Ctx.st = fake
    sys.modules["streamlit"] = fake
    plotly = types.ModuleType("plotly"); go = MagicMock()
    plotly.graph_objects = go
    sys.modules["plotly"] = plotly; sys.modules["plotly.graph_objects"] = go
    return fake


class TestSmoke(unittest.TestCase):
    def test_every_tab_every_company(self):
        from rescope_m2.ui import data
        n = len(data.list_bundles(ROOT / "data" / "bundles"))
        self.assertGreaterEqual(n, 5)
        for i in range(n):
            fake = install()
            fake.company_index = i
            for m in [k for k in list(sys.modules) if k.startswith("rescope_m2.ui") or k == "dashboard"]:
                del sys.modules[m]
            importlib.import_module("dashboard")  # runs main() with the fake


if __name__ == "__main__":
    unittest.main()
