"""Headless smoke test of the Streamlit app on real data: start the app,
run one comparison per alignment method for the default company, and report
what rendered. Requires the filings (scripts/fetch_filings.py).

Usage:  python scripts/smoke_test_app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

if __name__ == "__main__":
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
    assert not at.exception, at.exception
    print("App started. Companies:", at.sidebar.selectbox[0].options)
    for method_index in (0, 1):
        at.sidebar.selectbox[3].set_value(at.sidebar.selectbox[3].options[method_index]).run()
        at.sidebar.button[0].click().run()
        assert not at.exception, at.exception
        errors = [e.value for e in at.error]
        assert not errors, errors
        metrics = {m.label: m.value for m in at.metric}
        assert metrics, "no label counts rendered"
        print(f"Method {at.sidebar.selectbox[3].value!r}:")
        for label, value in metrics.items():
            print(f"   {label}: {value}")
    print("Smoke test passed.")
