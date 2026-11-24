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
            im.thumbnail((2400,2400)); im=im.convert('RGB');
            from PIL import ImageChops
            bounds=ImageChops.difference(im,Image.new('RGB',im.size,'white')).convert('L').point(lambda v: 255 if v>35 else 0).getbbox()
            if bounds:
                l,t,r,b=bounds; im=im.crop((max(0,l-12),max(0,t-12),min(im.width,r+12),min(im.height,b+12)))
            out=io.BytesIO(); im.save(out,'PNG'); out.seek(0)
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

# 5.0: additive UI; existing API contracts retained.
WEB_PAGE=WEB_PAGE.replace('4.1 PRO ·','5.0 PRO ·')
WEB_PAGE += r'''<style>
main{max-width:1500px}.workspace{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}.workspace article{margin:0;padding:12px}.workspace .scrolltable{max-height:70vh}.workspace th{position:sticky;top:0;background:#26364d}.tools{display:flex;gap:8px;flex-wrap:wrap}.tools button{width:auto;margin:4px 0}.diagram img{cursor:grab;user-select:none}.diagram{max-height:70vh}.workspace td button{margin:3px 0}.workspace :fullscreen{background:#fff}.savedrow{display:flex;gap:8px;align-items:center}.savedrow button{width:auto;margin:4px} @media(max-width:850px){.workspace{grid-template-columns:1fr}}
</style><script>
Object.assign(dict,{'airbag':'Légzsák','airbag unit for steering wheel':'Vezetőoldali kormánylégzsák','radiator':'Hűtő','coolant pump':'Hűtőfolyadék-szivattyú','headlight':'Fényszóró','brake disc':'Féktárcsa','brake pads':'Fékbetétek','screw':'Csavar','washer':'Alátét','nut':'Anya','hinge':'Zsanér','seal':'Tömítés','clip':'Patent','support':'Tartó','cover':'Burkolat','left':'Bal','right':'Jobb','rear bumper':'Hátsó lökhárító','front bumper':'Első lökhárító'});
function readLocal(k){try{const v=JSON.parse(localStorage.getItem('autora5:'+k)||'[]');return Array.isArray(v)?v:[]}catch{return []}}
function saveLocal(k,v){try{localStorage.setItem('autora5:'+k,JSON.stringify(v.slice(0,100)));return true}catch{alert('A helyi mentés nem elérhető.');return false}}
function remember(k,v){saveLocal(k,[v,...readLocal(k).filter(x=>JSON.stringify(x)!==JSON.stringify(v))]);drawSaved()}
const saved=el('section','');document.querySelector('main').append(saved);
function drawSaved(){saved.replaceChildren(el('h2','Saját katalógus'));for(const [k,label] of [['parts','Kedvenc alkatrészek'],['cars','Mentett járművek'],['history','OEM keresési előzmények']]){saved.append(el('h3',label));for(const x of readLocal(k)){const r=el('div','','savedrow');r.append(el('span',typeof x==='string'?x:[x.catalog,x.model,x.year].join(' · ')));btn(r,'Megnyitás',()=>{if(k==='cars'){for(const [id,key] of [['cat','catalog'],['model','model'],['year','year'],['motor','motor']])$(id).value=x[key]||'';$('cat').scrollIntoView()}else{$('q').value=x;$('q').scrollIntoView()}});btn(r,'Törlés',()=>{saveLocal(k,readLocal(k).filter(y=>JSON.stringify(y)!==JSON.stringify(x)));drawSaved()});saved.append(r)}btn(saved,'Lista ürítése',()=>{saveLocal(k,[]);drawSaved()})}saved.append(el('small','Csak ezen a böngészőn tároljuk; VIN és hozzáférési kód nélkül.'))}drawSaved();
$('search').addEventListener('submit',()=>{const q=$('q').value.trim().toUpperCase();if(q)remember('history',q)});
btn($('vehicles').parentNode,'Jármű mentése',()=>{if($('model').value.trim())remember('cars',{catalog:$('cat').value,model:$('model').value,year:$('year').value,motor:$('motor').value})});
const usage=el('p','API-hívások ebben a munkamenetben: 0');document.querySelector('main').prepend(usage);let calls=0;const originalFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const r=await originalFetch(...args);if(/^\/(oem\?|catalog\/|diagram$)/.test(String(args[0]))){calls++;usage.textContent='API-kérések ebben a munkamenetben: '+calls+' (nem számlázott tokenegyenleg)'}return r};
parts=async function(id,cat,hg,x){const d=await call('parts',{epis_typ:id,catalog:cat,hg_ug:x.hg_ug,bildtafel2:x.bildtafel2},vout);if(!d)return;btn(vout,'Vissza az alcsoportokhoz',()=>subs(id,cat,hg));vout.append(el('h2',tr(x.name||x.hg_ug)));const w=el('div','','workspace'),left=el('div',''),right=el('div','');w.append(left,right);vout.append(w);const list=rows(d);partTable(right,list);if(d.schemas)showSchemas(left,d.schemas,cat);else left.append(el('p','Nincs visszaadott ábra.'));if(!list.length)raw(right,d)};
partTable=function(out,list){const filter=el('input','');filter.placeholder='Alkatrész neve, OEM vagy pozíció';out.append(filter);const positions=el('select','');positions.add(new Option('Minden pozíció',''));const pos=a=>String(a.position??'').replace(/[()]/g,'').trim();for(const p of [...new Set(list.map(pos).filter(Boolean))])positions.add(new Option(p,p));out.append(positions);const wrap=el('div','','scrolltable');out.append(wrap);const compare=el('div','');out.append(compare);function draw(){wrap.replaceChildren();const t=el('table',''),h=el('tr','');for(const s of ['Poz.','OEM','Alkatrész / megjegyzés','Db','Művelet'])h.append(el('th',s));t.append(h);for(const a of list.filter(a=>(!positions.value||pos(a)===positions.value)&&[a.number,a.name,tr(a.name),a.note].join(' ').toLowerCase().includes(filter.value.toLowerCase()))){const r=el('tr','');for(const s of [a.position??'–',a.number||'–',tr(a.name)+(a.note?' · '+tr(a.note):''),a.qty??'–'])r.append(el('td',String(s)));const c=el('td','');if(a.number){btn(c,'OEM',()=>{$('q').value=a.number;$('q').scrollIntoView()});btn(c,'★',()=>remember('parts',a.number));btn(c,'Összevetés',()=>{chosen.set(a.number,a);compare.replaceChildren(el('h3','Összehasonlítás'));for(const v of chosen.values())compare.append(el('p',v.number+' · '+tr(v.name)+' · '+(v.note||'')));compare.append(el('small','Nem igazolt helyettesítők.'));btn(compare,'Törlés',()=>{chosen.clear();compare.replaceChildren()})})}r.append(c);t.append(r)}wrap.append(t)}filter.oninput=positions.onchange=draw;draw()};
showSchemas=function(out,schemas,cat){for(const x of Array.isArray(schemas)?schemas:[]){if(!x.file)continue;const a=el('article','');out.append(a);a.append(el('h2','Gyári ábra · '+x.file));let loaded=false;btn(a,'Ábra betöltése',async()=>{if(loaded)return;try{const r=await fetch('/diagram',{method:'POST',headers:{'Content-Type':'application/json','X-Autora-Token':$('token').value},body:JSON.stringify({catalog:cat,file:x.file})});if(!r.ok)throw Error((await r.json()).error);const box=el('div','','diagram'),img=el('img','');img.alt='Gyári robbantott ábra';const url=URL.createObjectURL(await r.blob());img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>URL.revokeObjectURL(url);img.src=url;img.style.width='100%';img.draggable=false;box.append(img);a.append(box);const z=el('input','');z.type='range';z.min=50;z.max=400;z.value=100;z.oninput=()=>img.style.width=z.value+'%';a.append(el('p','Nagyítás'),z);const tools=el('div','','tools');a.append(tools);btn(tools,'Teljes képernyő',async()=>{try{await box.requestFullscreen()}catch{alert('A böngésző nem támogatja.')}});btn(tools,'Alaphelyzet',()=>{z.value=100;z.oninput();box.scrollTo(0,0)});let drag=null;box.onpointerdown=e=>{if(e.pointerType==='touch')return;drag=[e.clientX,e.clientY,box.scrollLeft,box.scrollTop];box.setPointerCapture(e.pointerId)};box.onpointermove=e=>{if(drag){box.scrollLeft=drag[2]+drag[0]-e.clientX;box.scrollTop=drag[3]+drag[1]-e.clientY}};box.onpointerup=box.onpointercancel=()=>drag=null;loaded=true;a.append(el('small','A rajzon olvasható számot válaszd ki a jobb oldali pozíciólistából.'))}catch(e){a.append(el('p','Hiba: '+e.message))}})}};
</script>'''

WEB_PAGE=WEB_PAGE.replace('5.0 PRO ·','5.1 PRO ·')
WEB_PAGE += r'''<style>
.workspace .diagram{max-height:75vh;touch-action:none}.workspace .diagram img{margin:auto;transform-origin:top left}.workspace td:last-child{min-width:105px}.workspace td button{display:inline-block;width:auto;min-width:32px;margin:2px;padding:7px}.workspace tr:hover{background:#293b54}.workspace tr.selected{background:#284b76}.workspace .scrolltable{max-height:75vh}.workspace article{border-radius:12px}.positionchips{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0}.positionchips button{width:auto;margin:0;padding:6px 10px}.positionchips button.active{background:#0e7490}.workspace .diagram:fullscreen{max-height:none}.workspace td a{display:inline-block;padding:5px} </style><script>
Object.assign(dict,{'cross member':'Kereszttartó','crossmember':'Kereszttartó','reinforcement':'Merevítő','bracket':'Konzol','guide profile':'Vezetőprofil','spoiler':'Légterelő','retaining clip':'Rögzítőpatent','impact absorber':'Ütközéselnyelő','bumper reinforcement':'Lökhárító-merevítő','wheel housing':'Kerékjárati burkolat'});
const stableKey=a=>JSON.stringify(Object.keys(a).sort().map(k=>[k,a[k]]));
const pos51=a=>String(a.position??'').replace(/[()]/g,'').trim();
partTable=function(out,list){
 const unique=[...new Map(list.map(a=>[stableKey(a),a])).values()];
 const filter=el('input','');filter.placeholder='Alkatrész neve, OEM vagy pozíció';out.append(filter);
 const positions=el('select','');positions.add(new Option('Minden pozíció',''));const ps=[...new Set(unique.map(pos51).filter(Boolean))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));for(const p of ps)positions.add(new Option(p,p));out.append(positions);
 const count=el('p','');out.append(count);const wrap=el('div','','scrolltable');out.append(wrap);const compare=el('div','');out.append(compare);const selection=new Map();
 function drawCompare(){compare.replaceChildren(el('h3','Összehasonlítás'));const t=el('table','');for(const v of selection.values()){const r=el('tr','');for(const x of [v.number,tr(v.name),v.position??'–',v.note||'–'])r.append(el('td',String(x)));t.append(r)}compare.append(t,el('small','Nem igazolt helyettesítők. A gyári utód- és elődszámokat külön ellenőrizd.'));btn(compare,'Törlés',()=>{selection.clear();compare.replaceChildren()})}
 function draw(){wrap.replaceChildren();const t=el('table',''),h=el('tr','');for(const s of ['Poz.','OEM','Alkatrész / megjegyzés','Db','Művelet'])h.append(el('th',s));t.append(h);const q=filter.value.toLowerCase();const visible=unique.filter(a=>(!positions.value||pos51(a)===positions.value)&&[a.number,a.name,tr(a.name),a.note,a.position].join(' ').toLowerCase().includes(q));count.textContent=visible.length+' találat · '+(list.length-unique.length)+' pontos ismétlés összevonva';for(const a of visible){const r=el('tr','',positions.value?'selected':'');for(const s of [a.position??'–',a.number||'–',tr(a.name)+(a.note?' · '+tr(a.note):''),a.qty??'–'])r.append(el('td',String(s)));const c=el('td','');if(a.number){btn(c,'OEM',()=>{$('q').value=a.number;$('q').scrollIntoView()});btn(c,'★',()=>remember('parts',a.number));btn(c,'⇄',()=>{selection.set(stableKey(a),a);drawCompare()});c.lastChild.title='Összehasonlítás';const link=el('a','↗');link.title='Eladó alkatrész keresése';link.href='https://www.google.com/search?q='+encodeURIComponent(a.number);link.target='_blank';link.rel='noopener noreferrer';c.append(link);btn(c,'i',()=>{const info=el('pre','');info.textContent=JSON.stringify(a,null,2);const old=r.nextSibling;if(old?.classList.contains('partinfo')){old.remove();return}const rr=el('tr','','partinfo'),cc=el('td','');cc.colSpan=5;cc.append(info);rr.append(cc);r.after(rr)});c.lastChild.title='Összes katalógusadat'}r.append(c);t.append(r)}wrap.append(t)}
 filter.oninput=positions.onchange=draw;out.parentNode.positionPicker=p=>{positions.value=p;filter.value='';draw()};out.parentNode.positions51=ps;draw();
};
const originalSchemas51=showSchemas;showSchemas=function(out,schemas,cat){originalSchemas51(out,schemas,cat);const w=out.parentNode;const chips=el('div','','positionchips');out.prepend(chips);chips.append(el('small','Pozíció gyorsválasztó (nem a rajz koordinátái)'));for(const p of ['',...(w.positions51||[])])btn(chips,p||'Mind',()=>{w.positionPicker?.(p);for(const b of chips.querySelectorAll('button'))b.classList.toggle('active',b.textContent===(p||'Mind'))});
 const observer=new MutationObserver(()=>{for(const box of out.querySelectorAll('.diagram')){if(box.dataset.ready51)continue;box.dataset.ready51='1';const img=box.querySelector('img'),slider=box.parentNode.querySelector('input[type=range]');if(!img||!slider)continue;const pts=new Map();let base=null;box.onpointerdown=e=>{box.setPointerCapture(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2){const [a,b]=[...pts.values()];base=[Math.hypot(a[0]-b[0],a[1]-b[1]),Number(slider.value)]}};box.onpointermove=e=>{if(!pts.has(e.pointerId))return;const old=pts.get(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2&&base&&base[0]>0){const [a,b]=[...pts.values()];slider.value=Math.max(50,Math.min(400,base[1]*Math.hypot(a[0]-b[0],a[1]-b[1])/base[0]));slider.oninput()}else if(pts.size===1){box.scrollLeft+=old[0]-e.clientX;box.scrollTop+=old[1]-e.clientY}};box.onpointerup=box.onpointercancel=e=>{pts.delete(e.pointerId);base=null};}});observer.observe(out,{childList:true,subtree:true});
};
</script>'''
