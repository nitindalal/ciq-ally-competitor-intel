import argparse, os
from .loaders import load_csv, select_skus
from .preprocess import preprocess
from .rules import validate_all
from .scoring import score_all
from .compare import compare_sections
from .recommender import suggest_edits_llm
from .render import render_markdown_report
from .approvals import ask_approval
from src.rules_registry import load_all_rules, select_rules
from src.rules_engine import validate_with_rules
from .rules_registry import load_all_rules, select_rules
from .rules_engine import validate_with_rules


STYLEGUIDE_REFS = [
    'Titles: concise; avoid ALL CAPS/promo/seller info【9†PetSupplies_PetFood_Styleguide_EN_AE._CB1198675309_.pdf†L96-L116】',
    'Bullets: up to 5; start with capital; no ending punctuation; be specific【9†...†L162-L212】',
    'Descriptions: concise, truthful; no promo/URLs【9†...†L214-L274】'
]

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--csv', default='data/asin_data_filled.csv')
    p.add_argument('--client_id', required=True)
    p.add_argument('--competitor_id', required=True)
    p.add_argument('--out', default='report.md')
    return p.parse_args()

def main():
    args = parse_args()
    df = load_csv(args.csv)
    client, competitor = select_skus(df, args.client_id, args.competitor_id)

    client_p = preprocess(client)
    comp_p   = preprocess(competitor)

    packs = load_all_rules("data/policies")  # scans all policy folders
    # keep it simple for now; later make these CLI args
    market = "AE"
    categories = [client_p.category or "PetSupplies"]

    rules = select_rules(packs, market="AE", categories=[])  # accept all categories

    client_find = validate_with_rules(client_p, rules)
    comp_find   = validate_with_rules(comp_p, rules)
    print("findings:", len(client_find), len(comp_find))  # quick sanity log

    client_find = validate_all(client_p)
    comp_find   = validate_all(comp_p)

    client_scores = score_all(client_p)
    comp_scores   = score_all(comp_p)

    comparison = compare_sections(client_p, comp_p, client_scores, comp_scores, client_find, comp_find)

    print("comparison:", len(comparison))  # quick sanity log

    recs = suggest_edits_llm(client_p, comp_p, comparison, STYLEGUIDE_REFS)

    approved = ask_approval(recs)

    md = render_markdown_report(client_p, comp_p, comparison, recs, approved, client_findings=client_find,competitor_findings=comp_find)

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'Wrote {args.out}')

if __name__ == '__main__':
    main()
