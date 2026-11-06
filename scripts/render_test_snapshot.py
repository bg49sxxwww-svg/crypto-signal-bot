from html import escape
from pathlib import Path

result_file = Path("test-results.txt")
lines = result_file.read_text(encoding="utf-8").splitlines() if result_file.exists() else ["Test output unavailable"]
visible = lines[-17:]
text_nodes = "".join(
    f'<text x="36" y="{90 + index * 24}" fill="#e5e7eb" '
    f'font-family="monospace" font-size="16">{escape(line[:130])}</text>'
    for index, line in enumerate(visible)
)
svg = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520">'
    '<rect width="100%" height="100%" fill="#111827"/>'
    '<text x="36" y="48" fill="#93c5fd" font-family="monospace" '
    'font-size="24">Crypto Signal Bot - Regression Test</text>'
    f'{text_nodes}</svg>'
)
Path("test-results.svg").write_text(svg, encoding="utf-8")
