"""Inline results/leaderboard.json into site/template.html -> web/index.html (the launch snapshot;
the page also fetches the live leaderboard from the repo).  uv run python site/build_site.py"""
import json, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
board = json.loads((root / "results" / "leaderboard.json").read_text())
take = (root / "site" / "takeaways.html").read_text() if (root / "site" / "takeaways.html").exists() else ""
html = (root / "site" / "template.html").read_text().replace("/*DATA*/null", json.dumps(board)).replace("<!--TAKEAWAYS-->", take)
(root / "web" / "index.html").write_text(html)
print("wrote web/index.html with", len(board["models"]), "models")
