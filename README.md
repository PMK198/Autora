# AUTORA 3.0 szerver
Python 3.10+; telepítés: pip install -r requirements.txt
A tárhely titkos környezeti változói: PLAN_PARTS_API_KEY (saját Plan.parts kulcs), AUTORA_ACCESS_TOKEN (külön, hosszú véletlen hozzáférési kód). Ne töltsd fel ezeket GitHubra. Indítás: gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} app:app
HTTPS-t a tárhely biztosítson. Az Android beállításaiban a HTTPS szervercímet és a külön AUTORA hozzáférési kódot add meg. A gyorsítótár 15 perces, memóriában, egy folyamatban működik. Nyilvános kiadás előtt szükséges felhasználói hitelesítés, kvóták és adatlicenc ellenőrzése. A szótár csak néhány megnevezést fordít; a többi eredeti nyelven jelenik meg. Fotó, VIN és helyettesítő részletek még nem integráltak.
