from flask import Flask, render_template_string, request, redirect, session, jsonify, abort
import json, os, time, requests, secrets, re
from threading import Thread
from datetime import datetime, timedelta
from collections import defaultdict
from werkzeug.utils import secure_filename

app = Flask(__name__)

# === إصلاح خطأ secret_key ===
SECRET_FROM_ENV = os.environ.get('SECRET_KEY', '').strip()
if SECRET_FROM_ENV:
    app.secret_key = SECRET_FROM_ENV
else:
    app.secret_key = secrets.token_hex(32)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

# === المفاتيح - الصق مفاتيحك هنا في تلفونك فقط ===
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '').strip() or "$#ZAQWSCX$DERTGV@BHYTVNMJ@UIO$MLOPIGSGHEH8BEB8EV8S#GSUWBJSIS8H38BSI8EHUEBDNSKOS9S3UVDBDJH37"
IMGBB_API_KEY = os.environ.get('IMGBB_KEY', '').strip() or "3fd6caa2e26d2b535c568e6616891b46"

SPLASH_FILE = 'splash.json'

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

def get_csrf():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

def check_csrf():
    if request.form.get('csrf_token','') != session.get('csrf_token'):
        abort(403)

def load_splash():
    if os.path.exists(SPLASH_FILE):
        try:
            with open(SPLASH_FILE,'r',encoding='utf-8') as f:
                d=json.load(f)
                return d if d.get('media') else {"media":"","type":"image"}
        except: return {"media":"","type":"image"}
    return {"media":"","type":"image"}

def save_splash(data):
    with open(SPLASH_FILE,'w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

request_logs=defaultdict(list); blocked_ips={}; login_attempts=defaultdict(list)
MAX_REQUESTS=150; TIME_WINDOW=60
def is_blocked(ip):
    if ip in blocked_ips:
        if datetime.now()<blocked_ips[ip]: return True
        else: del blocked_ips[ip]
    return False

@app.before_request
def ddos_protection():
    if request.path in ['/favicon.ico','/splash_shown']:
        return None
    ip=request.remote_addr or '127.0.0.1'
    if is_blocked(ip): return "IP محظور - حاول بعد 5 دقايق",429
    now=datetime.now()
    request_logs[ip]=[t for t in request_logs[ip] if (now-t).total_seconds()<TIME_WINDOW]
    request_logs[ip].append(now)
    if len(request_logs[ip])>MAX_REQUESTS:
        blocked_ips[ip]=now+timedelta(minutes=5)
        return "تم حظرك 5 دقايق",429

online_users={}
def get_visitors_count():
    try:
        ip=request.remote_addr
        if session.get('visited'):
            if os.path.exists('visitors_ips.json'):
                try:
                    with open('visitors_ips.json','r') as f: return len(json.load(f))
                except: return 0
            return 0
        session['visited']=True; session.permanent=True
        visitors={}
        if os.path.exists('visitors_ips.json'):
            try:
                with open('visitors_ips.json','r',encoding='utf-8') as f: visitors=json.load(f)
            except: visitors={}
        visitors[ip]=datetime.now().isoformat()
        with open('visitors_ips.json','w',encoding='utf-8') as f: json.dump(visitors,f,ensure_ascii=False)
        return len(visitors)
    except:
        return 0

@app.before_request
def count_visitor():
    try:
        ip=request.remote_addr; now=datetime.now(); online_users[ip]=now
        for k in list(online_users.keys()):
            if now-online_users[k]>timedelta(minutes=3): del online_users[k]
    except: pass

def load_categories():
    if os.path.exists('categories.json'):
        try:
            with open('categories.json','r',encoding='utf-8') as f:
                return [re.sub(r'[<>"\'&]','',str(c))[:50] for c in json.load(f)]
        except: pass
    return ["تشيرتات","علاقات","طباعة اكواب","لوحات","استيكرات","رسم على جرابات الهواتف"]

def save_categories(cats):
    with open('categories.json','w',encoding='utf-8') as f: json.dump(cats,f,ensure_ascii=False,indent=2)

categories=load_categories()
ALLOWED_IMAGE={'png','jpg','jpeg','webp','gif'}; ALLOWED_VIDEO={'mp4','webm','ogg','mov'}
def allowed_image(fn): return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_IMAGE
def allowed_video(fn): return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_VIDEO
def safe_filename(fn):
    n=secure_filename(fn)
    if not n: return ''
    ext=n.rsplit('.',1)[-1].lower() if '.' in n else ''
    if ext not in ALLOWED_IMAGE and ext not in ALLOWED_VIDEO: return ''
    return n
def upload_to_imgbb(file):
    if not IMGBB_API_KEY or IMGBB_API_KEY.startswith('حط_'): return ''
    try:
        file.seek(0); files={"image":(safe_filename(file.filename),file.read())}
        r=requests.post("https://api.imgbb.com/1/upload",data={"key":IMGBB_API_KEY,"expiration":0},files=files,timeout=30)
        d=r.json()
        if d.get('success'): return d['data']['url'].replace('http://','https://')
    except: pass
    return ''
def upload_to_catbox(file):
    try:
        file.seek(0); files={'fileToUpload':(safe_filename(file.filename),file.read())}
        r=requests.post("https://catbox.moe/user/api.php",data={'reqtype':'fileupload'},files=files,timeout=60)
        if r.status_code==200 and r.text.startswith('http'): return r.text.strip()
    except: pass
    return ''
def clean_text(t,mx=500):
    if not t: return ''
    t=str(t)[:mx].replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    return t.strip()
def load_products():
    if os.path.exists('products.json'):
        try:
            with open('products.json','r',encoding='utf-8') as f:
                data=json.load(f)
                for cat in data:
                    for p in data[cat]:
                        p.setdefault('whatsapp','249XXXXXXXXX'); p.setdefault('sold',False); p.setdefault('location','جميع الولايات')
                return data
        except: return {c:[] for c in categories}
    return {c:[] for c in categories}
def save_products(d):
    with open('products.json','w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2)
def load_ads():
    if os.path.exists('ads.json'):
        try:
            with open('ads.json','r',encoding='utf-8') as f:
                ads=json.load(f); valid=[]
                for a in ads:
                    if a.get('media') and (a.get('link') or a.get('whatsapp')) and str(a.get('media','')).startswith('http'):
                        a.setdefault('desc',''); a.setdefault('whatsapp',''); a.setdefault('type','image'); valid.append(a)
                return valid
        except: return []
    return []
def save_ads(d):
    with open('ads.json','w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2)
def check_new_items():
    if not os.path.exists('last_check.txt'):
        with open('last_check.txt','w') as f: f.write(str(int(time.time())))
        return {'products':[],'ads':[]}
    try:
        with open('last_check.txt','r') as f: last=int(f.read() or 0)
    except: last=0
    now=int(time.time()); products=load_products(); ads=load_ads(); np=[]; na=[]
    for cat in products:
        for p in products[cat]:
            try:
                if int(p['id'])>last: np.append(p)
            except: pass
    for ad in ads:
        try:
            if int(ad['id'])>last: na.append(ad)
        except: pass
    with open('last_check.txt','w') as f: f.write(str(now))
    return {'products':np,'ads':na}
def find_product_by_id(pid):
    if not str(pid).isdigit(): return None,None,load_products()
    products=load_products()
    for cat in products:
        for p in products[cat]:
            if p['id']==pid: return p,cat,products
    return None,None,products

HTML = '''<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>QIMI STORE - قيمي استور</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box;}
:root{--bg:#f8f9fa;--text:#222;--card:#fff;--border:#e0e0e0;--header:#fff;}
[data-theme="dark"]{--bg:#0a0a0f;--text:#e0e0e0;--card:rgba(20,20,30,0.7);--border:rgba(255,255,255,0.1);--header:rgba(15,15,20,0.8);}
body{background:var(--bg);color:var(--text);font-family:'Tajawal',sans-serif;}
.shape{width:14px;height:14px;display:inline-block;border-radius:50%;vertical-align:middle;}
.shape-blue{background:#00ccff;box-shadow:0 0 10px #00ccff;}
.shape-green{background:#00ff88;box-shadow:0 0 10px #00ff88;animation:pulse 1.5s infinite;}
@keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.4)}100%{transform:scale(1)}}
.top-bar{background:var(--header);border-bottom:2px solid var(--border);padding:10px 20px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:1000;backdrop-filter:blur(10px);}
.stats-box{display:flex;gap:12px;}
.stat-card{background:var(--card);border:2px solid #00ff88;padding:8px 14px;border-radius:12px;text-align:center;min-width:110px;position:relative;overflow:hidden;}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#00ff88,#00ccff,#ff0066);}
.stat-card.online{border-color:#00ccff;}
.stat-card.online::before{background:linear-gradient(90deg,#00ccff,#8B5CF6);}
.stat-label{font-size:12px;font-weight:700;opacity:0.7;display:flex;align-items:center;gap:6px;justify-content:center;}
.stat-num{color:#00ff88;font-weight:900;font-size:30px;line-height:1.2;font-family:monospace;}
.stat-card.online .stat-num{color:#00ccff;}
.theme-btn{background:#fff;color:#000;border:2px solid #00ff88;padding:10px 18px;border-radius:12px;cursor:pointer;font-weight:900;font-size:14px;transition:0.3s;box-shadow:0 0 15px rgba(0,255,136,0.4);}
[data-theme="dark"] .theme-btn{background:#000;color:#fff;border-color:#ffcc00;box-shadow:0 0 15px rgba(255,204,0,0.5);}
[data-theme="light"] .theme-btn{background:#ffcc00;color:#000;border-color:#000;}
.notification{position:fixed;top:80px;right:20px;background:linear-gradient(135deg,#00ff88,#00ccff);color:#000;padding:15px 25px;border-radius:15px;font-weight:700;z-index:9999;display:none;animation:slideIn 0.5s;max-width:350px;line-height:1.8;}
@keyframes slideIn{from{transform:translateX(300px);opacity:0}to{transform:translateX(0);opacity:1}}
.site-title{text-align:center;padding:25px 20px 10px;}
.site-name{font-size:42px;font-weight:900;white-space:nowrap;background:linear-gradient(90deg,#ff0066,#ffcc00,#00ccff,#33ff99,#ff0066);background-size:400% 400%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:rgb 3s ease infinite;line-height:1.2;letter-spacing:4px;}
@media(max-width:480px){.site-name{font-size:28px;}}
@keyframes rgb{0%{background-position:0% 50%;}50%{background-position:100% 50%;}100%{background-position:0% 50%;}}
.ps-center{display:flex;align-items:center;justify-content:center;gap:16px;margin:14px 0 5px;}
.ps-hand-full{width:320px;max-width:90vw;height:auto;animation:psColor 4s linear infinite, psFloat 2.5s ease-in-out infinite;filter:drop-shadow(0 0 25px rgba(0,255,136,0.8));}
@keyframes psColor{0%{filter:drop-shadow(0 0 20px #ff0066) hue-rotate(0deg);}25%{filter:drop-shadow(0 0 25px #00ccff) hue-rotate(90deg);}50%{filter:drop-shadow(0 0 25px #ffcc00) hue-rotate(180deg);}75%{filter:drop-shadow(0 0 25px #33ff99) hue-rotate(270deg);}100%{filter:drop-shadow(0 0 20px #ff0066) hue-rotate(360deg);}}
@keyframes psFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-8px) scale(1.03)}}
.ps-line{height:4px;flex:1;max-width:150px;border-radius:10px;background:linear-gradient(90deg,#ff0066,#ffcc00,#00ccff,#33ff99);background-size:300% 100%;animation:rgb 3s linear infinite;}
.nav-cats{background:var(--header);padding:12px 10px;text-align:center;border-bottom:2px solid var(--border);}
.nav-row{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-bottom:8px;}
.cat-link{background:var(--card);border:2px solid var(--border);color:var(--text);padding:8px 16px;border-radius:10px;text-decoration:none;font-weight:700;font-size:14px;white-space:nowrap;}
.cat-link:hover{border-color:#00ff88;}
.cat-link.active{background:var(--text);color:var(--bg);}
.ads-slider{max-width:1200px;margin:20px auto;padding:0 20px;position:relative;overflow:hidden;border-radius:20px;border:3px solid #00ff88;min-height:500px;background:#000;}
.ads-wrapper{display:flex;transition:transform 0.6s ease-in-out;width:100%;}
.ads-slide{min-width:100%;flex-shrink:0;width:100%;}
.ads-box{background:var(--card);overflow:hidden;width:100%;}
.ads-media{width:100%;height:500px;display:block;object-fit:contain;background:#000;cursor:pointer;}
.ads-btn-container{padding:15px;text-align:center;background:rgba(0,0,0,0.7);}
.ads-btn{display:inline-block;background:#25D366;color:#fff;padding:14px 40px;border-radius:12px;text-decoration:none;font-weight:700;font-size:18px;width:90%;}
.ads-desc{font-size:16px;margin:10px 15px;text-align:center;line-height:1.6;color:var(--text);}
.slider-dots{text-align:center;padding:10px;background:rgba(0,0,0,0.7);position:absolute;bottom:0;left:0;right:0;z-index:10;}
.dot{display:inline-block;width:12px;height:12px;border-radius:50%;background:#666;margin:0 5px;cursor:pointer;transition:0.3s;}
.dot.active{background:#00ff88;width:30px;border-radius:6px;}
.search-box{max-width:600px;margin:25px auto;padding:0 20px;}
.search-input{width:100%;padding:15px 20px;border-radius:12px;border:2px solid var(--border);background:var(--card);color:var(--text);font-size:16px;}
.container{max-width:1400px;margin:auto;padding:30px 20px;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:30px;}
.card{background:var(--card);border:2px solid var(--border);border-radius:16px;overflow:hidden;position:relative;}
.card.sold{opacity:0.6;}
.card img{width:100%;height:auto;max-height:550px;object-fit:contain;background:#111;border-bottom:2px solid var(--border);cursor:zoom-in;}
.card-body{padding:22px;}
.price{font-size:26px;font-weight:700;color:#00ff88;}
.location{font-size:14px;color:#00ccff;margin:10px 0;font-weight:700;}
.order-btn{display:block;background:#8B5CF6;color:#fff;text-align:center;padding:15px;border-radius:10px;text-decoration:none;font-weight:700;font-size:17px;}
.order-btn.disabled{background:#666;pointer-events:none;}
.sold-stamp{position:absolute;top:40%;left:50%;transform:translate(-50%,-50%) rotate(-15deg);font-size:48px;font-weight:900;color:#ff4500;text-shadow:0 0 10px #ff0000,0 0 20px #ff6600,0 0 30px #ffaa00,0 0 40px #ffff00,0 0 60px #ff0000;z-index:10;border:5px solid #ff4500;padding:20px 50px;border-radius:15px;background:rgba(0,0,0,0.7);animation:fire 0.8s infinite alternate;}
@keyframes fire{0%{text-shadow:0 0 10px #ff0000,0 0 20px #ff6600,0 0 30px #ffaa00;}100%{text-shadow:0 0 20px #ff0000,0 0 40px #ff6600,0 0 60px #ffaa00,0 0 80px #ffff00;}}
.gallery-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:99999;align-items:center;justify-content:center;}
.gallery-modal.active{display:flex;}
.gallery-img{max-width:95%;max-height:95%;border-radius:10px;}
.gallery-close{position:absolute;top:30px;right:40px;font-size:50px;color:#fff;cursor:pointer;}
</style></head><body>
<audio id="notificationSound" preload="auto"><source src="https://files.catbox.moe/u5zsfh.wav" type="audio/wav"></audio>
{% if not session.get('splash_shown') %}{% set splash = load_splash() %}{% if splash and splash.media %}
<div id="splash" style="position:fixed;top:0;left:0;width:100%;height:100%;background:#000;z-index:99999;display:flex;align-items:center;justify-content:center;transition:opacity 1s;overflow:hidden;">
<canvas id="splashCanvas" style="position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;"></canvas>
<div style="position:relative;z-index:2;width:90%;max-width:1200px;height:500px;border-radius:20px;border:3px solid #00ff88;background:#000;display:flex;align-items:center;justify-content:center;">
{% if splash.type == 'video' %}<video autoplay muted loop playsinline style="max-width:100%;max-height:100%;border-radius:17px;"><source src="{{ splash.media }}" type="video/mp4"></video>
{% else %}<img src="{{ splash.media }}" style="max-width:100%;max-height:100%;object-fit:contain;border-radius:17px;">{% endif %}
</div><div style="position:absolute;bottom:50px;z-index:2;color:#00ff88;font-size:24px;font-weight:900;letter-spacing:3px;">QIMI STORE</div></div>
<script>var ss=false;setTimeout(function(){if(!ss){ss=true;var s=document.getElementById('splash');s.style.opacity='0';setTimeout(function(){s.remove();},1000);fetch('/splash_shown');}},20000);window.addEventListener('load',function(){const c=document.getElementById('splashCanvas');if(!c)return;const ctx=c.getContext('2d');c.width=window.innerWidth;c.height=window.innerHeight;const dots=[];for(let i=0;i<80;i++){dots.push({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*3+1,dx:(Math.random()-0.5)*0.5,dy:(Math.random()-0.5)*0.5,color:`hsl(${Math.random()*360},100%,50%)`});}function a(){ctx.clearRect(0,0,c.width,c.height);dots.forEach(d=>{d.x+=d.dx;d.y+=d.dy;if(d.x<0||d.x>c.width)d.dx*=-1;if(d.y<0||d.y>c.height)d.dy*=-1;ctx.beginPath();ctx.arc(d.x,d.y,d.r,0,Math.PI*2);ctx.fillStyle=d.color;ctx.shadowBlur=15;ctx.shadowColor=d.color;ctx.fill();});requestAnimationFrame(a);}a();});</script>
{% endif %}{% endif %}
<div class="top-bar"><div style="width:120px;"></div><div class="stats-box"><div class="stat-card"><div class="stat-label"><span class="shape shape-blue"></span> الزوار</div><div class="stat-num">{{ visitors }}</div></div><div class="stat-card online"><div class="stat-label"><span class="shape shape-green"></span> المتصلين</div><div class="stat-num">{{ online }}</div></div></div><button class="theme-btn" id="themeBtn" onclick="toggleTheme()">وضع الداكن</button></div>
<div class="notification" id="notif"></div>
{% if message %}<div class="alert" style="position:fixed;top:20px;right:20px;padding:15px 25px;border-radius:10px;font-weight:700;z-index:10000;background:#00ff88;color:#000;">{{ message }}</div><script>setTimeout(()=>document.querySelector('.alert').remove(),3000)</script>{% endif %}
<div class="site-title"><div class="site-name">♕ 𝗤𝗜𝗠𝗜 𝗦𝗧𝗢𝗥𝗘 ♕</div>
<div class="ps-center"><div class="ps-line"></div>
<svg class="ps-hand-full" viewBox="0 0 400 260" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="bodyGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#1a1a2e"/><stop offset="50%" style="stop-color:#16213e"/><stop offset="100%" style="stop-color:#0f3460"/></linearGradient><linearGradient id="rainbow" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#ff0066"/><stop offset="25%" style="stop-color:#ffcc00"/><stop offset="50%" style="stop-color:#00ccff"/><stop offset="75%" style="stop-color:#8B5CF6"/><stop offset="100%" style="stop-color:#33ff99"/></linearGradient></defs><path d="M40 60 Q30 20 80 25 L130 30 Q160 32 200 32 Q240 32 270 30 L320 25 Q370 20 360 60 L350 120 Q345 170 320 210 Q305 235 280 230 Q250 225 240 190 L225 150 Q210 135 200 135 Q190 135 175 150 L160 190 Q150 225 120 230 Q95 235 80 210 Q55 170 50 120 Z" fill="url(#bodyGrad)" stroke="url(#rainbow)" stroke-width="5" stroke-linejoin="round"/><rect x="155" y="45" width="90" height="18" rx="9" fill="#222" stroke="#00ccff" stroke-width="2"/><rect x="165" y="50" width="70" height="8" rx="4" fill="#00ccff" opacity="0.7"/><circle cx="200" cy="85" r="12" fill="#111" stroke="#fff" stroke-width="2"/><path d="M195 85 L200 80 L205 85 L200 90 Z" fill="#fff"/><g transform="translate(90,95)"><rect x="-10" y="-32" width="20" height="64" rx="5" fill="#111" stroke="#fff" stroke-width="1.5"/><rect x="-32" y="-10" width="64" height="20" rx="5" fill="#111" stroke="#fff" stroke-width="1.5"/><circle cx="0" cy="0" r="8" fill="#333"/></g><g><circle cx="310" cy="70" r="14" fill="#111" stroke="#33ff99" stroke-width="2.5"/><path d="M310 60 L318 78 L302 78 Z" fill="#33ff99"/><circle cx="335" cy="95" r="14" fill="#111" stroke="#ff0066" stroke-width="2.5"/><circle cx="335" cy="95" r="8" fill="none" stroke="#ff0066" stroke-width="2.5"/><circle cx="310" cy="120" r="14" fill="#111" stroke="#00ccff" stroke-width="2.5"/><path d="M303 113 L317 127 M317 113 L303 127" stroke="#00ccff" stroke-width="3.5" stroke-linecap="round"/><circle cx="285" cy="95" r="14" fill="#111" stroke="#ffcc00" stroke-width="2.5"/><rect x="277" y="87" width="16" height="16" fill="none" stroke="#ffcc00" stroke-width="2.5"/></g><g><circle cx="140" cy="165" r="28" fill="#0a0a0a" stroke="#00ff88" stroke-width="3"/><circle cx="140" cy="165" r="20" fill="#1a1a1a" stroke="#333" stroke-width="1"/><circle cx="140" cy="165" r="8" fill="#00ff88"/></g><g><circle cx="260" cy="165" r="28" fill="#0a0a0a" stroke="#00ccff" stroke-width="3"/><circle cx="260" cy="165" r="20" fill="#1a1a1a" stroke="#333" stroke-width="1"/><circle cx="260" cy="165" r="8" fill="#00ccff"/></g><rect x="70" y="22" width="50" height="12" rx="6" fill="#222" stroke="#ffcc00" stroke-width="1.5"/><rect x="280" y="22" width="50" height="12" rx="6" fill="#222" stroke="#ffcc00" stroke-width="1.5"/><text x="95" y="31" font-size="8" fill="#ffcc00" text-anchor="middle" font-weight="bold">L1</text><text x="305" y="31" font-size="8" fill="#ffcc00" text-anchor="middle" font-weight="bold">R1</text><circle cx="60" cy="60" r="4" fill="#ff0066"/><circle cx="340" cy="60" r="4" fill="#00ccff"/></svg>
<div class="ps-line"></div></div></div>
<div class="nav-cats"><div class="nav-row"><a href="/" class="cat-link {% if not active_cat %}active{% endif %}">الكل</a><a href="/available" class="cat-link {% if active_cat == 'available' %}active{% endif %}">المتاحات</a></div><div class="nav-row">{% for cat in categories %}<a href="/cat/{{ cat }}" class="cat-link {% if active_cat == cat %}active{% endif %}">{{ cat }}</a>{% endfor %}</div></div>
{% if ads and ads|length > 0 %}<div class="ads-slider" id="adsSlider"><div class="ads-wrapper" id="adsWrapper">{% for ad in ads %}<div class="ads-slide"><div class="ads-box">{% if ad.type == 'video' %}<video class="ads-media" controls preload="metadata" playsinline><source src="{{ ad.media }}" type="video/mp4"></video>{% else %}<img class="ads-media" src="{{ ad.media }}" alt="إعلان" onclick="openGallery(this.src)">{% endif %}{% if ad.desc %}<div class="ads-desc">{{ ad.desc }}</div>{% endif %}<div class="ads-btn-container"><a href="{{ ad.link if ad.link and ad.link!= '#' else 'https://wa.me/' + ad.whatsapp + '?text=استفسار عن الإعلان' }}" target="_blank" class="ads-btn">اضغط للمزيد</a></div></div></div>{% endfor %}</div>{% if ads|length > 1 %}<div class="slider-dots" id="sliderDots"></div>{% endif %}</div>{% endif %}
<div class="search-box"><input type="text" id="searchInput" class="search-input" placeholder="🔍 ابحث..."></div>
<div class="container">{% if products_list and products_list|length > 0 %}<div class="grid" id="productsGrid">{% for p in products_list %}<div class="card {% if p.sold %}sold{% endif %}" data-name="{{ p.name }} {{ p.desc }} {{ p.location }}">{% if p.sold %}<div class="sold-stamp">SOLD OUT</div>{% endif %}<img src="{{ p.img if p.img else 'https://i.ibb.co/nR8mQmK/no-image.png' }}" onclick="openGallery(this.src)"><div class="card-body"><h3>{{ p.name }}</h3><div style="opacity:0.7;margin:8px 0">{{ p.desc }}</div><div class="price">{{ p.price }} جنيه</div><div class="location">📍 {{ p.location }}</div><a class="order-btn {% if p.sold %}disabled{% endif %}" href="https://wa.me/{{ p.whatsapp }}?text=أريد {{ p.name }} - {{ p.price }} جنيه - {{ p.location }}" target="_blank">{% if p.sold %}نفذت{% else %}🛒 الطلب عبر واتساب{% endif %}</a></div></div>{% endfor %}</div>{% else %}<div style="text-align:center;padding:80px;opacity:0.5">📦 لا توجد منتجات</div>{% endif %}</div>
<div class="gallery-modal" id="galleryModal" onclick="closeGallery()"><span class="gallery-close">×</span><img class="gallery-img" id="galleryImg"></div>
<script>
function toggleTheme(){const h=document.documentElement;const n=h.getAttribute('data-theme')==='dark'?'light':'dark';h.setAttribute('data-theme',n);localStorage.setItem('theme',n);updateThemeBtn(n);}
function updateThemeBtn(t){const b=document.getElementById('themeBtn');if(!b)return;b.textContent=(t==='dark')?'الوضع الساطع':'وضع الداكن';}
document.documentElement.setAttribute('data-theme',localStorage.getItem('theme')||'dark');updateThemeBtn(localStorage.getItem('theme')||'dark');
document.getElementById('searchInput').addEventListener('input',function(){const q=this.value.toLowerCase();document.querySelectorAll('.card').forEach(c=>{c.style.display=c.getAttribute('data-name').toLowerCase().includes(q)?'block':'none'})});
function openGallery(s){document.getElementById('galleryImg').src=s;document.getElementById('galleryModal').classList.add('active');}
function closeGallery(){document.getElementById('galleryModal').classList.remove('active');}
let currentSlide=0,slideInterval;function initSlider(){const w=document.getElementById('adsWrapper');const d=document.getElementById('sliderDots');if(!w)return;const s=w.querySelectorAll('.ads-slide');if(s.length<=1)return;if(d){s.forEach((_,i)=>{const dot=document.createElement('span');dot.className='dot'+(i===0?' active':'');dot.onclick=()=>goToSlide(i);d.appendChild(dot);});}function u(){w.style.transform='translateX('+(currentSlide*100)+'%)';document.querySelectorAll('.dot').forEach((dot,i)=>{dot.classList.toggle('active',i===currentSlide);});}function goToSlide(n){currentSlide=n;u();reset();}function next(){currentSlide=(currentSlide+1)%s.length;u();}function reset(){clearInterval(slideInterval);slideInterval=setInterval(next,5000);}slideInterval=setInterval(next,5000);const sl=document.getElementById('adsSlider');sl.addEventListener('mouseenter',()=>clearInterval(slideInterval));sl.addEventListener('mouseleave',reset);u();}
window.addEventListener('load',initSlider);
var notifSound=document.getElementById('notificationSound');function playNotificationSound(){if(notifSound){notifSound.currentTime=0;notifSound.play().catch(function(e){});}}
setInterval(function(){fetch('/check_new').then(r=>r.json()).then(data=>{const notif=document.getElementById('notif');let msgs=[];if(data.products&&data.products.length>0){data.products.forEach(p=>{msgs.push(`🛍️ منتج جديد نزل!<br>📦 الاسم: ${p.name}<br>💰 السعر: ${p.price} جنيه<br>🏷️ القسم: ${p.cat}`);});}if(data.ads&&data.ads.length>0){data.ads.forEach(a=>{msgs.push(`📢 اعلان جديد!<br>📝 الوصف: ${a.desc||'اعلان جديد في المتجر'}`);});}if(msgs.length>0){playNotificationSound();let i=0;function showNext(){if(i<msgs.length){notif.innerHTML=msgs[i];notif.style.display='block';setTimeout(()=>{notif.style.display='none';i++;setTimeout(showNext,500);},6000);}}showNext();}});},30000);
</script></body></html>'''

LOGIN_HTML = '''<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><title>QIMI STORE - دخول</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Tajawal',sans-serif;}body{background:#0a0a0f;color:#e0e0e0;display:flex;align-items:center;justify-content:center;min-height:100vh;}.box{background:rgba(20,20,30,0.9);padding:40px;border-radius:20px;border:2px solid #00ff88;max-width:400px;width:90%;}h2{text-align:center;color:#00ff88;margin-bottom:30px;font-size:28px;}input{width:100%;padding:14px;margin:10px 0;border-radius:10px;border:2px solid #333;background:#111;color:#fff;font-size:16px;}button{width:100%;padding:15px;background:#00ff88;color:#000;border:0;border-radius:10px;font-weight:700;font-size:17px;cursor:pointer;}</style></head><body><div class="box"><h2>♕ 𝗤𝗜𝗠𝗜 𝗦𝗧𝗢𝗥𝗘 ♕</h2><form method="post" action="/adminstoerc-on/login"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="password" name="password" placeholder="كلمة السر" required><button type="submit">دخول</button></form></div></body></html>'''

@app.route('/splash_shown')
def splash_shown(): session['splash_shown']=True; return 'ok'

@app.route('/adminstoerc-on/login', methods=['POST'])
def admin_login():
    ip=request.remote_addr; now=datetime.now()
    login_attempts[ip]=[t for t in login_attempts[ip] if (now-t).total_seconds()<300]
    if len(login_attempts[ip])>=5: return "محاولات كتيرة - انتظر 5 دقايق",429
    login_attempts[ip].append(now); check_csrf()
    if request.form.get('password')==ADMIN_PASSWORD and not ADMIN_PASSWORD.startswith('حط_'):
        session['admin_logged']=True; session.permanent=True; login_attempts[ip]=[]; return redirect('/adminstoerc-on')
    return render_template_string(LOGIN_HTML, csrf=get_csrf())

@app.route('/adminstoerc-on', methods=['GET','POST'])
def admin():
    global categories
    if not session.get('admin_logged'): return render_template_string(LOGIN_HTML, csrf=get_csrf())
    products=load_products(); ads=load_ads(); splash=load_splash(); message=request.args.get('msg')
    if request.method=='POST':
        check_csrf(); action=request.form.get('action'); pid=request.form.get('pid'); ad_id=request.form.get('ad_id'); cat_name=clean_text(request.form.get('cat_name'),50)
        if action=='add_cat' and cat_name:
            if cat_name not in categories: categories.append(cat_name); save_categories(categories); products[cat_name]=[]; save_products(products)
            return redirect('/adminstoerc-on?msg=تم إضافة القسم')
        if action=='delete_cat' and cat_name:
            if cat_name in categories: categories.remove(cat_name); save_categories(categories)
            if cat_name in products: del products[cat_name]; save_products(products)
            return redirect('/adminstoerc-on?msg=تم حذف القسم')
        if action=='delete' and pid:
            p,cat,prods=find_product_by_id(pid)
            if p: prods[cat]=[x for x in prods[cat] if x['id']!=pid]; save_products(prods)
            return redirect('/adminstoerc-on?msg=تم حذف المنتج')
        if action=='toggle_sold' and pid:
            p,cat,prods=find_product_by_id(pid)
            if p: p['sold']=not p.get('sold',False); save_products(prods)
            return redirect('/adminstoerc-on')
        if action=='update_splash':
            mu=''; mt='image'
            if 'splash_media' in request.files:
                f=request.files['splash_media']
                if f and f.filename and safe_filename(f.filename):
                    if allowed_image(f.filename): mu=upload_to_imgbb(f); mt='image'
                    elif allowed_video(f.filename): mu=upload_to_catbox(f); mt='video'
            if mu: save_splash({"media":mu,"type":mt}); return redirect('/adminstoerc-on?msg=تم تحديث شاشة البداية')
        if action=='delete_splash': save_splash({"media":"","type":"image"}); return redirect('/adminstoerc-on?msg=تم مسح شاشة البداية')
        if action=='add':
            img=''
            if 'image' in request.files:
                f=request.files['image']
                if f and f.filename and allowed_image(f.filename) and safe_filename(f.filename):
                    img=upload_to_imgbb(f)
                    if not img: img="https://i.ibb.co/nR8mQmK/no-image.png"
            try: price=int(request.form['price'])
            except: price=0
            if price<0 or price>100000000: price=0
            wa=re.sub(r'\D','',request.form.get('whatsapp',''))[:15]
            nid=str(int(time.time())); newp={"id":nid,"name":clean_text(request.form['name'],100),"desc":clean_text(request.form['desc'],500),"price":price,"whatsapp":wa,"location":clean_text(request.form['location'],100),"img":img,"cat":clean_text(request.form['cat'],50),"sold":False}
            if newp['cat'] not in products: products[newp['cat']]=[]
            products[newp['cat']].append(newp); save_products(products); return redirect('/adminstoerc-on?msg=تم إضافة المنتج')
        if action=='add_ad':
            mu=''; mt='image'
            if 'ad_media' in request.files:
                f=request.files['ad_media']
                if f and f.filename and safe_filename(f.filename):
                    if allowed_image(f.filename): mu=upload_to_imgbb(f); mt='image'
                    elif allowed_video(f.filename): mu=upload_to_catbox(f); mt='video'
            if mu:
                link=clean_text(request.form.get('ad_link','#'),200)
                if link and not link.startswith('http'): link='https://'+link
                na={"id":str(int(time.time())),"media":mu,"type":mt,"link":link,"desc":clean_text(request.form.get('ad_desc',''),200),"whatsapp":re.sub(r'\D','',request.form.get('ad_whatsapp',''))[:15]}
                ads.append(na); save_ads(ads); return redirect('/adminstoerc-on?msg=تم إضافة الإعلان')
        if action=='delete_ad' and ad_id: ads=[a for a in ads if a['id']!=ad_id]; save_ads(ads); return redirect('/adminstoerc-on?msg=تم حذف الإعلان')
    allp=[]
    for c in categories: allp.extend(products.get(c,[]))
    csrf=get_csrf(); cards=''; adsh=''
    for p in allp:
        st='إرجاع' if p.get('sold') else 'SOLD OUT'; src=p.get("img","https://i.ibb.co/nR8mQmK/no-image.png")
        cards+=f'<div class="admin-card"><img src="{src}" style="height:180px;width:100%;object-fit:contain"><h4>{p["name"]}</h4><p style="font-size:14px;opacity:0.7">{p["cat"]} - {p["price"]} جنيه</p><div class="control-btns"><form method="post"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="toggle_sold"><input type="hidden" name="pid" value="{p["id"]}"><button type="submit" class="btn-big btn-sold">{st}</button></form><form method="post" onsubmit="return confirm(\'متأكد؟\')"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="delete"><input type="hidden" name="pid" value="{p["id"]}"><button type="submit" class="btn-big btn-delete">🗑️ حذف</button></form></div></div>'
    for ad in ads:
        mp=f'<video src="{ad.get("media","")}" style="height:150px;width:100%;object-fit:cover;border-radius:8px" controls></video>' if ad.get('type')=='video' else f'<img src="{ad.get("media","https://i.ibb.co/nR8mQmK/no-image.png")}" style="height:150px;width:100%;object-fit:cover;border-radius:8px">'
        adsh+=f'<div class="admin-card">{mp}<p style="font-size:13px;margin:10px 0">{ad.get("desc","بدون وصف")}</p><form method="post" onsubmit="return confirm(\'تحذف الإعلان؟\')"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="delete_ad"><input type="hidden" name="ad_id" value="{ad["id"]}"><button type="submit" class="btn-big btn-delete">🗑️ حذف</button></form></div>'
    catm='<div class="cat-manage"><h3 style="color:#00ff88;margin-bottom:15px">إدارة الأقسام</h3><form method="post" style="display:flex;gap:10px"><input type="hidden" name="csrf_token" value="'+csrf+'"><input type="hidden" name="action" value="add_cat"><input name="cat_name" placeholder="اسم القسم الجديد" required style="flex:1;padding:12px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text)"><button type="submit" class="btn-big btn-add" style="min-height:auto;padding:12px 25px">➕ إضافة قسم</button></form><div class="cat-list">'
    for c in categories: catm+=f'<div class="cat-item"><span>{c}</span><form method="post" onsubmit="return confirm(\'تحذف القسم؟\')"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="delete_cat"><input type="hidden" name="cat_name" value="{c}"><button type="submit" style="background:#ff4444;color:#fff;border:0;padding:5px 10px;border-radius:5px;cursor:pointer">×</button></form></div>'
    catm+='</div></div>'
    sph=''
    if splash and splash.get('media'):
        if splash.get('type')=='video': sph=f'<video src="{splash["media"]}" style="width:100%;height:300px;object-fit:contain;border-radius:10px;background:#000" controls></video>'
        else: sph=f'<img src="{splash["media"]}" style="width:100%;height:300px;object-fit:contain;border-radius:10px;background:#000">'
    return render_template_string('''<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><title>QIMI STORE - لوحة التحكم</title><style>@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');*{margin:0;padding:0;box-sizing:border-box;font-family:'Tajawal',sans-serif;}:root{--bg:#0a0a0f;--text:#e0e0e0;--card:rgba(20,20,30,0.7);--border:rgba(255,255,255,0.1);}body{background:var(--bg);color:var(--text);}.admin-container{max-width:1400px;margin:30px auto;padding:20px;}.admin-title{text-align:center;font-size:32px;color:#00ff88;margin-bottom:30px;}.section-title{color:#00ff88;font-size:24px;margin:30px 0 20px;}.admin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;}.admin-card{background:var(--card);border:2px solid var(--border);border-radius:12px;padding:20px;}.control-btns{display:flex;gap:12px;margin-top:15px}.btn-big{flex:1;padding:16px 0;font-size:18px;font-weight:700;border-radius:12px;border:none;cursor:pointer;min-height:55px;}.btn-sold{background:#ffaa00;color:#000}.btn-delete{background:#ff4444;color:#fff}.btn-add{background:#00ff88;color:#000}input,select,textarea{width:100%;padding:12px;margin:8px 0;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);}textarea{height:80px;}.cat-manage{background:var(--card);border:2px solid var(--border);padding:20px;border-radius:12px;margin:20px 0}.cat-list{display:flex;flex-wrap:wrap;gap:10px;margin-top:15px}.cat-item{background:var(--bg);padding:8px 15px;border-radius:8px;border:1px solid var(--border);display:flex;align-items:center;gap:10px}.alert{position:fixed;top:20px;right:20px;padding:15px 25px;border-radius:10px;font-weight:700;z-index:10000;background:#00ff88;color:#000;}</style></head><body><div class="admin-container"><h1 class="admin-title">♕ 𝗤𝗜𝗠𝗜 𝗦𝗧𝗢𝗥𝗘 ♕ - لوحة التحكم</h1><div style="text-align:center;margin-bottom:20px"><a href="#add" class="btn-big btn-add" style="display:inline-block;text-decoration:none;padding:14px 30px">➕ إضافة منتج</a><a href="#ads" class="btn-big btn-add" style="display:inline-block;text-decoration:none;padding:14px 30px;margin:0 10px">📢 إدارة الإعلانات</a><a href="/adminstoerc-on/logout" class="btn-big btn-delete" style="display:inline-block;text-decoration:none;padding:14px 30px">🚪 خروج</a></div>{{ cat_manage|safe }}<h2 class="section-title" id="ads">📢 إدارة الإعلانات</h2><div class="admin-grid">{{ ads_html|safe }}</div><form method="post" enctype="multipart/form-data" style="max-width:500px;margin:30px auto;background:var(--card);padding:30px;border-radius:15px;border:1px solid var(--border);"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="action" value="add_ad"><h3 style="text-align:center;margin-bottom:20px;color:#00ff88;">إضافة إعلان جديد</h3><input name="ad_link" placeholder="الرابط"><input name="ad_whatsapp" placeholder="رقم واتساب 249..."><textarea name="ad_desc" placeholder="وصف الإعلان"></textarea><input name="ad_media" type="file" accept="image/*,video/*" required><button type="submit" class="btn-big btn-add" style="width:100%">➕ إضافة الإعلان</button></form><h2 class="section-title">🖼️ شاشة البداية</h2><div class="admin-card" style="max-width:600px;margin:20px auto;border-color:#00ff88;">{% if splash and splash.media %}{{ splash_html|safe }}<form method="post" style="margin-top:10px" onsubmit="return confirm('متأكد؟')"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="action" value="delete_splash"><button type="submit" class="btn-big btn-delete">🗑️ مسح شاشة البداية</button></form>{% else %}<p style="text-align:center;opacity:0.6">لا توجد شاشة بداية</p>{% endif %}<form method="post" enctype="multipart/form-data" style="margin-top:15px"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="action" value="update_splash"><input name="splash_media" type="file" accept="image/*,video/*" required><button type="submit" class="btn-big btn-add" style="width:100%">🔄 رفع / تحديث</button></form></div><h2 class="section-title">📦 المنتجات</h2><div class="admin-grid">{{ cards_html|safe }}</div><form method="post" enctype="multipart/form-data" id="add" style="max-width:500px;margin:50px auto;background:var(--card);padding:30px;border-radius:15px;border:1px solid var(--border);"><input type="hidden" name="csrf_token" value="{{ csrf }}"><input type="hidden" name="action" value="add"><h2 style="text-align:center;margin-bottom:20px;color:#00ff88;">➕ إضافة منتج</h2><input name="name" placeholder="اسم المنتج" required><textarea name="desc" placeholder="الوصف" required></textarea><input name="price" type="number" placeholder="السعر" required><input name="whatsapp" placeholder="رقم واتساب 249..." required><input name="location" placeholder="مكان التوصيل" required><input name="image" type="file" accept="image/*" required><select name="cat">''' + ''.join(['<option>'+c+'</option>' for c in categories]) + '''</select><button type="submit" class="btn-big btn-add" style="width:100%">➕ إضافة</button></form></div>{% if message %}<div class="alert">{{ message }}</div><script>setTimeout(()=>document.querySelector('.alert').remove(),3000)</script>{% endif %}</body></html>''', categories=categories, cards_html=cards, ads_html=adsh, cat_manage=catm, splash=splash, splash_html=sph, message=message, csrf=csrf)

@app.route('/adminstoerc-on/logout')
def logout(): session.clear(); return redirect('/adminstoerc-on')

@app.route('/check_new')
def check_new():
    d=check_new_items()
    return jsonify({'products':[{'name':p['name'],'cat':p['cat'],'price':p['price']} for p in d['products']],'ads':[{'desc':a.get('desc','اعلان جديد')} for a in d['ads']]})

@app.route('/')
def home():
    if 'splash_shown' in session: session.pop('splash_shown')
    products=load_products(); ads=load_ads(); splash=load_splash(); allp=[]
    for c in categories: allp.extend(products.get(c,[]))
    return render_template_string(HTML, categories=categories, products_list=allp, ads=ads, splash=splash, active_cat=None, visitors=get_visitors_count(), online=len(online_users), message=request.args.get('msg'), load_splash=load_splash, session=session)

@app.route('/available')
def available_products():
    products=load_products(); ads=load_ads(); splash=load_splash(); av=[]
    for c in categories: av.extend([p for p in products.get(c,[]) if not p.get('sold')])
    return render_template_string(HTML, categories=categories, products_list=av, ads=ads, splash=splash, active_cat='available', visitors=get_visitors_count(), online=len(online_users), message=request.args.get('msg'), load_splash=load_splash, session=session)

@app.route('/cat/<cat_name>')
def category_page(cat_name):
    cat_name=clean_text(cat_name,50); products=load_products(); ads=load_ads(); splash=load_splash()
    return render_template_string(HTML, categories=categories, products_list=products.get(cat_name,[]), ads=ads, splash=splash, active_cat=cat_name, visitors=get_visitors_count(), online=len(online_users), message=request.args.get('msg'), load_splash=load_splash, session=session)

keep_alive_app=Flask('keep_alive')
keep_alive_app.secret_key = secrets.token_hex(32)
@keep_alive_app.route('/')
def home_keep(): return "QIMI STORE is alive"
def run_keep(): keep_alive_app.run(host='0.0.0.0',port=8080)
def keep_alive():
    t=Thread(target=run_keep); t.start()
if __name__=='__main__':
    keep_alive(); app.run(host='0.0.0.0',port=9000,debug=False)
