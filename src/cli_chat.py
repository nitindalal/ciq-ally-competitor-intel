# src/cli_chat.py
import sys
from pathlib import Path

# Ensure project root import works
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skill import run_compare, _coerce_list
from src.rules_engine import validate_with_rules
from src.rules_registry import load_all_rules, select_rules

BANNER = """\
CIQ Ally – Competitor Content Intelligence (Chat Demo)
Commands:
  compare <client_id> <competitor_id>
  show report
  show draft
  edit bullet <N>: <text>
  title: <new title>
  description: <new description>
  bullets:
    <one per line>
    (end with a single '.' line)
  validate
  approve
  final
  help
  quit
"""

state = {
    "results": None,      # output of run_compare
    "approved": False
}

def read_multiline():
    print("(Paste bullets, end with a single '.' on its own line)")
    lines = []
    while True:
        line = input("… ")
        if line.strip() == ".":
            break
        lines.append(line)
    return lines

def main():
    print(BANNER)

    while True:
        try:
            line = input("ally> ").strip()
        except EOFError:
            break
        if not line:
            continue

        low = line.lower()

        if low in ("quit", "exit"):
            break

        # ---- RUN COMPARE ----
        if low.startswith("compare "):
            parts = line.split()
            client_id, competitor_id = parts[1], parts[2]
            result = run_compare(client_id, competitor_id)
            state["results"] = result
            state["approved"] = False
            print("\n--- REPORT ---\n")
            print(result["report_markdown"])
            print("\nNext actions: edit bullet, title, description, validate, approve.\n")
            continue

        # If no comparison was run yet:
        if not state["results"]:
            print("Run `compare <client> <competitor>` first.")
            continue

        # ---- SHOW REPORT ----
        if low == "show report":
            print(state["results"]["report_markdown"])
            continue

        # ---- SHOW DRAFT ----
        if low == "show draft":
            d = state["results"]["draft"]
            print(f"Title: {d['title']}")
            print("Bullets:")
            for i, b in enumerate(d["bullets"], 1):
                print(f"  {i}. {b}")
            print("Description:", d["description"])
            continue

        # ---- EDIT BULLET ----
        if low.startswith("edit bullet "):
            # edit bullet N: text
            try:
                body = line[len("edit bullet "):]
                idx_str, text = body.split(":", 1)
                idx = int(idx_str.strip()) - 1
                bullets = state["results"]["draft"]["bullets"]
                while idx >= len(bullets):
                    bullets.append("")
                bullets[idx] = text.strip()
                state["results"]["draft"]["bullets"] = bullets
                print("✅ Bullet updated.")
            except Exception as e:
                print(f"Error: {e}")
            continue

        # ---- EDIT TITLE ----
        if low.startswith("title:"):
            state["results"]["draft"]["title"] = line.split(":",1)[1].strip()
            print("✅ Title updated.")
            continue

        # ---- EDIT DESCRIPTION ----
        if low.startswith("description:"):
            state["results"]["draft"]["description"] = line.split(":",1)[1].strip()
            print("✅ Description updated.")
            continue

        # ---- REPLACE BULLETS ----
        if low == "bullets:":
            lines = read_multiline()
            state["results"]["draft"]["bullets"] = _coerce_list("\n".join(lines))
            print("✅ Bullets replaced.")
            continue

        # ---- VALIDATE ----
        if low == "validate":
            packs = load_all_rules("data/policies")
            rules = select_rules(packs, market="AE", categories=[])
            draft = state["results"]["draft"]

            # copy client SKU and insert edited draft fields
            client = state["results"]["client"]
            client.title = draft["title"]
            client.bullets = draft["bullets"]
            client.description = draft["description"]

            failing = [f for f in validate_with_rules(client, rules) if not f.passed]
            if failing:
                print(f"❗ {len(failing)} issue(s):")
                for f in failing:
                    print(f"- {f.rule_id} ({f.section}): {f.message}")
            else:
                print("✅ Draft passes all policy checks!")
            continue

        # ---- APPROVE ----
        if low == "approve":
            state["approved"] = True
            print("✅ Approved. Use `final` to output final Markdown.")
            continue

        # ---- FINAL MARKDOWN ----
        if low == "final":
            draft = state["results"]["draft"]
            cid = state["results"]["client"].sku_id
            print(f"# FINAL – {cid}")
            print("\n## Title\n" + draft["title"])
            print("\n## Bullets")
            for b in draft["bullets"]:
                print(f"- {b}")
            print("\n## Description\n" + draft["description"])
            continue

        if low == "help":
            print(BANNER)
            continue

        print("Unknown command. Type `help`.")

if __name__ == "__main__":
    main()
