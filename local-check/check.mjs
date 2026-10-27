/**
 * Local, read-only port of ../monitor.py for machines without Python.
 *
 * Prints each store's status. Does NOT write state.json or alerts.json and
 * sends no notifications. Keep the detection rules in sync with monitor.py,
 * which remains the source of truth for the GitHub Actions monitor.
 */
import { readFile } from "node:fs/promises";
import * as cheerio from "cheerio";

const ISBN = "9784047377486";
const SITES = {
  "KADOKAWA": {
    url: "https://store.kadokawa.co.jp/shop/g/g322308000883/",
    checker: "kadokawa",
  },
  "Tower Records": {
    url: "https://tower.jp/item/6178367",
    checker: "tower",
  },
  "Rakuten Books": {
    url: "https://books.rakuten.co.jp/rb/17625532/",
    checker: "rakuten",
  },
  "Maruzen Junkudo": {
    url: "https://www.maruzenjunkudo.co.jp/products/9784047377486",
    checker: "maruzen",
  },
};
const STATE = new URL("../state.json", import.meta.url);
const HEADERS = {
  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
  "Accept-Language": "ja-JP,ja;q=0.9",
};

class HTTPError extends Error {
  constructor(status) {
    super(status === 429 ? "HTTP 429 (사이트 접속 제한, 잠시 후 재시도)" : `HTTP ${status}`);
    this.name = "HTTPError";
  }
}

function result(status, detail) {
  return { status, detail };
}

// Mirrors BeautifulSoup get_text(" ", strip=True) + whitespace collapse.
function normalizedText(node) {
  if (!node) return "";
  const parts = [];
  const walk = (n) => {
    if (n.type === "text") {
      const t = n.data.trim();
      if (t) parts.push(t);
    } else if (n.children) {
      n.children.forEach(walk);
    }
  };
  walk(node);
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function productVerified($, html) {
  const text = normalizedText($.root()[0]);
  return (
    html.includes(ISBN) &&
    text.includes("ファミレス行こ") &&
    text.includes("アクリルスタンド付き特装版")
  );
}

function isEnabled($, tag) {
  const el = $(tag);
  if (el.attr("disabled") !== undefined ||
      (el.attr("aria-disabled") || "").toLowerCase() === "true") {
    return false;
  }
  const classes = (el.attr("class") || "").split(/\s+/).filter(Boolean);
  if (classes.some((cls) => cls.toLowerCase().includes("disabled"))) return false;
  if (el.parents("fieldset[disabled]").length) return false;
  return true;
}

function actionLabels($, container) {
  const labels = [];
  $(container).find('button, a, input[type="submit"], input[type="button"]').each((_, tag) => {
    const label = [normalizedText(tag), $(tag).attr("value") || "", $(tag).attr("aria-label") || ""]
      .filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
    if ([
      "買い物かごに入れる", "カートに入れる", "注文する",
      "購入する", "予約する", "お取り寄せ",
    ].some((term) => label.includes(term)) && isEnabled($, tag)) {
      labels.push(label.slice(0, 90));
    }
  });
  return labels;
}

function checkRakuten($) {
  // Confirmed by the GitHub diagnostic: #purchaseBox (NOT #purchaseBoxMain).
  const box = $("#purchaseBox").get(0);
  if (!box) return result("unknown", "라쿠텐 상품 구매 영역(#purchaseBox) 없음");
  const availability = $(box).find(".availability").get(0);
  if (!availability) return result("unknown", "라쿠텐 구매 상태 영역(.availability) 없음");
  const statusText = normalizedText(availability);
  const negatives = [
    "ご注文できない商品", "ご注文いただけない商品",
    "現在ご注文いただけません", "売り切れ", "在庫なし",
  ].filter((x) => statusText.includes(x));
  if (negatives.length) {
    return result("unavailable", "라쿠텐 상품 구매 상태: " + negatives.join(", "));
  }
  const actions = actionLabels($, box);
  if (actions.length) {
    return result("possible", "라쿠텐 상품 구매 영역의 활성 버튼: " + actions.slice(0, 2).join(", "));
  }
  return result("unknown", "라쿠텐 구매 영역에 확인된 주문 가능/불가 신호 없음");
}

function checkTower($) {
  const text = normalizedText($.root()[0]);
  const negatives = [
    "現在ご注文いただけません", "ご注文いただけません", "販売終了",
  ].filter((x) => text.includes(x));
  if (negatives.length) {
    return result("unavailable", "타워레코드 주문 불가 표시: " + negatives.join(", "));
  }
  for (const selector of [
    "#itemInfo", "#itemDetail", "#item_detail", "#productDetail",
    ".itemDetail", ".item-detail", ".product-detail", ".itemInfo",
  ]) {
    const section = $(selector).get(0);
    if (!section) continue;
    const sectionText = normalizedText(section);
    if (sectionText.includes("メーカー取り寄せ") || sectionText.includes("お取り寄せ")) {
      return result("possible", "타워레코드 상품 정보 영역: お取り寄せ");
    }
    const actions = actionLabels($, section);
    if (actions.length) {
      return result("possible", "타워레코드 상품 영역의 활성 버튼: " + actions.slice(0, 2).join(", "));
    }
  }
  return result("unknown", "타워레코드 상품 주문 가능 신호 미확인");
}

function checkKadokawa($) {
  const text = normalizedText($.root()[0]);
  const negatives = ["在庫がありません", "在庫なし"].filter((x) => text.includes(x));
  const positives = ["カートに入れる", "在庫あり", "お取り寄せ"].filter((x) => text.includes(x));
  if (negatives.length && positives.length) {
    return result("unknown", "KADOKAWA 주문 가능/불가 문구 충돌");
  }
  if (negatives.length) return result("unavailable", "KADOKAWA: " + negatives.join(", "));
  if (positives.length) {
    for (const selector of ["form[action*='cart']", "#productDetail", ".product-detail"]) {
      const section = $(selector).get(0);
      if (section && actionLabels($, section).length) {
        return result("possible", "KADOKAWA 상품 구매 버튼 확인");
      }
    }
    return result("unknown", "KADOKAWA 긍정 문구 발견, 상품 구매 버튼은 미확인");
  }
  return result("unknown", "KADOKAWA 상품 주문 상태 신호 없음");
}

async function checkMaruzen($, url) {
  const response = await fetch(url.replace(/\/+$/, "") + ".js", {
    headers: HEADERS,
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new HTTPError(response.status);
  const data = await response.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return result("unknown", "마루젠 JSON 상품 데이터 형식 오류");
  }
  const title = String(data.title ?? "");
  if (!title.includes("ファミレス行こ") || !title.includes("アクリルスタンド付き特装版")) {
    return result("unknown", "마루젠 JSON 특장판 상품명 불일치");
  }
  const variants = data.variants;
  if (!Array.isArray(variants) || variants.length !== 1) {
    return result("unknown", "마루젠 상품 옵션 수가 달라짐; 수동 확인 필요");
  }
  const available = variants[0].available;
  if (typeof available !== "boolean") {
    return result("unknown", "마루젠 JSON 구매 가능 여부 없음");
  }
  const section = $(".product__info-container").get(0) || $(".product-form").get(0);
  const sectionText = normalizedText(section);
  // Confirmed in a real browser: when sold out, the cart button stays enabled
  // and the JSON still says available=true, but the net-store stock line
  // says one of these. It is the authoritative signal.
  const negatives = [
    "ネットストア在庫がありません", "お取り扱いできません",
  ].filter((x) => sectionText.includes(x));
  if (negatives.length) {
    return result("unavailable", "마루젠 넷스토어 재고 없음: " + negatives.join(", "));
  }
  const soldOut = ["売り切れ", "在庫切れ", "在庫なし"].some((x) => sectionText.includes(x));
  if (available && soldOut) {
    return result("unknown", "마루젠 JSON available=true, 상품 HTML 売り切れ: 상충");
  }
  if (available) return result("possible", "마루젠 상품 JSON available=true (주문 성공 미검증)");
  return result("unavailable", "마루젠 상품 JSON available=false");
}

// fetch().text() always assumes UTF-8; honour the page's declared charset
// (some Japanese stores still serve Shift_JIS / EUC-JP).
async function fetchHtml(url) {
  const response = await fetch(url, { headers: HEADERS, signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new HTTPError(response.status);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const head = new TextDecoder("latin1").decode(bytes.slice(0, 4096));
  const charset =
    (response.headers.get("content-type") || "").match(/charset=["']?([\w-]+)/i)?.[1] ||
    head.match(/<meta[^>]+charset=["']?([\w-]+)/i)?.[1] ||
    "utf-8";
  try {
    return new TextDecoder(charset).decode(bytes);
  } catch {
    return new TextDecoder("utf-8").decode(bytes);
  }
}

async function check(cfg) {
  try {
    const rawHtml = await fetchHtml(cfg.url);
    const $ = cheerio.load(rawHtml);
    $("script, style, noscript, svg").remove();
    const { checker } = cfg;
    let identified;
    if (checker === "kadokawa") {
      const text = normalizedText($.root()[0]);
      identified = text.includes(ISBN) || text.includes("アクリルスタンド付き特装版");
    } else {
      identified = productVerified($, rawHtml);
    }
    if (!identified) return result("unknown", "ISBN/특장판 상품명 검증 실패 (차단 또는 페이지 변경)");
    if (checker === "kadokawa") return checkKadokawa($);
    if (checker === "tower") return checkTower($);
    if (checker === "rakuten") return checkRakuten($);
    if (checker === "maruzen") return await checkMaruzen($, cfg.url);
    return result("unknown", "정의되지 않은 판매처 판별 방식");
  } catch (exc) {
    const accessError = exc instanceof HTTPError || exc instanceof SyntaxError ||
      exc.name === "TimeoutError" || exc.name === "TypeError";
    const reason = exc instanceof HTTPError ? exc.message : exc.name;
    return result("unknown", (accessError ? "접근/데이터 오류: " : "분석 오류: ") + reason);
  }
}

async function loadState() {
  try {
    const data = JSON.parse(await readFile(STATE, "utf-8"));
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch {
    return {};
  }
}

async function main() {
  const old = await loadState();
  for (const [name, cfg] of Object.entries(SITES)) {
    const { status, detail } = await check(cfg);
    const previous = old[name] && typeof old[name] === "object" ? old[name] : {};
    const alreadyAlerted = Boolean(
      previous.alerted_in_current_cycle ?? previous.status === "possible"
    );
    const note = status === "possible" && !alreadyAlerted ? "  ← GitHub에서 돌았다면 새 알림 대상" : "";
    console.log(`${name}: ${status} (${detail})${note}`);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

await main();
