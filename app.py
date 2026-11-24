import os,re,time,threading
from collections import OrderedDict
from urllib.parse import quote
import requests
from flask import Flask,request,jsonify
app=Flask(__name__)
BASE='https://cdn.plan.parts/api'
CACHE=OrderedDict(); LOCK=threading.Lock()
TRANSLATIONS={'airbag unit for steering wheel':'Vezetőoldali kormánylégzsák','titan black':'Titánfekete','airbag':'Légzsák','brake pads':'Fékbetétek','bumper':'Lökhárító'}
def normalize(q):
    q=q.strip().upper()
    if not re.fullmatch(r'[A-Z0-9 .-]{2,50}',q): raise ValueError('Érvénytelen cikkszám')
    return re.sub(r'[ .-]','',q)
def group(rows):
    items={}
    for a in rows:
        number=a['number']; brand=a['brand']; name=a['name']; key=(brand,number,name)
        item=items.setdefault(key,dict(brand=brand,number=number,description=TRANSLATIONS.get(name.lower(),name),original=name,oe=number,markets=[],has_replacements=False,discontinued_dates=[],color_code=number.split()[-1] if ' ' in number else ''))
        market=a.get('markt_name') or a.get('markt') or 'Nincs megadva'
        if market not in item['markets']: item['markets'].append(market)
        item['has_replacements'] |= bool(a.get('has_replacements'))
        if a.get('discontinued_date') and a['discontinued_date'] not in item['discontinued_dates']: item['discontinued_dates'].append(a['discontinued_date'])
    return list(items.values())
@app.get('/health')
def health(): return jsonify(configured=bool(os.getenv('PLAN_PARTS_API_KEY')))
@app.get('/oem')
def oem():
    try: q=normalize(request.args.get('q',''))
    except ValueError as e: return jsonify(error=str(e)),400
    token=os.getenv('PLAN_PARTS_API_KEY'); access=os.getenv('AUTORA_ACCESS_TOKEN')
    if not token or not access: return jsonify(error='Szerver nincs beállítva'),503
    import hmac
    if not hmac.compare_digest(request.headers.get('X-Autora-Token',''),access): return jsonify(error='Hozzáférés megtagadva'),401
    brand=request.args.get('brand',''); market=request.args.get('market','')
    with LOCK:
        cached=CACHE.get(q); hit=bool(cached and time.monotonic()-cached[0]<900)
        if hit: items,count=cached[1:]
        else:
            try:
                r=requests.get(BASE+'/v1/vag/part/'+quote(q,safe=''),params={'lang':'EN'},headers={'Authorization':'Bearer '+token,'Accept':'application/json'},timeout=15,allow_redirects=False)
                p=r.json()
                if p.get('error',{}).get('code')=='NOT_FOUND': items,count=[],0
                else:
                    if r.status_code!=200 or not p.get('success'): return jsonify(error='Katalógushiba',upstream_status=r.status_code),502
                    rows=p['data']['results']; items=group(rows); count=p['data']['count']
                CACHE[q]=(time.monotonic(),items,count); CACHE.move_to_end(q)
                while len(CACHE)>256: CACHE.popitem(last=False)
            except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError): return jsonify(error='Katalógus nem elérhető'),502
    return jsonify(items=[a for a in items if (not brand or a['brand']==brand) and (not market or market in a['markets'])],raw_count=count,cached=hit)
