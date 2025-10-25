import re
from typing import List
from .models import SKU, Finding

PROMO_WORDS = re.compile(r'\b(sale|free shipping|free delivery|best seller|top seller)\b', re.I)
ALL_CAPS = re.compile(r'[A-Z]{4,}')
SYMBOLS = re.compile(r'[!*$?©®™]')

def check_title_basic(sku: SKU) -> List[Finding]:
    title = sku.title or ''
    findings = []
    findings.append(Finding(
        section='title',
        rule_id='TITLE_LENGTH',
        passed=len(title) <= 200,
        message=f'Title length {len(title)} chars (<=200 recommended).',
        citation='Titles: concise; no ALL CAPS/promos/seller info【9†PetSupplies_PetFood_Styleguide_EN_AE._CB1198675309_.pdf†L96-L116】'
    ))
    findings.append(Finding(
        section='title',
        rule_id='TITLE_PROMO',
        passed=not PROMO_WORDS.search(title),
        message='No promotional terms in title.',
        citation='No promo/seller info in titles【9†...†L96-L116】'
    ))
    findings.append(Finding(
        section='title',
        rule_id='TITLE_ALLCAPS',
        passed=not ALL_CAPS.search(title),
        message='Avoid long ALL CAPS tokens.',
        citation='Do not use ALL CAPS【9†...†L106-L116】'
    ))
    findings.append(Finding(
        section='title',
        rule_id='TITLE_SYMBOLS',
        passed=not SYMBOLS.search(title),
        message='No disallowed symbols in title.',
        citation='Do not include symbols like ! * $ ? © ® ™【9†...†L96-L116】'
    ))
    return findings

def check_bullets(sku: SKU) -> List[Finding]:
    bullets = sku.bullets or []
    msgs = []
    msgs.append(Finding(
        section='bullets',
        rule_id='BULLETS_COUNT',
        passed=1 <= len(bullets) <= 5,
        message=f'{len(bullets)} bullets (1–5 recommended).',
        citation='Key product features: up to 5; start with capital; no ending punctuation; be specific【9†...†L162-L212】'
    ))
    if bullets:
        bad_end = any(b.endswith('.') for b in bullets)
        msgs.append(Finding(
            section='bullets',
            rule_id='BULLETS_END_PUNCT',
            passed=not bad_end,
            message='Bullets should not end with punctuation.',
            citation='Bullets: sentence fragments; no ending punctuation【9†...†L174-L200】'
        ))
        vague = any(re.search(r'\b(top seller|best|great quality)\b', b, re.I) for b in bullets)
        msgs.append(Finding(
            section='bullets',
            rule_id='BULLETS_SPECIFIC',
            passed=not vague,
            message='Avoid vague claims like "Top seller".',
            citation='Be specific; avoid vague/promotional statements【9†...†L192-L212】'
        ))
    return msgs

def check_description(sku: SKU) -> List[Finding]:
    desc = sku.description or ''
    return [
        Finding(
            section='description',
            rule_id='DESC_LENGTH',
            passed=len(desc) <= 400,
            message=f'Description length {len(desc)} chars (concise recommended).',
            citation='Keep it short; correct grammar; no promo/seller info【9†...†L214-L274】'
        ),
        Finding(
            section='description',
            rule_id='DESC_PROMO',
            passed=not PROMO_WORDS.search(desc),
            message='No promotional language in description.',
            citation='No promotional language in description【9†...†L214-L274】'
        ),
        Finding(
            section='description',
            rule_id='DESC_SELLER_INFO',
            passed=not any(x in desc.lower() for x in ['www', 'http', '@']),
            message='No URLs/emails/seller info.',
            citation='Do not include seller/company/URL in description【9†...†L214-L274】'
        )
    ]

def validate_all(sku: SKU) -> List[Finding]:
    return check_title_basic(sku) + check_bullets(sku) + check_description(sku)
