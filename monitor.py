"""Stock monitor for ファミレス行こ。(上) アクリルスタンド付き特装版.

"possible" means an order signal was found, NOT confirmed inventory.
Output contract: state.json and alerts.json for the existing GitHub workflow.
"""
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ISBN = "9784047377486"
PRODUCT = "ファミレス行こ。 上 アクリルスタンド付き特装版"
SITES = {
    "KADOKAWA": {
        "url": "https://store.kadokawa.co.jp/shop/g/g322308000883/",
        "checker": "kadokawa",
    },
    "Tower Records": {
        "url": "https://tower.jp/item/6178367",
        "checker": "tower",
    },
    "Rakuten Books": {
        "url": "https://books.rakuten.co.jp/rb/17625532/",
        "checker": "rakuten",
    },
    "Maruzen Junkudo": {
        "url": "https://www.maruzenjunkudo.co.jp/products/9784047377486",
        "checker": "maruzen",
    },
}
STATE = Path("state.json")
ALERTS = Path("alerts.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def result(status, detail):
    return {"status": status, "detail": detail}


def normalized_text(element):
    if element is None:
        return ""
    return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()


def product_verified(soup, html):
    text = normalized_text(soup)
    return (
        ISBN in html
        and "ファミレス行こ" in text
        and "アクリルスタンド付き特装版" in text
    )


def is_enabled(tag):
    if tag.has_attr("disabled") or tag.get("aria-disabled", "").lower() == "true":
        return False
    if any("disabled" in cls.lower() for cls in tag.get("class", [])):
        return False
    if tag.find_parent("fieldset", disabled=True):
        return False
    return True


def action_labels(container):
    labels = []
    for tag in container.select('button, a, input[type="submit"], input[type="button"]'):
        label = " ".join(filter(None, [
            normalized_text(tag), tag.get("value", ""), tag.get("aria-label", ""),
        ]))
        label = re.sub(r"\s+", " ", label).strip()
        if any(term in label for term in (
            "買い物かごに入れる", "カートに入れる", "注文する",
            "購入する", "予約する", "お取り寄せ",
        )) and is_enabled(tag):
            labels.append(label[:90])
    return labels


def check_rakuten(soup):
    # Confirmed by the GitHub diagnostic: #purchaseBox (NOT #purchaseBoxMain).
    box = soup.select_one("#purchaseBox")
    if box is None:
        return result("unknown", "라쿠텐 상품 구매 영역(#purchaseBox) 없음")
    availability = box.select_one(".availability")
    if availability is None:
        return result("unknown", "라쿠텐 구매 상태 영역(.availability) 없음")
    status_text = normalized_text(availability)
    negatives = [x for x in (
        "ご注文できない商品", "ご注文いただけない商品",
        "現在ご注文いただけません", "売り切れ", "在庫なし",
    ) if x in status_text]
    if negatives:
        return result("unavailable", "라쿠텐 상품 구매 상태: " + ", ".join(negatives))
    actions = action_labels(box)
    if actions:
        return result("possible", "라쿠텐 상품 구매 영역의 활성 버튼: " + ", ".join(actions[:2]))
    return result("unknown", "라쿠텐 구매 영역에 확인된 주문 가능/불가 신호 없음")


def check_tower(soup):
    # Preserve the confirmed negative detection from the existing monitor.
    text = normalized_text(soup)
    negatives = [x for x in (
        "現在ご注文いただけません", "ご注文いただけません", "販売終了",
    ) if x in text]
    if negatives:
        return result("unavailable", "타워레코드 주문 불가 표시: " + ", ".join(negatives))
    for selector in (
        "#itemInfo", "#itemDetail", "#item_detail", "#productDetail",
        ".itemDetail", ".item-detail", ".product-detail", ".itemInfo",
    ):
        section = soup.select_one(selector)
        if section is None:
            continue
        text = normalized_text(section)
        if "メーカー取り寄せ" in text or "お取り寄せ" in text:
            return result("possible", "타워레코드 상품 정보 영역: お取り寄せ")
        actions = action_labels(section)
        if actions:
            return result("possible", "타워레코드 상품 영역의 활성 버튼: " + ", ".join(actions[:2]))
    return result("unknown", "타워레코드 상품 주문 가능 신호 미확인")


def check_kadokawa(soup):
    # Keep the previously successful negative check; avoid asserting stock from
    # conflicting generic page-wide copy.
    text = normalized_text(soup)
    negatives = [x for x in ("在庫がありません", "在庫なし") if x in text]
    positives = [x for x in ("カートに入れる", "在庫あり", "お取り寄せ") if x in text]
    if negatives and positives:
        return result("unknown", "KADOKAWA 주문 가능/불가 문구 충돌")
    if negatives:
        return result("unavailable", "KADOKAWA: " + ", ".join(negatives))
    if positives:
        # Retain the old behavior, but do not treat a generic page-wide "在庫あり"
        # as a verified product order button.
        for selector in ("form[action*='cart']", "#productDetail", ".product-detail"):
            section = soup.select_one(selector)
            if section and action_labels(section):
                return result("possible", "KADOKAWA 상품 구매 버튼 확인")
        return result("unknown", "KADOKAWA 긍정 문구 발견, 상품 구매 버튼은 미확인")
    return result("unknown", "KADOKAWA 상품 주문 상태 신호 없음")


def check_maruzen(session, soup, url):
    # The store's Shopify product JSON was reachable (HTTP 200) in GitHub Actions.
    # Its "available: true" conflicted with "売り切れ" in the HTML diagnostic.
    # A conflict must not be reported as confirmed ordering.
    js_url = url.rstrip("/") + ".js"
    response = session.get(js_url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return result("unknown", "마루젠 JSON 상품 데이터 형식 오류")
    title = str(data.get("title", ""))
    if "ファミレス行こ" not in title or "アクリルスタンド付き特装版" not in title:
        return result("unknown", "마루젠 JSON 특장판 상품명 불일치")
    # Verify the ISBN against the product URL and the HTML checked by caller.
    variants = data.get("variants")
    if not isinstance(variants, list) or len(variants) != 1:
        return result("unknown", "마루젠 상품 옵션 수가 달라짐; 수동 확인 필요")
    available = variants[0].get("available")
    if not isinstance(available, bool):
        return result("unknown", "마루젠 JSON 구매 가능 여부 없음")
    # Restrict conflicting HTML signals to the product form/container.
    section = soup.select_one(".product__info-container") or soup.select_one(".product-form")
    section_text = normalized_text(section)
    sold_out = any(x in section_text for x in ("売り切れ", "在庫切れ", "在庫なし"))
    if available and sold_out:
        return result("unknown", "마루젠 JSON available=true, 상품 HTML 売り切れ: 상충")
    if available:
        return result("possible", "마루젠 상품 JSON available=true (주문 성공 미검증)")
    return result("unavailable", "마루젠 상품 JSON available=false")


def check(name, cfg, session=None):
    session = session or requests.Session()
    try:
        response = session.get(cfg["url"], headers=HEADERS, timeout=20)
        response.raise_for_status()
        raw_html = response.text
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        if not product_verified(soup, raw_html):
            return result("unknown", "ISBN/특장판 상품명 검증 실패 (차단 또는 페이지 변경)")
        checker = cfg["checker"]
        if checker == "kadokawa":
            return check_kadokawa(soup)
        if checker == "tower":
            return check_tower(soup)
        if checker == "rakuten":
            return check_rakuten(soup)
        if checker == "maruzen":
            return check_maruzen(session, soup, cfg["url"])
        return result("unknown", "정의되지 않은 판매처 판별 방식")
    except (requests.RequestException, ValueError) as exc:
        return result("unknown", "접근/데이터 오류: " + type(exc).__name__)
    except Exception as exc:
        return result("unknown", "분석 오류: " + type(exc).__name__)


def load_state():
    if not STATE.exists():
        return {}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        print("WARNING: state.json 읽기 실패; 이전 알림 이력을 확인할 수 없음", flush=True)
        return {}


def main():
    old = load_state()
    updated = {}
    alerts = []
    with requests.Session() as session:
        for name, cfg in SITES.items():
            observation = check(name, cfg, session)
            status = observation["status"]
            previous = old.get(name, {})
            if not isinstance(previous, dict):
                previous = {}
            # Migration from the original state.json: prior "possible" counts as
            # already alerted. Unknown does NOT reset the alert latch.
            already_alerted = bool(previous.get(
                "alerted_in_current_cycle", previous.get("status") == "possible"
            ))
            if status == "unavailable":
                already_alerted = False
            elif status == "possible" and not already_alerted:
                alerts.append({
                    "name": name,
                    "url": cfg["url"],
                    "detail": observation["detail"],
                })
                already_alerted = True
            print(f'{name}: {status} ({observation["detail"]})', flush=True)
            updated[name] = {
                "status": status,
                "detail": observation["detail"],
                "alerted_in_current_cycle": already_alerted,
            }
            time.sleep(1)
    STATE.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ALERTS.write_text(
        json.dumps(alerts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if alerts:
        print("ALERTS: " + json.dumps(alerts, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
