import json, os, re, time
from pathlib import Path
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

ISBN='9784047377486'
PRODUCT='ファミレス行こ。 上 アクリルスタンド付き特装版'
SITES={
 'KADOKAWA': {'url':'https://store.kadokawa.co.jp/shop/g/g322308000883/', 'negative':['在庫がありません','在庫なし'], 'positive':['カートに入れる','在庫あり','お取り寄せ']},
 'Animate': {'url':'https://www.animate-onlineshop.jp/pd/2326011/', 'negative':['販売終了','在庫なし'], 'positive':['カートに入れる','予約受付中','取り寄せ']},
 'Kinokuniya': {'url':'https://www.kinokuniya.co.jp/f/dsg-01-9784047377486', 'negative':['ご注文を受け付けておりません'], 'positive':['カートに入れる','ご注文いただけます','取り寄せ']},
 'Maruzen Junkudo': {'url':'https://www.maruzenjunkudo.co.jp/products/9784047377486', 'negative':['売り切れ','在庫切れ','在庫なし'], 'positive':['カートに追加する','カートに入れる','購入する']},
}
STATE=Path('state.json')
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; PersonalStockMonitor/1.0; +https://github.com/)','Accept-Language':'ja-JP,ja;q=0.9'}

def check(name, cfg):
    try:
        r=requests.get(cfg['url'], headers=HEADERS, timeout=18)
        r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        for x in soup(['script','style','noscript','svg']): x.decompose()
        # Only examine visible text; script data and meta descriptions can mislead.
        text=' '.join(soup.stripped_strings)
        if ISBN not in text and 'アクリルスタンド付き特装版' not in text:
            return {'status':'unknown','detail':'상품 식별 정보 확인 불가 (차단/렌더링 가능성)'}
        negatives=[x for x in cfg['negative'] if x in text]
        positives=[x for x in cfg['positive'] if x in text]
        # Conservative: conflicting evidence must not be called in-stock.
        if negatives and positives:
            return {'status':'unknown','detail':'상충하는 문구: '+', '.join((negatives+positives)[:4])}
        if negatives:
            return {'status':'unavailable','detail':', '.join(negatives)}
        if positives:
            return {'status':'possible','detail':', '.join(positives)}
        return {'status':'unknown','detail':'구매 상태 문구 식별 불가'}
    except Exception as e:
        return {'status':'unknown','detail':f'접근 실패: {type(e).__name__}'}

def main():
    old=json.loads(STATE.read_text()) if STATE.exists() else {}
    updated={}
    alerts=[]
    for name,cfg in SITES.items():
        result=check(name,cfg)
        status=result['status']
        prev=old.get(name,{}).get('status')
        print(f'{name}: {status} ({result["detail"]})')
        # A newly detected possible purchase, including after previous unknown, is notified.
        if status=='possible' and prev!='possible':
            alerts.append({'name':name,'url':cfg['url'],'detail':result['detail']})
        updated[name]={'status':status,'detail':result['detail']}
        time.sleep(1)
    STATE.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n')
    Path('alerts.json').write_text(json.dumps(alerts,ensure_ascii=False,indent=2)+'\n')
    if alerts:
        print('ALERTS: '+json.dumps(alerts,ensure_ascii=False))

if __name__=='__main__': main()
