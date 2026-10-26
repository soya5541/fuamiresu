"""Stock monitor for ISBN 9784047377486.

Status 'possible' means an ordering signal was detected, not guaranteed stock.
"""
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ISBN = '9784047377486'
PRODUCT = 'ファミレス行こ。 上 アクリルスタンド付き特装版'
SITES = {
    'KADOKAWA': {'url': 'https://store.kadokawa.co.jp/shop/g/g322308000883/',
                 'negative': ['在庫がありません', '在庫なし'],
                 'positive': ['カートに入れる', '在庫あり', 'お取り寄せ']},
    'Animate': {'url': 'https://www.animate-onlineshop.jp/pd/2326011/',
                'negative': ['販売終了', '在庫なし'],
                'positive': ['カートに入れる', '予約受付中', '取り寄せ']},
    'Kinokuniya': {'url': 'https://www.kinokuniya.co.jp/f/dsg-01-9784047377486',
                   'negative': ['ご注文を受け付けておりません'],
                   'positive': ['カートに入れる', 'ご注文いただけます', '取り寄せ']},
    'Maruzen Junkudo': {'url': 'https://www.maruzenjunkudo.co.jp/products/9784047377486',
                        'negative': ['売り切れ', '在庫切れ', '在庫なし'],
                        'positive': ['カートに追加する', 'カートに入れる', '購入する']},
    'Tower Records': {'url': 'https://tower.jp/item/6178367', 'checker': 'tower'},
    'Rakuten Books': {'url': 'https://books.rakuten.co.jp/rb/17625532/', 'checker': 'rakuten'},
}
STATE = Path('state.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}


def normalized_text(element):
    if element is None:
        return ''
    return re.sub(r'\s+', ' ', element.get_text(' ', strip=True)).strip()


def is_product(soup, raw_html):
    # The exact ISBN was verified in both stores' diagnostic runs.
    return ISBN in raw_html and 'ファミレス行こ' in normalized_text(soup)


def is_enabled(tag):
    if tag.has_attr('disabled') or tag.get('aria-disabled', '').lower() == 'true':
        return False
    classes = tag.get('class', [])
    if any('disabled' in cls.lower() for cls in classes):
        return False
    # An action inside a disabled fieldset is not actionable.
    if tag.find_parent('fieldset', disabled=True):
        return False
    return True


def action_labels(container):
    labels = []
    for tag in container.select('button, a, input[type="submit"], input[type="button"]'):
        label = ' '.join(filter(None, [normalized_text(tag), tag.get('value', ''), tag.get('aria-label', '')]))
        label = re.sub(r'\s+', ' ', label).strip()
        if any(x in label for x in ('買い物かごに入れる', 'カートに入れる', '注文する', '購入する', '予約する', 'お取り寄せ')):
            if is_enabled(tag):
                labels.append(label[:90])
    return labels


def check_rakuten(soup):
    # Do not scan banners, promotions or generic '在庫あり' messages outside the purchase box.
    box = soup.select_one('#purchaseBoxMain')
    if box is None:
        return {'status': 'unknown', 'detail': '라쿠텐 상품 구매 영역(#purchaseBoxMain) 없음'}
    availability = box.select_one('.availability')
    if availability is None:
        return {'status': 'unknown', 'detail': '라쿠텐 구매 상태 영역(.availability) 없음'}
    status_text = normalized_text(availability)
    negative_terms = ('ご注文できない商品', 'ご注文いただけない商品',
                      '現在ご注文いただけません', '売り切れ', '在庫なし')
    negatives = [x for x in negative_terms if x in status_text]
    if negatives:
        return {'status': 'unavailable', 'detail': '상품 구매 영역: ' + ', '.join(negatives)}
    actions = action_labels(box)
    if actions:
        return {'status': 'possible', 'detail': '상품 구매 영역의 활성 버튼: ' + ', '.join(actions[:2])}
    return {'status': 'unknown', 'detail': '상품 구매 영역에서 주문 가능/불가 신호 미확인'}


def check_tower(soup):
    # The observed negative text belongs to the product's ordering information.
    # Negative signals take precedence over generic purchase links elsewhere on the page.
    text = normalized_text(soup)
    negative_terms = ('現在ご注文いただけません', 'ご注文いただけません', '販売終了')
    negatives = [x for x in negative_terms if x in text]
    if negatives:
        return {'status': 'unavailable', 'detail': '주문 불가 표시: ' + ', '.join(negatives)}

    # Product-specific order sections are preferable to site-wide navigation text.
    # The Tower HTML structure may change; do not infer stock from the disappearance
    # of an unavailable message alone.
    candidates = [soup.select_one(sel) for sel in (
        '#itemInfo', '#itemDetail', '#item_detail', '#productDetail',
        '.itemDetail', '.item-detail', '.product-detail', '.itemInfo',
    )]
    for section in candidates:
        if section is None:
            continue
        section_text = normalized_text(section)
        if any(x in section_text for x in ('お取り寄せ', 'メーカー取り寄せ')):
            return {'status': 'possible', 'detail': '상품 정보 영역: お取り寄せ'}
        actions = action_labels(section)
        if actions:
            return {'status': 'possible', 'detail': '상품 정보 영역의 활성 버튼: ' + ', '.join(actions[:2])}
    return {'status': 'unknown', 'detail': '주문 불가 문구 없음; 상품 주문 가능 신호는 미확인'}


def check_legacy(soup, cfg):
    # Preserve original checks for the existing four stores.
    text = normalized_text(soup)
    if ISBN not in text and 'アクリルスタンド付き特装版' not in text:
        return {'status': 'unknown', 'detail': '상품 식별 정보 확인 불가 (차단/렌더링 가능성)'}
    negatives = [x for x in cfg['negative'] if x in text]
    positives = [x for x in cfg['positive'] if x in text]
    if negatives and positives:
        return {'status': 'unknown', 'detail': '상충하는 문구: ' + ', '.join((negatives + positives)[:4])}
    if negatives:
        return {'status': 'unavailable', 'detail': ', '.join(negatives)}
    if positives:
        return {'status': 'possible', 'detail': ', '.join(positives)}
    return {'status': 'unknown', 'detail': '구매 상태 문구 식별 불가'}


def check(name, cfg):
    try:
        response = requests.get(cfg['url'], headers=HEADERS, timeout=18)
        response.raise_for_status()
        raw_html = response.text
        soup = BeautifulSoup(raw_html, 'html.parser')
        for tag in soup(['script', 'style', 'noscript', 'svg']):
            tag.decompose()
        if cfg.get('checker') in ('tower', 'rakuten'):
            if not is_product(soup, raw_html):
                return {'status': 'unknown', 'detail': '상품명/ISBN 확인 실패 (페이지 변경 또는 접근 제한)'}
            return check_tower(soup) if cfg['checker'] == 'tower' else check_rakuten(soup)
        return check_legacy(soup, cfg)
    except requests.RequestException as exc:
        return {'status': 'unknown', 'detail': f'접근 실패: {type(exc).__name__}'}
    except Exception as exc:
        return {'status': 'unknown', 'detail': f'분석 실패: {type(exc).__name__}'}


def main():
    old = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    updated = {}
    alerts = []
    for name, cfg in SITES.items():
        result = check(name, cfg)
        status = result['status']
        prev = old.get(name, {}).get('status')
        print(f'{name}: {status} ({result["detail"]})', flush=True)
        if status == 'possible' and prev != 'possible':
            alerts.append({'name': name, 'url': cfg['url'], 'detail': result['detail']})
        updated[name] = {'status': status, 'detail': result['detail']}
        time.sleep(1)
    STATE.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    Path('alerts.json').write_text(json.dumps(alerts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if alerts:
        print('ALERTS: ' + json.dumps(alerts, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
