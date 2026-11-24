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
                app.logger.warning('Plan.parts HTTP status=%s content_type=%s', r.status_code, r.headers.get('Content-Type','unknown'))
                if r.status_code in (401,403,429):
                    return jsonify(error='Plan.parts HTTP '+str(r.status_code)+' – ellenőrizd a kulcsot, jogosultságot vagy kvótát'),502
                try: p=r.json()
                except ValueError: return jsonify(error='Plan.parts nem JSON választ adott (HTTP '+str(r.status_code)+')'),502
                if (p.get('error') or {}).get('code')=='NOT_FOUND': items,count=[],0
                else:
                    if r.status_code!=200 or not p.get('success'): return jsonify(error='Katalógushiba (HTTP '+str(r.status_code)+')',upstream_status=r.status_code),502
                    rows=p['data']['results']; items=group(rows); count=p['data']['count']
                CACHE[q]=(time.monotonic(),items,count); CACHE.move_to_end(q)
                while len(CACHE)>256: CACHE.popitem(last=False)
            except requests.RequestException as e:
                app.logger.warning('Plan.parts connection error: %s',type(e).__name__)
                return jsonify(error='Plan.parts kapcsolati hiba: '+type(e).__name__),502
            except (ValueError,KeyError,TypeError,AttributeError) as e:
                app.logger.warning('Plan.parts data error: %s',type(e).__name__)
                return jsonify(error='Katalógus adatfeldolgozási hiba: '+type(e).__name__),502
    return jsonify(items=[a for a in items if (not brand or a['brand']==brand) and (not market or market in a['markets'])],raw_count=count,cached=hit)

@app.get('/')
def home():
    from flask import make_response
    response=make_response(WEB_PAGE)
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    return response

WEB_PAGE = r'''<!doctype html><html lang="hu"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AUTORA – OEM kereső</title><style>
*{box-sizing:border-box}body{margin:0;background:#101827;color:#edf2ff;font:16px system-ui}main{max-width:800px;margin:auto;padding:24px}h1{font-size:36px;margin:0;color:#7db6ff}p{line-height:1.5;color:#b9c8df}section,article{background:#1e293b;border:1px solid #34445d;border-radius:16px;padding:20px;margin:16px 0}label{display:block;margin:12px 0 6px}input,select,button{width:100%;padding:13px;border-radius:9px;border:1px solid #52617a;background:#101827;color:white;font:inherit}button{background:#2563eb;border:0;font-weight:bold;margin-top:16px;cursor:pointer}button:disabled{opacity:.5}small{color:#b9c8df}h2{font-size:20px;margin:0 0 8px}a{color:#93c5fd}.number{color:#93c5fd;font-size:20px;font-weight:bold}.filters{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:480px){.filters{grid-template-columns:1fr}} </style><main><h1>AUTORA</h1><p>3.2 · Gyári OEM alkatrészkereső · VAG katalógus</p><section><form id="search"><label for="token">AUTORA hozzáférési kód</label><input id="token" type="password" autocomplete="off" required placeholder="A Renderben beállított külön kód"><small>Nem a Plan.parts API-kulcs. A kódot nem mentjük el.</small><label for="q">OEM cikkszám</label><input id="q" required maxlength="50" placeholder="Pl. 5G0880201Q"><button id="go">Alkatrész keresése</button></form></section><p id="status" role="status" aria-live="polite"></p><section id="filters" hidden><div class="filters"><div><label for="brand">Márka</label><select id="brand"></select></div><div><label for="market">Piac</label><select id="market"></select></div></div></section><div id="results"></div><p><small>Forrás: Plan.parts. A katalógustalálat nem igazolja a járművel való kompatibilitást. A fordítás részleges. A gyorsítótár 15 percig él a szerveren.</small></p></main><script>
const $=id=>document.getElementById(id);let items=[];const el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n};function options(id,values){const s=$(id);s.replaceChildren(new Option('Összes',''));for(const v of [...new Set(values)].sort())s.add(new Option(v,v))}function render(){const out=$('results');out.replaceChildren();const rows=items.filter(x=>(!$('brand').value||x.brand===$('brand').value)&&(!$('market').value||x.markets.includes($('market').value)));if(!rows.length)out.append(el('p','Nincs találat a kiválasztott feltételekkel.'));for(const x of rows){const a=el('article','');a.append(el('h2',x.description),el('div',x.number,'number'),el('p',x.brand+' · '+x.original),el('p','Piacok: '+x.markets.join(', ')),el('p','Színkód: '+(x.color_code||'Nincs megadva')),el('p','Helyettesítő: '+(x.has_replacements?'Jelölve a katalógusban':'Nincs megjelölve')),el('p','Megszüntetési dátum: '+(x.discontinued_dates.join(', ')||'Nincs megadva')));const link=el('a','Eladó alkatrészek keresése');link.href='https://www.google.com/search?q='+encodeURIComponent(x.number);link.target='_blank';link.rel='noopener noreferrer';a.append(link);out.append(a)}}$('brand').onchange=render;$('market').onchange=render;$('search').onsubmit=async e=>{e.preventDefault();$('go').disabled=true;$('status').textContent='Keresés folyamatban… Az ingyenes szerver ébredése időbe telhet.';$('results').replaceChildren();$('filters').hidden=true;try{const r=await fetch('/oem?'+new URLSearchParams({q:$('q').value}),{headers:{'X-Autora-Token':$('token').value},cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'HTTP '+r.status);items=d.items;options('brand',items.map(x=>x.brand));options('market',items.flatMap(x=>x.markets));$('filters').hidden=!items.length;$('status').textContent=d.raw_count+' katalógusbejegyzés · '+items.length+' összevont találat'+(d.cached?' · Gyorsítótárból':'');render()}catch(err){$('status').textContent='Hiba: '+err.message}finally{$('go').disabled=false}};
</script></html>'''
