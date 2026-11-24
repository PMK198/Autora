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
    token=os.getenv('PLAN_PARTS_API_KEY','').strip(); access=os.getenv('AUTORA_ACCESS_TOKEN')
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

# V4: explicitly requested, authenticated catalogue operations.
EXTRA_CACHE=OrderedDict(); EXTRA_LOCK=threading.Lock()
@app.post('/catalog/<action>')
def catalog(action):
    import hmac
    access=os.getenv('AUTORA_ACCESS_TOKEN',''); token=os.getenv('PLAN_PARTS_API_KEY','').strip()
    if not access or not token: return jsonify(error='Szerver nincs beállítva'),503
    if not hmac.compare_digest(request.headers.get('X-Autora-Token','').encode(),access.encode()): return jsonify(error='Hozzáférés megtagadva'),401
    d=request.get_json(silent=True) or {}; params={}
    try:
        if action=='vin':
            vin=str(d.get('vin','')).strip().upper()
            if not re.fullmatch('[A-HJ-NPR-Z0-9]{17}',vin): raise ValueError('Érvénytelen VIN')
            if d.get('confirm') is not True: raise ValueError('50 token jóváhagyása szükséges')
            path='/v1/vag/vin/'+vin
        elif action=='vehicles':
            path='/v1/vag/vehicles'; params={'catalog':d.get('catalog'),'limit':100,'model':str(d.get('model',''))[:80],'year':str(d.get('year','')),'q':str(d.get('q',''))[:100]}
            if not params['model'] and not params['q']: raise ValueError('Adj meg modellt')
            if params['year'] and not re.fullmatch('[0-9]{4}',params['year']): raise ValueError('Érvénytelen évjárat')
        elif action in ('groups','subgroups','parts'):
            ident=int(d['epis_typ']); path=f'/v1/vag/vehicle/{ident}/{action}'; params={'catalog':d.get('catalog'),'lang':'EN'}
            if action=='subgroups': params['hg']=int(d['hg'])
            if action=='parts':
                params.update(hg_ug=str(d['hg_ug'])[:30],bildtafel2=int(d['bildtafel2']))
        elif action in ('supersessions','cross','fitment','images','price'):
            path='/v1/vag/part/'+quote(normalize(str(d.get('number',''))),safe='')+'/'+('vehicles' if action=='fitment' else action)
        elif action=='aftermarket':
            path='/v1/aftermarket/search'; params={'q':normalize(str(d.get('number',''))),'type':'OEM'}
        else: return jsonify(error='Ismeretlen művelet'),404
        if 'catalog' in params and params['catalog'] not in ('VW','AU','SK','SE','PO','ML'): raise ValueError('Érvénytelen katalógus')
        params={k:v for k,v in params.items() if v!=''}
    except (ValueError,KeyError,TypeError) as e: return jsonify(error=str(e)),400
    key=(path,tuple(sorted(params.items())))
    with EXTRA_LOCK:
        previous=EXTRA_CACHE.get(key) if action!='vin' else None
        if previous and time.monotonic()-previous[0]<900: return jsonify(data=previous[1],cached=True)
        try:
            r=requests.get(BASE+path,params=params,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},timeout=45,allow_redirects=False)
            if r.status_code!=200: return jsonify(error='Plan.parts HTTP '+str(r.status_code)),502
            p=r.json()
            if not isinstance(p,dict) or not p.get('success'): return jsonify(error='A katalógus nem adott sikeres választ'),502
            data=p['data']
            if action!='vin':
                EXTRA_CACHE[key]=(time.monotonic(),data)
                while len(EXTRA_CACHE)>256: EXTRA_CACHE.popitem(last=False)
            return jsonify(data=data,cached=False)
        except (requests.RequestException,ValueError,KeyError) as e: return jsonify(error='Katalógushiba: '+type(e).__name__),502

WEB_PAGE=WEB_PAGE.replace('3.2 ·','4.1 PRO ·').replace('</main>',r'''<section><h2>Jármű és VIN keresés</h2><label>Márka</label><select id="cat"><option value="VW">Volkswagen</option><option value="AU">Audi</option><option value="SK">Škoda</option><option value="SE">SEAT</option><option value="PO">Porsche</option></select><label><input id="europe" type="checkbox" style="width:auto" checked> RDW / helyi katalógus előnyben (más piacok elrejtése)</label><label>Modell</label><input id="model" placeholder="Golf"><label>Évjárat</label><input id="year" type="number" placeholder="2017"><label>Motor / szabad keresés</label><input id="motor" placeholder="1.6 TDI"><button id="vehicles">Jármű keresése · 1 token</button><label>Alvázszám (VIN)</label><input id="vin" maxlength="17"><button id="vinGo">VIN keresése · 50 token</button><div id="vehicleResults"></div></section><section><h2>OEM részletes adatok</h2><label>Cikkszám (a fenti OEM mezőből)</label><div id="detailButtons"></div><div id="details"></div></section><p><small>A járműkatalógus nem igazolja minden felszereltségi változat kompatibilitását. VIN-t a szolgáltatónak továbbítjuk; nem mentjük helyben. A tokenárak a szolgáltató dokumentációja szerintiek.</small></p></main>''')+r'''<script>
const vout=$('vehicleResults'), dout=$('details');
function btn(parent,label,fn){const b=el('button',label);b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn()}finally{b.disabled=false}};parent.append(b)}
async function call(action,payload,out){out.replaceChildren(el('p','Lekérdezés folyamatban…'));try{const r=await fetch('/catalog/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Autora-Token':$('token').value},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.error);out.replaceChildren();return d.data}catch(e){out.replaceChildren(el('p','Hiba: '+e.message));return null}}
function raw(out,d){const p=el('pre',JSON.stringify(d,null,2));p.style.whiteSpace='pre-wrap';p.style.overflowWrap='anywhere';out.append(p)}
function rows(d){return Array.isArray(d)?d:Array.isArray(d?.results)?d.results:[]}
function vehicles(d,cat){const list=Array.isArray(d)||Array.isArray(d?.results)?rows(d):[d];for(const x of list.filter(x=>!$('europe').checked||!x.markt||x.markt==='RDW')){const a=el('article','');a.append(el('h2',x.name||x.model||'Jármű'));a.append(el('p',[x.brand,x.year_from,x.vbz,x.markt_name||x.markt].filter(Boolean).join(' · ')));if(x.epis_typ)btn(a,'Alkatrészcsoportok · 1 token',()=>groups(x.epis_typ,x.catalog||cat));vout.append(a)}}
async function groups(id,cat){const d=await call('groups',{epis_typ:id,catalog:cat},vout);if(!d)return;for(const x of rows(d))btn(vout,tr(x.name||x.hg),()=>subs(id,cat,x.hg));if(!rows(d).length)raw(vout,d)}
async function subs(id,cat,hg){const d=await call('subgroups',{epis_typ:id,catalog:cat,hg},vout);if(!d)return;btn(vout,'Vissza a csoportokhoz',()=>groups(id,cat));for(const x of rows(d))btn(vout,tr(x.name||x.hg_ug)+' · 2 token',()=>parts(id,cat,hg,x));if(!rows(d).length)raw(vout,d)}
async function parts(id,cat,hg,x){const d=await call('parts',{epis_typ:id,catalog:cat,hg_ug:x.hg_ug,bildtafel2:x.bildtafel2},vout);if(!d)return;btn(vout,'Vissza az alcsoportokhoz',()=>subs(id,cat,hg));partTable(vout,rows(d));if(d.schemas)showSchemas(vout,d.schemas,cat);if(!rows(d).length)raw(vout,d)}
$('vehicles').onclick=async()=>{const d=await call('vehicles',{catalog:$('cat').value,model:$('model').value,year:$('year').value,q:$('motor').value},vout);if(d)vehicles(d,$('cat').value)};
$('vinGo').onclick=async()=>{if(!confirm('Ez a lekérdezés 50 tokent fogyaszthat. Folytatod?'))return;const d=await call('vin',{vin:$('vin').value,confirm:true},vout);if(d)vehicles(d,$('cat').value)};
for(const [a,l] of [['supersessions','Gyári utód- és elődszámok · 1 token'],['cross','Kereszthivatkozások · 2 token'],['fitment','Katalógus szerinti járművek · 1 token'],['images','Kép- és ábraadatok · 1 token'],['price','Gyári ár · 1 token'],['aftermarket','Utángyártott katalógus · 2 token']])btn($('detailButtons'),l,async()=>{const d=await call(a,{number:$('q').value},dout);if(d)detailView(a,d)});
</script>'''

# 4.1: fixed upstream host, authenticated diagram conversion, bounded payload.
@app.post('/diagram')
def diagram():
    import hmac, io
    from flask import send_file
    from PIL import Image
    access=os.getenv('AUTORA_ACCESS_TOKEN',''); token=os.getenv('PLAN_PARTS_API_KEY','').strip()
    if not access or not token: return jsonify(error='Szerver nincs beállítva'),503
    if not hmac.compare_digest(request.headers.get('X-Autora-Token','').encode(),access.encode()): return jsonify(error='Hozzáférés megtagadva'),401
    d=request.get_json(silent=True) or {}; cat=d.get('catalog'); file=str(d.get('file',''))
    if cat not in ('VW','AU','SK','SE','PO','ML') or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',file): return jsonify(error='Érvénytelen ábraazonosító'),400
    try:
        with requests.get('https://plan.parts/api/v1/vag/schema',params={'c':cat,'f':file,'t':'TIF'},headers={'Authorization':'Bearer '+token},timeout=30,stream=True,allow_redirects=False) as r:
            if r.status_code!=200: return jsonify(error='Ábra HTTP '+str(r.status_code)),502
            buf=bytearray()
            for chunk in r.iter_content(65536):
                buf.extend(chunk)
                if len(buf)>12000000: return jsonify(error='Túl nagy ábra'),502
        with Image.open(io.BytesIO(buf)) as im:
            if im.width*im.height>25000000: return jsonify(error='Túl nagy képméret'),502
            im.thumbnail((2400,2400)); out=io.BytesIO(); im.convert('RGB').save(out,'PNG'); out.seek(0)
        response=send_file(out,mimetype='image/png',max_age=0); response.headers['Cache-Control']='no-store'; return response
    except (requests.RequestException,OSError,ValueError,Image.DecompressionBombError) as e: return jsonify(error='Ábrahiba: '+type(e).__name__),502

WEB_PAGE += r'''<style>main{max-width:1100px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:10px;border-bottom:1px solid #52617a;text-align:left}td button{margin:0;padding:8px} .scrolltable{overflow:auto} .diagram{overflow:auto;background:white;border-radius:8px;max-height:75vh}.diagram img{display:block;max-width:none} .muted{color:#b9c8df} pre{font-size:12px} </style><script>
const dict={'engine':'Motor','fuel, exhaust, cooling':'Üzemanyag, kipufogó, hűtés','gearbox':'Sebességváltó','front axle, steering':'Első futómű, kormányzás','rear axle':'Hátsó futómű','wheels, brakes':'Kerekek, fékek','pedals':'Pedálok','body':'Karosszéria','electrics':'Elektromos rendszer','access.,infotainment,miscell.':'Tartozékok, multimédia','wing':'Sárvédő','bonnet':'Motorháztető','underbody trim':'Alsó burkolat','rear lid':'Csomagtérajtó','doors':'Ajtók','door lock':'Ajtózár','window regulator':'Ablakemelő','window glasses':'Ablaküvegek','radiator grille':'Hűtőrács','bumper':'Lökhárító','bumper cover':'Lökhárítóburkolat','side reinforcement':'Oldalsó merevítő','primed':'Alapozott kivitel','front':'Első','rear':'Hátsó','hexagon collar nut self-locking':'Önzáró peremes hatlapú anya','hexagon collar bolt with socket head':'Peremes belső kulcsnyílású csavar'};
function tr(s){return dict[String(s||'').toLowerCase()]||String(s||'')}
const chosen=new Map();
function partTable(out,list){const unique=[...new Map(list.map(a=>[JSON.stringify(a),a])).values()];const filter=el('input','');filter.placeholder='Szűrés név, OEM vagy pozíció alapján';out.append(filter);const wrap=el('div','','scrolltable');out.append(wrap);const compare=el('div','');out.append(compare);function draw(){wrap.replaceChildren();const t=el('table',''),h=el('tr','');for(const x of ['Poz.','OEM','Megnevezés / megjegyzés','Db','Művelet'])h.append(el('th',x));t.append(h);for(const a of unique.filter(a=>[a.number,a.name,tr(a.name),a.position,a.note].join(' ').toLowerCase().includes(filter.value.toLowerCase()))){const r=el('tr','');for(const x of [a.position??'–',a.number||'–',tr(a.name)+(a.note?' · '+tr(a.note):''),a.qty??'–'])r.append(el('td',String(x)));const c=el('td','');if(a.number){btn(c,'OEM',()=>{$('q').value=a.number;$('q').scrollIntoView()});btn(c,'Összevetés',()=>{chosen.set(a.number,a);compare.replaceChildren(el('h2','Kiválasztott cikkszámok'));for(const v of chosen.values())compare.append(el('p',v.number+' · '+tr(v.name)+' · '+(v.note||'')));compare.append(el('small','A hasonló cikkszám nem igazolt helyettesítő.'));btn(compare,'Lista törlése',()=>{chosen.clear();compare.replaceChildren()})})}r.append(c);t.append(r)}wrap.append(t)}filter.oninput=draw;draw()}
function showSchemas(out,schemas,cat){for(const x of (Array.isArray(schemas)?schemas:[])){if(!x.file)continue;const a=el('article','');a.append(el('h2','Gyári robbantott ábra · '+x.file));out.prepend(a);btn(a,'Ábra betöltése (külön API-lekérés)',async()=>{try{const r=await fetch('/diagram',{method:'POST',headers:{'Content-Type':'application/json','X-Autora-Token':$('token').value},body:JSON.stringify({catalog:cat,file:x.file})});if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob());const box=el('div','','diagram'),img=el('img','');img.alt='Gyári műszaki rajz';img.src=url;img.onload=()=>URL.revokeObjectURL(url);img.style.width='100%';box.append(img);a.append(box);const z=el('input','');z.type='range';z.min=50;z.max=300;z.value=100;z.oninput=()=>img.style.width=z.value+'%';a.append(el('p','Nagyítás'),z)}catch(e){a.append(el('p',e.message))}})}}
function detailView(action,d){if(action==='supersessions'){for(const [k,l] of [['predecessors','Gyári elődszámok'],['successors','Gyári utódszámok']]){dout.append(el('h2',l));const list=d[k];if(!Array.isArray(list)||!list.length)dout.append(el('p','Nincs visszaadott adat – ez nem bizonyítja, hogy nincs helyettesítő.'));else for(const v of list)dout.append(el('p',typeof v==='string'?v:JSON.stringify(v)))}return}const list=rows(d);if(list.length){for(const x of list){const a=el('article','');for(const [k,v] of Object.entries(x))a.append(el('p',k+': '+(typeof v==='object'?JSON.stringify(v):v)));dout.append(a)}}else if(Array.isArray(d.results))dout.append(el('p','A katalógus nem adott találatot.'));else raw(dout,d)}
</script>'''
