# -*- coding: utf-8 -*-
# ==============================================================================
# SUDANESE-X v31 — PART 1/3
# imports, models, helpers, styles, splash, auth, chats
# ==============================================================================
import os, re, io, uuid, random, string, secrets, hashlib, hmac, time, traceback, json
import base64, html as html_module, shutil
from datetime import datetime, timedelta, timezone
from functools import wraps
from collections import defaultdict

try:
    from flask_socketio import SocketIO, emit as socket_emit, join_room as socket_join_room
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

try:
    from zoneinfo import ZoneInfo
    KHARTOUM_TZ = ZoneInfo("Africa/Khartoum")
except Exception:
    KHARTOUM_TZ = timezone(timedelta(hours=2), name="SDT")
UTC_TZ = timezone.utc

from flask import (Flask, render_template_string, redirect, url_for, flash,
                   request, session, abort, make_response, send_from_directory,
                   jsonify, Response, send_file)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text, or_, and_, func, case

SITE_NAME = "𝚂𝚄𝙳𝙰𝙽𝙴𝚂𝙴-X"
SUPPORT_PASSWORD = "$#ZAQWSCX$DERTGV@BHYTVNMJ@UIO$MLOPIGSGHEH8BEB8EV8S#GSUWBJSIS8H38BSI8EHUEBDNSKOS9S3UVDBDJH37"

VOLUME_MOUNT = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
if VOLUME_MOUNT and os.path.isdir(VOLUME_MOUNT):
    DATA_DIR = VOLUME_MOUNT
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
STATUS_DIR = os.path.join(UPLOAD_DIR, "statuses")
CHAT_DIR = os.path.join(UPLOAD_DIR, "chats")
GROUP_DIR = os.path.join(UPLOAD_DIR, "groups")
VOICE_DIR = os.path.join(DATA_DIR, "voices")
VERIFY_DIR = os.path.join(DATA_DIR, "verification")
ADS_DIR = os.path.join(UPLOAD_DIR, "ads")
STICKER_DIR = os.path.join(UPLOAD_DIR, "stickers")
SPLASH_DIR = os.path.join(UPLOAD_DIR, "splash")
for d in (AVATAR_DIR, STATUS_DIR, CHAT_DIR, GROUP_DIR, VOICE_DIR,
          VERIFY_DIR, ADS_DIR, STICKER_DIR, SPLASH_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///" + os.path.join(DATA_DIR, "sarhni.db")

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["AVATAR_FOLDER"] = AVATAR_DIR
app.config["STATUS_FOLDER"] = STATUS_DIR
app.config["CHAT_FOLDER"] = CHAT_DIR
app.config["GROUP_FOLDER"] = GROUP_DIR
app.config["ADS_FOLDER"] = ADS_DIR
app.config["STICKER_FOLDER"] = STICKER_DIR
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

socketio = None
if SOCKETIO_AVAILABLE:
    try:
        socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
    except Exception:
        socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

def to_sd(dt):
    if dt is None: return None
    try:
        if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(KHARTOUM_TZ)
    except Exception:
        try: return dt + timedelta(hours=2)
        except Exception: return dt

def fmt_sd(dt, fmt="%Y-%m-%d %H:%M"):
    d = to_sd(dt)
    if d is None: return "—"
    try: return d.strftime(fmt)
    except Exception: return "—"

def utc_now(): return datetime.now(UTC_TZ).replace(tzinfo=None)
def now_utc_naive(): return utc_now()

def time_ago_sd(dt):
    if not dt: return "غير معروف"
    d = to_sd(dt)
    if not d: return "غير معروف"
    diff = (datetime.now(KHARTOUM_TZ) - d).total_seconds()
    if diff < 60: return "الآن"
    if diff < 3600: return f"منذ {int(diff//60)} دقيقة"
    if diff < 86400: return f"منذ {int(diff//3600)} ساعة"
    if diff < 604800: return f"منذ {int(diff//86400)} يوم"
    return fmt_sd(dt, "%Y-%m-%d")

_MSG_KEY = None
def _msg_key():
    global _MSG_KEY
    if _MSG_KEY is not None: return _MSG_KEY
    raw = os.environ.get("MSG_ENCRYPTION_KEY", "") or (app.config.get("SECRET_KEY") or "dev")
    _MSG_KEY = hashlib.sha256((raw + "|msg-salt-v1").encode("utf-8")).digest()
    return _MSG_KEY

def _ks(iv, length):
    key = _msg_key(); out = bytearray(); ctr = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + iv + ctr.to_bytes(4, "big")).digest()); ctr += 1
    return bytes(out[:length])

def encrypt_message(plaintext):
    if plaintext is None: plaintext = ""
    data = plaintext.encode("utf-8")
    iv = secrets.token_bytes(12)
    ct = bytes(a ^ b for a, b in zip(data, _ks(iv, len(data))))
    tag = hmac.new(_msg_key(), iv + ct, hashlib.sha256).digest()
    return "enc1:" + base64.urlsafe_b64encode(iv + tag + ct).decode("ascii")

def decrypt_message(token):
    if not token: return ""
    if not token.startswith("enc1:"): return token
    try: raw = base64.urlsafe_b64decode(token[5:].encode("ascii"))
    except Exception: return ""
    if len(raw) < 44: return ""
    iv, tag, ct = raw[:12], raw[12:44], raw[44:]
    expected = hmac.new(_msg_key(), iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag): return ""
    plain = bytes(a ^ b for a, b in zip(ct, _ks(iv, len(ct))))
    try: return plain.decode("utf-8")
    except Exception: return ""

IMAGE_EXT = {"png","jpg","jpeg","gif","webp","bmp","heic"}
VIDEO_EXT = {"mp4","webm","mov","m4v","ogg","ogv","avi","mkv","3gp","mpeg","mpg"}
AUDIO_EXT = {"mp3","m4a","wav","aac","ogg","oga","opus","flac","amr","3gp","weba","webm"}
IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n","png"),(b"\xff\xd8\xff","jpg"),(b"GIF87a","gif"),(b"GIF89a","gif"),(b"RIFF","webp"),(b"BM","bmp")]

def _is_video_head(h):
    if len(h) < 12: return False
    if h[4:8] == b"ftyp": return True
    if h.startswith(b"\x1a\x45\xdf\xa3"): return True
    if h.startswith(b"OggS"): return True
    if h.startswith(b"RIFF") and h[8:12] == b"AVI ": return True
    if h.startswith(b"\x00\x00\x01\xba"): return True
    if h.startswith(b"FLV"): return True
    return False

def check_image_magic(fs):
    try: head = fs.stream.read(32); fs.stream.seek(0)
    except Exception: return False
    return any(head.startswith(m) for m, _ in IMAGE_MAGIC)

def check_video_magic(fs):
    try: head = fs.stream.read(32); fs.stream.seek(0)
    except Exception: return False
    return _is_video_head(head)

def check_audio_magic(fs):
    try: head = fs.stream.read(64); fs.stream.seek(0)
    except Exception: return False
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"): return True
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE": return True
    if head.startswith(b"OggS"): return True
    if head.startswith(b"fLaC"): return True
    if head.startswith(b"#!AMR"): return True
    return False

def allowed_image(fn): return "." in fn and fn.rsplit(".",1)[1].lower() in IMAGE_EXT
def allowed_video(fn): return "." in fn and fn.rsplit(".",1)[1].lower() in VIDEO_EXT
def allowed_audio(fn): return "." in fn and fn.rsplit(".",1)[1].lower() in AUDIO_EXT

CODE_ALPHABET = string.ascii_uppercase + string.digits
def gen_recovery_code(): return "".join(secrets.choice(CODE_ALPHABET) for _ in range(20))
def hash_recovery_code(c): return hashlib.sha256(c.strip().upper().encode()).hexdigest()
def format_code(c):
    c = c.strip().upper()
    return "-".join(c[i:i+4] for i in range(0, len(c), 4))
def gen_public_id(): return "".join(random.choices(string.digits, k=8))
def gen_device_token(): return secrets.token_urlsafe(32)

# ==================== MODELS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(8), unique=True, default=gen_public_id, nullable=False)
    username = db.Column(db.String(5), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    recovery_hash = db.Column(db.String(64), default="", index=True)
    nickname = db.Column(db.String(64), default="")
    bio = db.Column(db.String(200), default="")
    avatar = db.Column(db.String(300), default="")
    is_banned = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    verified_color = db.Column(db.String(200), default="#000000")
    created_at = db.Column(db.DateTime, default=utc_now)
    last_seen = db.Column(db.DateTime, default=utc_now)
    profile_views = db.Column(db.Integer, default=0)
    dark_mode = db.Column(db.Boolean, default=False)
    mood_text = db.Column(db.String(30), default="")
    verified_until = db.Column(db.DateTime, nullable=True)
    last_username_change = db.Column(db.DateTime, nullable=True)
    @property
    def nickname_ok(self):
        if not self.nickname: return False
        parts = [p for p in self.nickname.split() if len(p) >= 1]
        return 1 <= len(parts) <= 4
    @property
    def short_name(self): return self.nickname if self.nickname else self.username
    @property
    def is_online(self):
        if not self.last_seen: return False
        return (now_utc_naive() - self.last_seen).total_seconds() < 120

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    media = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(10), default="")
    reactions = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utc_now)
    is_read = db.Column(db.Boolean, default=False)
    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])
    @property
    def body_plain(self): return decrypt_message(self.body or "")

class ChatReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("chat_message.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    emoji = db.Column(db.String(16), default="👍")
    __table_args__ = (db.UniqueConstraint("message_id","user_id"),)

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    addressee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(10), default="pending")
    created_at = db.Column(db.DateTime, default=utc_now)
    __table_args__ = (db.UniqueConstraint("requester_id","addressee_id"),)

class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.String(300), default="")
    media = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(10), default="")
    created_at = db.Column(db.DateTime, default=utc_now)
    user = db.relationship("User", backref="statuses")

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    media = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(10), default="")
    is_hidden = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)
    user = db.relationship("User", foreign_keys=[user_id])

class PostReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    emoji = db.Column(db.String(16), default="👍")
    __table_args__ = (db.UniqueConstraint("post_id","user_id"),)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=utc_now, index=True)
    user = db.relationship("User", foreign_keys=[user_id])

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), default="info")
    title = db.Column(db.String(120), default="")
    body = db.Column(db.String(500), default="")
    link = db.Column(db.String(300), default="")
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    kind = db.Column(db.String(20), default="post")
    target_id = db.Column(db.Integer, nullable=False)
    target_user_id = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.String(300), default="")
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    reporter = db.relationship("User", foreign_keys=[reporter_id])

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(8), unique=True, default=gen_public_id, nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), default="")
    avatar = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    owner = db.relationship("User", foreign_keys=[owner_id])

class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(10), default="member")
    joined_at = db.Column(db.DateTime, default=utc_now)
    user = db.relationship("User", foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint("group_id","user_id"),)

class GroupMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=utc_now)
    sender = db.relationship("User", foreign_keys=[sender_id])
    @property
    def body_plain(self): return decrypt_message(self.body or "")

class Mention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("group_message.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False, index=True)
    mentioned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    is_everyone = db.Column(db.Boolean, default=False)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

class VerificationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), default="personal")
    id_doc = db.Column(db.String(300), default="")
    financial_doc = db.Column(db.String(300), default="")
    company_doc = db.Column(db.String(300), default="")
    status = db.Column(db.String(10), default="pending")
    admin_note = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=utc_now)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])

class PaymentInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    method = db.Column(db.String(30), default="bank")
    account = db.Column(db.String(120), default="")
    owner_name = db.Column(db.String(120), default="")
    note = db.Column(db.String(200), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)

class Ad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    body = db.Column(db.String(300), default="")
    image = db.Column(db.String(300), default="")
    link = db.Column(db.String(300), default="")
    phone = db.Column(db.String(30), default="")
    advertiser = db.Column(db.String(100), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)

class StickerPack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    cover = db.Column(db.String(300), default="")
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)

class Sticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pack_id = db.Column(db.Integer, db.ForeignKey("sticker_pack.id"), nullable=False)
    media = db.Column(db.String(300), nullable=False)
    media_type = db.Column(db.String(10), default="image")
    created_at = db.Column(db.DateTime, default=utc_now)

class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    summary = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

def init_db():
    with app.app_context():
        db.create_all()
        try:
            from sqlalchemy import inspect, text as _sql_text
            insp = inspect(db.engine)
            tables_cols = {
                "user": [("verified_until", "TIMESTAMP"), ("last_username_change", "TIMESTAMP")],
                "chat_message": [("reactions", "TEXT")],
            }
            for tbl, cols in tables_cols.items():
                if tbl in insp.get_table_names():
                    existing = {c["name"] for c in insp.get_columns(tbl)}
                    for col, typ in cols:
                        if col not in existing:
                            try:
                                db.session.execute(_sql_text(f'ALTER TABLE "{tbl}" ADD COLUMN {col} {typ}'))
                                db.session.commit()
                                print(f"[migrate] added: {tbl}.{col}")
                            except Exception as e:
                                db.session.rollback()
                                print(f"[migrate] skip: {e}")
        except Exception as e:
            print(f"[migrate] warn: {e}")
            db.session.rollback()
        try:
            defaults = {"splash_enabled":"1","splash_image":"","splash_seconds":"5"}
            for k, v in defaults.items():
                if not SiteSetting.query.filter_by(key=k).first():
                    db.session.add(SiteSetting(key=k, value=v))
            db.session.commit()
        except Exception: db.session.rollback()

init_db()

def get_setting(key, default=""):
    s = SiteSetting.query.filter_by(key=key).first()
    return s.value if s else default
def set_setting(key, value):
    s = SiteSetting.query.filter_by(key=key).first()
    if s: s.value = value
    else: db.session.add(SiteSetting(key=key, value=value))
    db.session.commit()

@login_manager.user_loader
def load_user(uid):
    try: return db.session.get(User, int(uid))
    except Exception: return None

def is_valid_username(u): return bool(re.match(r"^[a-zA-Z0-9_]{3,5}$", u))
def is_valid_nickname(n):
    if not n: return False
    parts = [p for p in n.strip().split() if len(p) >= 1]
    return 1 <= len(parts) <= 4

def avatar_url(user):
    if not user: return ""
    if user.avatar: return url_for("serve_upload", subpath=f"avatars/{user.avatar}")
    return f"https://ui-avatars.com/api/?name={user.username}&background=2aabee&color=ffffff&size=200"
def group_avatar_url(g):
    if not g: return ""
    if g.avatar: return url_for("serve_upload", subpath=f"groups/{g.avatar}")
    return f"https://ui-avatars.com/api/?name={g.name}&background=2aabee&color=ffffff&size=200"
def upload_url(kind, filename): return url_for("serve_upload", subpath=f"{kind}/{filename}")

def html_escape_text(t):
    if t is None: return ""
    return (str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            .replace('"',"&quot;").replace("'","&#39;"))
def linkify_text(t):
    if not t: return ""
    esc = html_escape_text(t)
    return re.sub(r'(https?://[^\s<]+)', r'<a href="\1" target="_blank" rel="noopener" class="chat-link">\1</a>', esc)

def online_status_html(user, show_text=True):
    if not user: return "", ""
    if user.is_online:
        return '<span class="tg-dot tg-dot-on"></span>', '<span class="tg-online">متصل الآن</span>' if show_text else ''
    return '<span class="tg-dot tg-dot-off"></span>', f'<span class="tg-offline">آخر ظهور {time_ago_sd(user.last_seen)}</span>' if show_text else ''

def unread_chat_count(user_id): return ChatMessage.query.filter_by(receiver_id=user_id, is_read=False).count()
def unread_notif_count(user_id): return Notification.query.filter_by(user_id=user_id, is_read=False).count()
def unread_group_mentions_count(user_id): return Mention.query.filter_by(mentioned_user_id=user_id, is_read=False).count()

def get_friends(uid):
    rows = Friendship.query.filter(Friendship.status == "accepted",
        or_(Friendship.requester_id == uid, Friendship.addressee_id == uid)).all()
    ids = [r.addressee_id if r.requester_id == uid else r.requester_id for r in rows]
    return User.query.filter(User.id.in_(ids)).all() if ids else []

def friendship_status(a,b):
    r = Friendship.query.filter(or_(
        and_(Friendship.requester_id == a, Friendship.addressee_id == b),
        and_(Friendship.requester_id == b, Friendship.addressee_id == a))).first()
    if not r: return "none", None
    if r.status == "accepted": return "friends", r
    if r.requester_id == a: return "pending_out", r
    return "pending_in", r

def get_group_member(gid, uid): return GroupMember.query.filter_by(group_id=gid, user_id=uid).first()

def log_activity(kind, summary, user_id=None):
    try:
        db.session.add(ActivityLog(kind=kind, summary=summary[:500], user_id=user_id))
        db.session.commit()
    except Exception: db.session.rollback()

def notify(user_id, kind, title, body, link=""):
    try:
        n = Notification(user_id=user_id, kind=kind, title=title[:120], body=body[:500], link=link[:300])
        db.session.add(n); db.session.commit()
    except Exception: db.session.rollback()

def verified_html(user, large=False):
    if not user or not getattr(user, "is_verified", False): return ""
    color = user.verified_color or "#2aabee"
    size = 28 if large else 20
    return (f'<span style="display:inline-flex;vertical-align:middle;margin-right:4px">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="{color}">'
            f'<path d="M12 1l2.5 3.5L19 5l1.5 4.5L24 12l-3.5 2.5L19 19l-4.5 1.5L12 24l-2.5-3.5L5 19l-1.5-4.5L0 12l3.5-2.5L5 5l4.5-1.5z"/>'
            f'<path d="M10 16l-3-3 1.4-1.4L10 13.2l5.6-5.6L17 9z" fill="#fff"/></svg></span>')

# ==================== STYLE ====================
TG_STYLE = """
<style>
:root{--tg-bg:#fff;--tg-surface:#fff;--tg-sidebar:#f4f4f5;--tg-border:#e5e7eb;
--tg-text:#0f172a;--tg-muted:#64748b;--tg-accent:#2aabee;--tg-accent-2:#229ed9;
--tg-bubble-me:#eeffde;--tg-bubble-them:#fff;--tg-hover:#f1f5f9;
--tg-danger:#ef4444;--tg-success:#10b981;--tg-warning:#f59e0b;
--tg-radius:14px;--tg-radius-sm:10px}
body.dark{--tg-bg:#0e1621;--tg-surface:#17212b;--tg-sidebar:#17212b;--tg-border:#243442;
--tg-text:#e6ebf0;--tg-muted:#8696a0;--tg-hover:#1e2c3a;
--tg-bubble-me:#2b5278;--tg-bubble-them:#182533}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
body{font-family:-apple-system,'Segoe UI','Roboto',Tahoma,system-ui,sans-serif;
background:var(--tg-bg);color:var(--tg-text);line-height:1.5;display:flex;flex-direction:column;min-height:100vh}
a{color:var(--tg-accent);text-decoration:none}a:hover{text-decoration:underline}
h2{font-size:17px;margin-bottom:14px}
.tg-topbar{position:sticky;top:0;z-index:100;background:var(--tg-surface);border-bottom:1px solid var(--tg-border);
padding:10px 14px;display:flex;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.tg-topbar .tg-title{flex:1;font-size:17px;font-weight:800}
.tg-topbar .tg-title-sub{font-size:12px;color:var(--tg-muted);font-weight:500}
.tg-back{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;
border-radius:50%;background:transparent;border:none;cursor:pointer;color:var(--tg-text);padding:0;margin:0}
.tg-back:hover{background:var(--tg-hover)}.tg-back svg{width:22px;height:22px}
.tg-tabs{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--tg-surface);
border-top:1px solid var(--tg-border);display:flex;justify-content:space-around;padding:6px 2px;
box-shadow:0 -1px 4px rgba(0,0,0,.06)}
.tg-tab{flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;padding:5px 1px;
color:var(--tg-muted);font-size:8.5px;font-weight:600;border-radius:8px;text-decoration:none;position:relative;transition:.15s}
.tg-tab:hover{color:var(--tg-accent);text-decoration:none}.tg-tab svg{width:20px;height:20px}
.tg-tab.active{color:var(--tg-accent)}
.tg-tab .tg-badge{position:absolute;top:0;right:calc(50% - 20px);
background:var(--tg-danger);color:#fff;font-size:9px;min-width:16px;height:16px;
border-radius:999px;display:flex;align-items:center;justify-content:center;
padding:0 4px;font-weight:700;border:2px solid var(--tg-surface)}
.tg-page{flex:1;max-width:720px;width:100%;margin:0 auto;padding:14px 14px 80px}
.card{background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:var(--tg-radius);padding:18px 16px;margin-bottom:12px}
.card.center{text-align:center}
label{display:block;font-size:12.5px;color:var(--tg-muted);margin:10px 0 5px;font-weight:600}
input,textarea,select{width:100%;padding:11px 14px;border-radius:var(--tg-radius-sm);
border:1.5px solid var(--tg-border);background:var(--tg-bg);color:var(--tg-text);font-family:inherit;font-size:15px}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--tg-accent)}
textarea{resize:vertical;min-height:80px}
button{width:100%;padding:12px;border:none;border-radius:var(--tg-radius-sm);
background:var(--tg-accent);color:#fff;cursor:pointer;font-size:15px;font-weight:700;margin-top:14px;transition:.15s}
button:hover{background:var(--tg-accent-2)}button:active{transform:scale(.98)}
.pw-wrap{position:relative}.pw-wrap input{padding-left:44px}
.pw-toggle{position:absolute;left:6px;top:50%;transform:translateY(-50%);background:transparent;
border:none;color:var(--tg-muted);font-size:18px;cursor:pointer;width:36px;height:36px;padding:0;margin:0;
display:flex;align-items:center;justify-content:center;border-radius:50%}
.avatar{width:96px;height:96px;border-radius:50%;object-fit:cover;border:3px solid var(--tg-surface);
box-shadow:0 2px 8px rgba(0,0,0,.15);cursor:pointer}
.avatar-sm{width:44px;height:44px;border-radius:50%;object-fit:cover;cursor:pointer;flex-shrink:0}
.tg-dot{display:inline-block;width:11px;height:11px;border-radius:50%;border:2px solid var(--tg-surface)}
.tg-dot-on{background:#22c55e}.tg-dot-off{background:#94a3b8}
.tg-online{color:#22c55e;font-weight:600;font-size:12px}
.tg-offline{color:var(--tg-muted);font-size:12px}
.actions{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.btn{display:block;padding:11px;border-radius:var(--tg-radius-sm);border:1.5px solid var(--tg-border);
font-size:14.5px;font-weight:600;text-align:center;cursor:pointer;transition:.15s;
background:var(--tg-surface);color:var(--tg-text);text-decoration:none}
.btn:hover{background:var(--tg-hover);text-decoration:none}
.btn-primary{background:var(--tg-accent);color:#fff;border-color:var(--tg-accent)}
.btn-danger{color:var(--tg-danger);border-color:var(--tg-danger);background:transparent}
.btn-sm{padding:7px 13px;font-size:13px;width:auto;display:inline-block;margin:0}
.flash{padding:11px 15px;border-radius:var(--tg-radius-sm);margin-bottom:10px;font-size:13.5px;border:1.5px solid;font-weight:500}
.success{background:#f0fdf4;color:#166534;border-color:#86efac}
.error{background:#fef2f2;color:#991b1b;border-color:#fecaca}
.info{background:#eff6ff;color:#1e40af;border-color:#bfdbfe}
.list-item{display:flex;align-items:center;gap:12px;padding:11px 8px;
border-bottom:1px solid var(--tg-border);color:inherit;text-decoration:none;transition:.12s;flex-wrap:wrap}
.list-item:hover{background:var(--tg-hover);text-decoration:none}
.list-item:last-child{border-bottom:none}
.list-item .li-name{font-weight:700;font-size:14.5px}
.list-item .li-sub{font-size:12px;color:var(--tg-muted)}
.empty{text-align:center;color:var(--tg-muted);font-size:14px;padding:24px 0}
.acct-box{background:var(--tg-hover);border-radius:var(--tg-radius-sm);padding:12px 14px;margin-top:12px}
.acct-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--tg-border);gap:8px}
.acct-row:last-child{border-bottom:none}
.acct-row .k{font-size:11.5px;font-weight:700;color:var(--tg-muted);text-transform:uppercase}
.acct-row .v{font-weight:700;font-size:14px;direction:ltr;font-family:'Courier New',monospace;
display:inline-flex;align-items:center;gap:6px}
.copy-btn{background:var(--tg-hover);color:var(--tg-text);border:1px solid var(--tg-border);
border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;padding:3px 9px;width:auto;margin:0}
.tg-chat-head{display:flex;align-items:center;gap:12px;padding:10px 4px;border-bottom:1px solid var(--tg-border);margin-bottom:10px}
.chat-box{background:var(--tg-sidebar);border-radius:var(--tg-radius);padding:14px;
height:65vh;overflow-y:auto;display:flex;flex-direction:column;gap:4px;border:1px solid var(--tg-border)}
.bubble{max-width:78%;padding:8px 12px 6px;border-radius:14px;font-size:14.5px;line-height:1.45;
word-wrap:break-word;box-shadow:0 1px 1px rgba(0,0,0,.06);position:relative}
.bubble.me{align-self:flex-start;background:var(--tg-bubble-me);border-bottom-left-radius:4px}
.bubble.them{align-self:flex-end;background:var(--tg-bubble-them);border-bottom-right-radius:4px;border:1px solid var(--tg-border)}
.bubble .t{font-size:10.5px;color:var(--tg-muted);margin-top:3px;display:flex;align-items:center;gap:4px;justify-content:flex-end}
.bubble img,.bubble video{display:block;border-radius:10px;margin-bottom:4px;max-width:100%;max-height:300px;cursor:pointer}
.bubble-wrap{display:flex;flex-direction:column;width:100%;position:relative}
.bubble-wrap:has(.bubble.me){align-items:flex-start}
.bubble-wrap:has(.bubble.them){align-items:flex-end}
.chat-input{display:flex;gap:8px;margin-top:10px;align-items:center}
.chat-input input:not([type="file"]):not([type="hidden"]){flex:1;margin:0;border-radius:24px;padding:12px 18px;background:var(--tg-hover);border:none}
.chat-input button[type="submit"]{width:46px;height:46px;padding:0;margin:0;border-radius:50%;background:var(--tg-accent);flex-shrink:0;display:flex;align-items:center;justify-content:center}
.chat-input .icon-btn{width:46px;height:46px;border-radius:50%;background:var(--tg-hover);color:var(--tg-muted);border:none;margin:0;flex-shrink:0;display:flex;align-items:center;justify-content:center;padding:0}
.sticker-btn{width:46px;height:46px;border-radius:50%;background:transparent;border:none;font-size:24px;cursor:pointer;flex-shrink:0;padding:0;margin:0;display:flex;align-items:center;justify-content:center}
.tg-post{background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:var(--tg-radius);padding:14px;margin-bottom:12px}
.tg-post .post-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.tg-post .post-head .pn{font-weight:800;font-size:14.5px}
.tg-post .post-head .pt{font-size:11.5px;color:var(--tg-muted)}
.tg-post .post-body{font-size:14.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;margin-bottom:8px}
.tg-post .post-media{max-width:100%;border-radius:var(--tg-radius-sm);margin-bottom:8px;cursor:pointer}
.tg-post .post-foot{display:flex;gap:12px;color:var(--tg-muted);font-size:12.5px;padding-top:8px;border-top:1px solid var(--tg-border);flex-wrap:wrap;align-items:center}
.rxn{background:var(--tg-hover);padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700}
.reactors-row{display:flex;gap:-6px;align-items:center}
.reactors-row img{width:24px;height:24px;border-radius:50%;border:2px solid var(--tg-surface);margin-left:-6px}
.reactors-row img:first-child{margin-left:0}
.comment-box{display:flex;gap:8px;margin-bottom:10px;align-items:flex-start}
.comment-body{flex:1;background:var(--tg-hover);border-radius:12px;padding:8px 12px}
.comment-name{font-weight:700;font-size:13px;color:var(--tg-text);text-decoration:none}
.comment-text{font-size:13px;margin-top:4px;white-space:pre-wrap;word-break:break-word}
.comment-time{font-size:10px;color:var(--tg-muted);margin-top:4px}
.expand-btn{background:transparent;border:none;color:var(--tg-accent);cursor:pointer;font-size:13px;font-weight:700;padding:0;margin:4px 0;width:auto;text-align:right}
.profile-head{display:flex;flex-direction:column;align-items:center;padding:20px 16px;text-align:center}
.mood-cloud{display:inline-block;background:var(--tg-hover);border-radius:14px;padding:6px 14px;font-size:13px;font-weight:600;color:var(--tg-text);margin-top:8px}
.toast-container{position:fixed;top:70px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;max-width:340px}
.toast{background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:10px;padding:12px 16px;
box-shadow:0 8px 24px rgba(0,0,0,.15);font-size:13.5px;font-weight:600;color:var(--tg-text);
pointer-events:auto;transform:translateX(120%);animation:tgToastIn .35s cubic-bezier(.4,0,.2,1) forwards;
border-right:4px solid var(--tg-success)}
.toast.error{border-right-color:var(--tg-danger)}
@keyframes tgToastIn{to{transform:translateX(0)}}
.theme-toggle{position:fixed;top:12px;left:12px;z-index:500;background:var(--tg-surface);border:1px solid var(--tg-border);width:44px;height:44px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0;color:var(--tg-text);font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,.1);transition:.3s}
.theme-toggle:hover{transform:rotate(20deg) scale(1.1)}
.theme-toggle svg{width:24px;height:24px}
.status-ring{display:inline-flex;padding:3px;border-radius:50%;background:linear-gradient(135deg,#2aabee,#22c55e,#2aabee);cursor:pointer}
.status-ring img{width:60px;height:60px;border-radius:50%;object-fit:cover;border:2.5px solid var(--tg-surface);display:block}
.status-view{position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:9000;display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px}
.status-view img,.status-view video{max-width:95vw;max-height:85vh;border-radius:12px;object-fit:contain}
.status-view .stext{color:#fff;font-size:20px;text-align:center;margin-top:16px;max-width:600px;line-height:1.6}
.status-view .close{position:absolute;top:16px;left:16px;color:#fff;font-size:22px;background:rgba(255,255,255,.12);border:none;width:44px;height:44px;border-radius:50%;cursor:pointer;padding:0;margin:0}
.status-view .dl{position:absolute;top:16px;right:16px;color:#fff;font-size:14px;background:rgba(42,171,238,.9);border:none;width:44px;height:44px;border-radius:50%;cursor:pointer;padding:0;margin:0;display:flex;align-items:center;justify-content:center;text-decoration:none}
.ad-card{background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:16px;padding:14px;margin-bottom:12px;box-shadow:0 2px 10px rgba(0,0,0,.08)}
.ad-image-box{width:100%;height:200px;background:var(--tg-hover);border-radius:12px;overflow:hidden;margin-bottom:10px;display:flex;align-items:center;justify-content:center;cursor:pointer}
.ad-image-box img{width:100%;height:100%;object-fit:cover}
.ad-title{font-size:16px;font-weight:800;color:var(--tg-text);margin-bottom:6px}
.ad-body{font-size:13.5px;color:var(--tg-muted);line-height:1.5;margin-bottom:10px}
.ad-btn{display:block;padding:11px;background:#10b981;color:#fff;border-radius:10px;font-weight:800;text-decoration:none;font-size:14px;text-align:center;box-shadow:0 4px 12px rgba(16,185,129,.3);border:none;cursor:pointer}
.ad-btn:hover{background:#059669;color:#fff;text-decoration:none}
.mention-hint{background:var(--tg-hover);border-radius:10px;padding:8px 12px;font-size:12px;color:var(--tg-muted);margin-bottom:8px}
.report-btn{background:transparent;border:none;color:var(--tg-muted);font-size:12px;cursor:pointer;padding:4px 8px;margin:0;width:auto}
.report-btn:hover{color:var(--tg-danger)}
@media (max-width:480px){.tg-page{padding:10px 10px 80px}.card{padding:16px 12px}.chat-box{height:60vh}}
</style>
"""

ICONS = {
    "chat":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>',
    "posts":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 3h18v2H3V3zm0 4h18v2H3V7zm0 4h12v2H3v-2zm0 4h18v2H3v-2zm0 4h12v2H3v-2z"/></svg>',
    "groups":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>',
    "user":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>',
    "shield":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>',
    "back":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>',
    "send":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
    "pin":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 3l-8 8v2h2l8-8V3h-2zM3 21l6-6 2 2-6 6H3v-2z"/></svg>',
    "ads":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c.4.53.8 1.07 1.2 1.6-.99.74-2.24 1.68-3.2 2.4-.4-.53-.8-1.07-1.2-1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4z"/></svg>',
    "bell":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>',
    "moon":'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.5 0 2.91-.33 4.17-.92l-1.5-1.5c-.85.27-1.74.42-2.67.42-4.41 0-8-3.59-8-8s3.59-8 8-8c.93 0 1.82.15 2.67.42l1.5-1.5C14.91 2.33 13.5 2 12 2zm9 8.5l-1.5-1.5-1.5 1.5-1.5-1.5L15 10.5 16.5 12 15 13.5l1.5 1.5 1.5-1.5 1.5 1.5 1.5-1.5-1.5-1.5 1.5-1.5z"/></svg>',
}
def icon(name, size=22, color="currentColor"):
    svg = ICONS.get(name, "")
    if not svg: return ""
    return f'<span style="display:inline-flex;width:{size}px;height:{size}px;color:{color}">{svg}</span>'

def tg_topbar(title, subtitle="", back_url=None):
    back = f'<a class="tg-back" href="{back_url}">{icon("back",22)}</a>' if back_url else ''
    sub = f'<div class="tg-title-sub">{html_escape_text(subtitle)}</div>' if subtitle else ''
    return f'<div class="tg-topbar">{back}<div style="flex:1"><div class="tg-title">{html_escape_text(title)}</div>{sub}</div></div>'

def tg_tabs(active="chats"):
    if not current_user.is_authenticated: return ""
    unread_chat = unread_chat_count(current_user.id)
    unread_notif = unread_notif_count(current_user.id)
    unread_groups = unread_group_mentions_count(current_user.id)
    def badge(n): return f'<span class="tg-badge">{n}</span>' if n > 0 else ''
    items = [
        ("chats", "chat", "الدردشات", url_for("chats"), unread_chat),
        ("groups", "groups", "المجموعات", url_for("groups_list"), unread_groups),
        ("friends", "user", "الأصدقاء", url_for("friends_hub"), 0),
        ("posts", "posts", "المنشورات", url_for("posts_feed"), 0),
        ("notif", "bell", "التنبيهات", url_for("notifications_page"), unread_notif),
        ("verified", "shield", "الموثقون", url_for("verified_list"), 0),
        ("ads", "ads", "إعلانات", url_for("ads_page"), 0),
        ("profile", "user", "حسابي", url_for("profile_me"), 0),
    ]
    tabs = ""
    for key, ic, label, href, count in items:
        cls = "tg-tab active" if key == active else "tg-tab"
        tabs += f'<a class="{cls}" href="{href}">{icon(ic,18)}<span>{label}</span>{badge(count)}</a>'
    return f'<div class="tg-tabs">{tabs}</div>'

FLASH_BLOCK = """{% with msgs=get_flashed_messages(with_categories=true) %}{% for c,m in msgs %}<div class="flash {{c}}">{{m}}</div>{% endfor %}{% endwith %}"""

def render_page(body, title=None, **ctx):
    t = title or SITE_NAME
    dark_class = "dark" if (current_user.is_authenticated and getattr(current_user, "dark_mode", False)) else ""
    # theme toggle as half-sun-half-moon ball
    theme_btn = (
        '<button class="theme-toggle" onclick="toggleDark()" title="تغيير لون الموقع">'
        '<svg viewBox="0 0 24 24"><defs>'
        '<clipPath id="half"><rect x="0" y="0" width="12" height="24"/></clipPath>'
        '</defs>'
        '<circle cx="12" cy="12" r="10" fill="#fbbf24"/>'
        '<circle cx="12" cy="12" r="10" fill="#1f2937" clip-path="url(#half)"/>'
        '<circle cx="12" cy="12" r="4" fill="#0e1621"/>'
        '</svg></button>'
    )
    full = (
        "<!DOCTYPE html><html lang='ar' dir='rtl'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>"
        "<title>{{ t }} — {{ site }}</title>" + TG_STYLE + "</head>"
        "<body class='" + dark_class + "'>"
        + theme_btn +
        "<div class='tg-page'>" + body + "</div>"
        "<div class='toast-container' id='toast-container'></div>"
        "<script>"
        "function toggleDark(){document.body.classList.toggle('dark');"
        "try{fetch('/toggle-dark',{method:'POST',credentials:'same-origin'});}catch(e){}"
        "try{localStorage.setItem('tgdark',document.body.classList.contains('dark')?'1':'0');}catch(e){}}"
        "try{if(localStorage.getItem('tgdark')==='1'&&!document.body.classList.contains('dark'))document.body.classList.add('dark');}catch(e){}"
        "function togglePw(id){var e=document.getElementById(id);if(!e)return;e.type=e.type==='password'?'text':'password';}"
        "function showToast(m,t){t=t||'success';var c=document.getElementById('toast-container');if(!c)return;"
        "var d=document.createElement('div');d.className='toast '+t;d.textContent=m;c.appendChild(d);"
        "setTimeout(function(){d.style.opacity='0';setTimeout(function(){d.remove()},400)},3000);}"
        "function copyText(t,b){var done=function(){if(b){b.textContent='✓';}showToast('تم النسخ')};"
        "var fb=function(){var x=document.createElement('textarea');x.value=t;"
        "document.body.appendChild(x);x.select();try{document.execCommand('copy')}catch(e){}x.remove();done()};"
        "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done).catch(fb)}else{fb()}}"
        # openMedia supports image/video with download and close X
        "function openMedia(u,isVideo){var v=document.getElementById('av-viewer');if(!v){v=document.createElement('div');v.id='av-viewer';"
        "v.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px';"
        "document.body.appendChild(v);}"
        "var inner='';"
        "if(isVideo){inner='<video src=\"'+u+'\" controls autoplay style=\"max-width:95vw;max-height:80vh;border-radius:14px\"></video>';}"
        "else{inner='<img src=\"'+u+'\" style=\"max-width:95vw;max-height:80vh;border-radius:14px\">';}"
        "inner+='<a href=\"'+u+'\" download style=\"position:absolute;top:20px;right:20px;background:rgba(42,171,238,.9);color:#fff;padding:10px 16px;border-radius:10px;text-decoration:none;font-weight:700;font-size:13px\">تحميل</a>';"
        "inner+='<button onclick=\"document.getElementById(\\'av-viewer\\').remove()\" style=\"position:absolute;top:20px;left:20px;background:rgba(255,255,255,.15);color:#fff;border:none;width:44px;height:44px;border-radius:50%;font-size:22px;cursor:pointer;padding:0;margin:0\">✕</button>';"
        "v.innerHTML=inner;v.style.display='flex';}"
        "function openAvatar(u){openMedia(u,false);}"
        "function scrollChat(){var b=document.getElementById('chatbox');if(b)b.scrollTop=b.scrollHeight;}"
        "document.addEventListener('DOMContentLoaded',function(){scrollChat();});"
        "function startLiveUpdates(url,ms){setInterval(function(){"
        "fetch(url+(url.indexOf('?')>=0?'&':'?')+'ajax=1',{credentials:'same-origin'})"
        ".then(function(r){return r.json()}).then(function(d){"
        "if(d.html!==undefined){var b=document.getElementById('chatbox');"
        "if(b){var at=b.scrollTop+b.clientHeight>=b.scrollHeight-40;b.innerHTML=d.html;if(at)b.scrollTop=b.scrollHeight;}}"
        "}).catch(function(){});},ms||2000);}"
        "function toggleComments(pid){var el=document.getElementById('comments-'+pid);if(!el)return;"
        "if(el.style.display==='none'){el.style.display='block';loadComments(pid);}else{el.style.display='none';}}"
        "function loadComments(pid){fetch('/post/'+pid+'/comments-ajax',{credentials:'same-origin'})"
        ".then(function(r){return r.json()}).then(function(d){var box=document.getElementById('comments-list-'+pid);if(box)box.innerHTML=d.html;}).catch(function(){});}"
        "function toggleExpand(id){var s=document.getElementById('short-'+id), f=document.getElementById('full-'+id);"
        "if(s.style.display==='none'){s.style.display='block';f.style.display='none';}else{s.style.display='none';f.style.display='block';}}"
        "function showReactors(pid){fetch('/post/'+pid+'/reactors',{credentials:'same-origin'})"
        ".then(function(r){return r.json()}).then(function(d){var v=document.getElementById('reactors-'+pid);if(v){v.innerHTML=d.html;v.style.display=v.style.display==='none'?'block':'none';}}).catch(function(){});}"
        "function reactMsg(mid,emoji){fetch('/msg/'+mid+'/react',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({emoji:emoji})})"
        ".then(function(r){return r.json()}).then(function(d){if(d.ok){var el=document.getElementById('rxn-'+mid);if(el)el.textContent=d.summary;}}).catch(function(){});}"
        "function showEmojiBar(mid){var bar=document.getElementById('emoji-bar-'+mid);if(!bar)return;bar.style.display=bar.style.display==='none'?'flex':'none';}"
        "function reportItem(kind,targetId){var reason=prompt('سبب الإبلاغ:');if(reason===null)return;"
        "fetch('/report',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:kind,target_id:targetId,reason:reason})})"
        ".then(function(r){return r.json()}).then(function(d){if(d.ok)showToast('تم إرسال البلاغ','success');else showToast(d.error||'خطأ','error');}).catch(function(){});}"
        "</script></body></html>"
    )
    return render_template_string(full, t=t, site=SITE_NAME, **ctx)

@app.route("/uploads/<path:subpath>")
def serve_upload(subpath): return send_from_directory(UPLOAD_DIR, subpath)

@app.route("/verify-files/<path:path>")
def serve_verify(path):
    if not session.get("support_authed"): abort(403)
    return send_from_directory(VERIFY_DIR, path)

@app.route("/toggle-dark", methods=["POST"])
def toggle_dark():
    if current_user.is_authenticated:
        try: current_user.dark_mode = not bool(current_user.dark_mode); db.session.commit()
        except Exception: db.session.rollback()
    return jsonify({"ok": True})

@app.route("/api/unread")
@login_required
def api_unread():
    return jsonify({
        "chats": unread_chat_count(current_user.id),
        "notif": unread_notif_count(current_user.id),
        "groups": unread_group_mentions_count(current_user.id),
    })

@app.route("/report", methods=["POST"])
@login_required
def submit_report():
    data = request.get_json() or {}
    kind = data.get("kind","")
    target_id = data.get("target_id",0)
    reason = (data.get("reason") or "")[:300]
    if kind not in ("post","status","group","ad"): return jsonify({"ok": False, "error": "invalid kind"})
    try: target_id = int(target_id)
    except: return jsonify({"ok": False, "error": "invalid target"})
    target_user_id = None
    if kind == "post":
        p = db.session.get(Post, target_id)
        if p: target_user_id = p.user_id
    elif kind == "status":
        s = db.session.get(Status, target_id)
        if s: target_user_id = s.user_id
    elif kind == "group":
        g = db.session.get(Group, target_id)
        if g: target_user_id = g.owner_id
    db.session.add(Report(reporter_id=current_user.id, kind=kind, target_id=target_id, target_user_id=target_user_id, reason=reason))
    db.session.commit()
    log_activity("report", f"بلاغ {kind} #{target_id} من @{current_user.username}: {reason}", user_id=current_user.id)
    return jsonify({"ok": True})

@app.route("/")
def index():
    if current_user.is_authenticated: return redirect(url_for("chats"))
    return redirect(url_for("splash"))

@app.route("/splash")
def splash():
    if current_user.is_authenticated: return redirect(url_for("chats"))
    if get_setting("splash_enabled","1") != "1": return redirect(url_for("login"))
    img = get_setting("splash_image","")
    sec = int(get_setting("splash_seconds","5") or 5)
    img_html = f'<img src="{img}" onerror="this.style.display=\'none\'">' if img else '<div style="font-size:100px">💬</div>'
    return render_page(f"""
    <div style="position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:#0e1621;z-index:9999;flex-direction:column;gap:20px">
    {img_html}
    <div style="color:#2aabee;font-size:26px;font-weight:900">{SITE_NAME}</div>
    <a href="{url_for('login')}" style="color:#fff;opacity:.7;padding:8px 20px;border-radius:20px;background:rgba(255,255,255,.1);text-decoration:none">تخطي ←</a>
    </div>
    <script>setTimeout(function(){{location.href='{url_for("login")}';}}, {sec*1000});</script>
    """, title="مرحبًا")

@app.route("/register", methods=["GET","POST"])
def register():
    if current_user.is_authenticated: return redirect(url_for("chats"))
    if request.method == "POST":
        u = request.form.get("username","").strip().lower().lstrip("@")
        pw = request.form.get("password",""); cf = request.form.get("confirm","")
        if not is_valid_username(u): flash("اليوزر 3-5 أحرف.","error"); return redirect(url_for("register"))
        if len(pw) < 8: flash("كلمة المرور 8 أحرف.","error"); return redirect(url_for("register"))
        if pw != cf: flash("غير متطابقتين.","error"); return redirect(url_for("register"))
        if User.query.filter_by(username=u).first(): flash("محجوز.","error"); return redirect(url_for("register"))
        pid = gen_public_id()
        while User.query.filter_by(public_id=pid).first(): pid = gen_public_id()
        recovery = gen_recovery_code()
        user = User(username=u, public_id=pid, password_hash=generate_password_hash(pw), recovery_hash=hash_recovery_code(recovery))
        db.session.add(user); db.session.commit()
        login_user(user, remember=True); session.permanent = True; session["show_recovery"] = recovery
        return redirect(url_for("welcome"))
    return render_page(FLASH_BLOCK + f"""<div class="card"><h2>إنشاء حساب</h2>
    <form method="POST">
    <label>اليوزر</label><input name="username" maxlength="5" required>
    <label>كلمة المرور</label><div class="pw-wrap"><input name="password" id="p1" type="password" required>
    <button type="button" class="pw-toggle" onclick="togglePw('p1')">👁</button></div>
    <label>تأكيد</label><div class="pw-wrap"><input name="confirm" id="p2" type="password" required>
    <button type="button" class="pw-toggle" onclick="togglePw('p2')">👁</button></div>
    <button type="submit">تسجيل</button></form>
    <a href="{url_for('login')}" style="display:block;text-align:center;margin-top:14px;font-size:14px">لديك حساب؟</a></div>""", title="تسجيل")

@app.route("/welcome")
@login_required
def welcome():
    recovery = session.pop("show_recovery", None)
    if not recovery: return redirect(url_for("set_nickname"))
    return render_page(f"""<div class="card center"><h2>مرحبًا</h2>
    <div class="acct-box"><div class="acct-row"><span class="k">USERNAME</span><span class="v">@{current_user.username}</span></div>
    <div class="acct-row"><span class="k">ID</span><span class="v">{current_user.public_id}</span></div></div>
    <div class="flash info" style="margin-top:14px"><b>كود الاستعادة:</b><br><code style="font-size:15px">{format_code(recovery)}</code></div>
    <a class="btn btn-primary" href="{url_for('set_nickname')}">أكمل</a></div>""", title="مرحبًا")

@app.route("/set-nickname", methods=["GET","POST"])
@login_required
def set_nickname():
    if current_user.nickname_ok: return redirect(url_for("chats"))
    if request.method == "POST":
        n = request.form.get("nickname","").strip()
        if not is_valid_nickname(n): flash("اللقب 1-4 كلمات.","error"); return redirect(url_for("set_nickname"))
        current_user.nickname = n; db.session.commit()
        return redirect(url_for("chats"))
    return render_page(FLASH_BLOCK + f"""<div class="card"><h2>اختر لقبك</h2>
    <form method="POST"><input name="nickname" maxlength="64" required>
    <button type="submit">حفظ</button></form></div>""", title="اللقب")

@app.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("chats"))
    if request.method == "POST":
        u = request.form.get("username","").strip().lower().lstrip("@")
        pw = request.form.get("password","")
        user = User.query.filter_by(username=u).first()
        if not user or not check_password_hash(user.password_hash, pw):
            flash("بيانات غير صحيحة.","error"); return redirect(url_for("login"))
        if user.is_banned: flash("الحساب محظور.","error"); return redirect(url_for("login"))
        user.last_seen = now_utc_naive(); db.session.commit()
        login_user(user, remember=True); session.permanent = True
        return redirect(url_for("chats"))
    return render_page(FLASH_BLOCK + f"""<div class="card"><h2>تسجيل الدخول</h2>
    <form method="POST"><label>اليوزر</label><input name="username" required autocomplete="off">
    <label>كلمة المرور</label><div class="pw-wrap"><input name="password" id="lp" type="password" required>
    <button type="button" class="pw-toggle" onclick="togglePw('lp')">👁</button></div>
    <button type="submit">دخول</button></form>
    <a href="{url_for('register')}" style="display:block;text-align:center;margin-top:14px;font-size:14px">تسجيل جديد</a></div>""", title="دخول")

@app.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("login"))

@app.before_request
def before_each_request():
    if not current_user.is_authenticated: return
    if random.random() < 0.15:
        try: current_user.last_seen = now_utc_naive(); db.session.commit()
        except Exception: db.session.rollback()
    allowed = {"login","register","welcome","set_nickname","logout","static","serve_upload","toggle_dark","splash","index","ads_page","api_unread","submit_report"}
    if request.endpoint in allowed: return
    if not current_user.nickname_ok:
        return redirect(url_for("set_nickname"))

# ==================== CHATS ====================
@app.route("/chats")
@login_required
def chats():
    sent = db.session.query(ChatMessage.receiver_id).filter_by(sender_id=current_user.id).distinct().all()
    recv = db.session.query(ChatMessage.sender_id).filter_by(receiver_id=current_user.id).distinct().all()
    peer_ids = {r[0] for r in sent} | {r[0] for r in recv}
    peers = User.query.filter(User.id.in_(peer_ids)).all() if peer_ids else []
    items = []
    for f in peers:
        last = ChatMessage.query.filter(or_(
            and_(ChatMessage.sender_id == current_user.id, ChatMessage.receiver_id == f.id),
            and_(ChatMessage.sender_id == f.id, ChatMessage.receiver_id == current_user.id)
        )).order_by(ChatMessage.created_at.desc()).first()
        unread = ChatMessage.query.filter_by(sender_id=f.id, receiver_id=current_user.id, is_read=False).count()
        items.append((last.created_at if last else f.created_at, f, last, unread))
    items.sort(key=lambda x: -x[0].timestamp() if x[0] else 0)
    rows = ""
    for _, f, last, unread in items:
        preview = "ابدأ الدردشة"
        if last:
            preview = last.body_plain[:40] if last.body else ("📷 صورة" if last.media_type=="image" else "🎥 فيديو" if last.media_type=="video" else "🎤 صوت" if last.media_type=="audio" else "...")
        utag = f'<span style="background:var(--tg-accent);color:#fff;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:700">{unread}</span>' if unread else ''
        dot, _ = online_status_html(f, show_text=False)
        time_str = fmt_sd(last.created_at, "%H:%M") if last else ""
        rows += f'''<a class="list-item" href="{url_for("chat_with",username=f.username)}">
        <div style="position:relative"><img class="avatar-sm" src="{avatar_url(f)}"><div style="position:absolute;bottom:0;right:0">{dot}</div></div>
        <div style="flex:1;min-width:0">
        <div class="li-name">{verified_html(f)}{html_escape_text(f.short_name)} {utag}</div>
        <div class="li-sub" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{html_escape_text(preview)}</div>
        </div><div style="font-size:11px;color:var(--tg-muted)">{time_str}</div></a>'''
    if not rows: rows = '<p class="empty">لا محادثات بعد. ابحث عن شخص لبدء المحادثة.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("الدردشات", SITE_NAME) + f"""
    <div style="display:flex;gap:8px;margin-bottom:12px">
    <a class="btn btn-sm btn-primary" href="{url_for('discover')}">+ محادثة جديدة</a>
    <a class="btn btn-sm" href="{url_for('friends_hub')}">الأصدقاء</a>
    </div>
    <div class="card" style="padding:6px 4px">{rows}</div>
    """ + tg_tabs("chats"), title="الدردشات")

def render_bubble_chat(m, current_user, peer):
    cls = "me" if m.sender_id == current_user.id else "them"
    plain = m.body_plain
    media_html = ""
    if m.media:
        if m.media_type == "sticker":
            st_url = upload_url("stickers", m.media)
            media_html = f'<img src="{st_url}" style="max-width:120px;max-height:120px;object-fit:contain">'
        else:
            url = upload_url("chats", m.media)
            if m.media_type == "video":
                media_html = f'<video src="{url}" onclick="openMedia(\'{url}\',true)" style="cursor:pointer"></video>'
            elif m.media_type == "audio":
                media_html = (f'<div style="display:flex;align-items:center;gap:8px;background:rgba(0,0,0,.06);border-radius:18px;padding:6px 10px;min-width:200px">'
                    f'<svg viewBox="0 0 24 24" fill="#2aabee" width="20" height="20"><path d="M8 5v14l11-7z"/></svg>'
                    f'<audio src="{url}" controls style="flex:1;height:32px"></audio></div>')
            else:
                media_html = f'<img src="{url}" onclick="openMedia(\'{url}\',false)" style="cursor:pointer">'
    body_html = f'<div>{linkify_text(plain)}</div>' if plain else ""
    seen = '✓✓' if (cls == "me" and m.is_read) else ('✓' if cls == "me" else '')
    reactions = ChatReaction.query.filter_by(message_id=m.id).all()
    counts = {}
    for r in reactions: counts[r.emoji] = counts.get(r.emoji, 0) + 1
    rxn_summary = " ".join([f"{e}{c}" for e,c in counts.items()])
    rxn_display = f'<span style="background:var(--tg-hover);padding:1px 6px;border-radius:10px;font-size:11px;margin-top:4px;display:inline-block" id="rxn-{m.id}">{rxn_summary}</span>' if rxn_summary else f'<span id="rxn-{m.id}"></span>'
    emoji_bar = (
        f'<div id="emoji-bar-{m.id}" style="display:none;gap:4px;margin-top:6px;padding:4px 6px;background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:20px;width:fit-content">'
        + "".join([f'<button type="button" onclick="reactMsg({m.id},\'{e}\')" style="background:none;border:none;font-size:18px;cursor:pointer;padding:2px 4px;margin:0;width:auto">{e}</button>' for e in ["👍","❤️","😂","😮","😢","🙏"]])
        + '</div>'
    )
    return (f'<div class="bubble-wrap"><div class="bubble {cls}">{media_html}{body_html}'
            f'<span class="t">{seen} {fmt_sd(m.created_at,"%H:%M")}</span>'
            f'{rxn_display}'
            f'<button type="button" onclick="showEmojiBar({m.id})" style="background:transparent;border:none;color:var(--tg-muted);cursor:pointer;font-size:14px;padding:0;margin:2px 0 0;width:auto">😊</button>'
            f'{emoji_bar}</div></div>')

@app.route("/chat/<username>", methods=["GET","POST"])
@login_required
def chat_with(username):
    peer = User.query.filter_by(username=username.lower().lstrip("@")).first_or_404()
    if peer.id == current_user.id: flash("لا يمكنك محادثة نفسك.","error"); return redirect(url_for("chats"))
    if request.method == "POST":
        body = request.form.get("body","").strip()
        f = request.files.get("media")
        media_fn = ""; media_type = ""
        if f and f.filename:
            low = f.filename.lower()
            if allowed_video(low) and check_video_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(CHAT_DIR, fn)); media_fn = fn; media_type = "video"
            elif allowed_image(low) and check_image_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(CHAT_DIR, fn)); media_fn = fn; media_type = "image"
        if not body and not media_fn: return redirect(url_for("chat_with", username=peer.username))
        cm = ChatMessage(sender_id=current_user.id, receiver_id=peer.id, body=encrypt_message(body[:2000]) if body else "", media=media_fn, media_type=media_type)
        db.session.add(cm); db.session.commit()
        notify(peer.id, "message", f"رسالة من {current_user.short_name}", (body[:100] or "[مرفق]"), url_for("chat_with", username=current_user.username))
        return redirect(url_for("chat_with", username=peer.username))
    ChatMessage.query.filter_by(sender_id=peer.id, receiver_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    msgs = ChatMessage.query.filter(or_(
        and_(ChatMessage.sender_id == current_user.id, ChatMessage.receiver_id == peer.id),
        and_(ChatMessage.sender_id == peer.id, ChatMessage.receiver_id == current_user.id)
    )).order_by(ChatMessage.created_at.asc()).limit(500).all()
    if request.args.get("ajax") == "1":
        return jsonify({"html": "".join(render_bubble_chat(m, current_user, peer) for m in msgs)})
    bubbles = "".join(render_bubble_chat(m, current_user, peer) for m in msgs)
    dot, stext = online_status_html(peer)
    return render_page(
        f"""
        <div class="tg-chat-head">
        <a class="tg-back" href="{url_for('chats')}">{icon('back',22)}</a>
        <img class="avatar-sm" src="{avatar_url(peer)}" onclick="openAvatar('{avatar_url(peer)}')">
        <div style="flex:1"><div style="font-weight:800;font-size:15.5px">{verified_html(peer)}{html_escape_text(peer.short_name)}</div>
        <div style="color:var(--tg-muted);font-size:12px">{stext}</div></div>
        </div>
        <div class="chat-box" id="chatbox">{bubbles}</div>
        <form class="chat-input" method="POST" enctype="multipart/form-data">
        <input type="file" name="media" id="mi" accept="image/*,video/*" style="display:none">
        <button type="button" class="icon-btn" onclick="document.getElementById('mi').click()" title="إرسال صورة أو فيديو">{icon('pin',22)}</button>
        <input name="body" placeholder="رسالة..." autocomplete="off">
        <button type="submit">{icon('send',22)}</button>
        </form>
        <script>startLiveUpdates('{url_for("chat_with",username=peer.username)}',1500);</script>
        """ + tg_tabs("chats"), title=peer.short_name)

@app.route("/msg/<int:mid>/react", methods=["POST"])
@login_required
def msg_react(mid):
    m = db.session.get(ChatMessage, mid)
    if not m: return jsonify({"ok": False}), 404
    data = request.get_json() or {}
    emoji = (data.get("emoji") or "👍").strip()[:8]
    existing = ChatReaction.query.filter_by(message_id=mid, user_id=current_user.id).first()
    if existing:
        if existing.emoji == emoji: db.session.delete(existing)
        else: existing.emoji = emoji
    else:
        db.session.add(ChatReaction(message_id=mid, user_id=current_user.id, emoji=emoji))
    db.session.commit()
    reactions = ChatReaction.query.filter_by(message_id=mid).all()
    counts = {}
    for r in reactions: counts[r.emoji] = counts.get(r.emoji, 0) + 1
    return jsonify({"ok": True, "summary": " ".join([f"{e}{c}" for e,c in counts.items()])})
    # ==============================================================================
# SUDANESE-X v31 — PART 2/3
# ==============================================================================

@app.route("/posts")
@login_required
def posts_feed():
    session["last_posts_seen_ts"] = int(time.time())
    posts = Post.query.filter_by(is_hidden=False).order_by(Post.created_at.desc()).limit(50).all()
    rows = ""
    for p in posts:
        u = p.user
        if not u: continue
        media = ""
        if p.media:
            url = upload_url("statuses", p.media)
            if p.media_type == "video":
                media = f'<video class="post-media" src="{url}" onclick="openMedia(\'{url}\',true)"></video>'
            else:
                media = f'<img class="post-media" src="{url}" onclick="openMedia(\'{url}\',false)">'
        reactions = PostReaction.query.filter_by(post_id=p.id).all()
        counts = {}
        for r in reactions: counts[r.emoji] = counts.get(r.emoji, 0) + 1
        reaction_summary = " ".join([f"{e}{c}" for e,c in counts.items()]) or ""
        top_reactors = reactions[:5]
        avatars_html = ""
        for rr in top_reactors:
            ru = db.session.get(User, rr.user_id)
            if ru: avatars_html += f'<img src="{avatar_url(ru)}">'
        avatars_block = f'<div class="reactors-row">{avatars_html}</div>' if avatars_html else ""
        react_url = url_for("post_react", pid=p.id)
        emoji_picker = (
            '<div class="rxn-bar">'
            + "".join([f'<form method="POST" action="{react_url}" style="display:inline;margin:0"><input type="hidden" name="emoji" value="{e}"><button type="submit" class="rxn-btn">{e}</button></form>' for e in ["👍","❤️","😂","😮","😢","🙏"]])
            + '</div>'
        )
        report_btn = f'<button type="button" class="report-btn" onclick="reportItem(\'post\',{p.id})">🚩 إبلاغ</button>'
        delete_link = ""
        if p.user_id == current_user.id:
            delete_link = (f'<a href="{url_for("delete_post", pid=p.id)}" onclick="return confirm(\'حذف المنشور؟\')" style="color:var(--tg-danger);margin-right:auto;font-size:12px">حذف</a>')
        comments_count = Comment.query.filter_by(post_id=p.id).count()
        body_text = p.body or ""
        lines = body_text.split("\n")
        if len(lines) > 5:
            short_body = "\n".join(lines[:5])
            body_html = (f'<div class="post-body" id="short-{p.id}">{linkify_text(short_body)}...</div>'
                f'<div class="post-body" id="full-{p.id}" style="display:none">{linkify_text(body_text)}</div>'
                f'<button type="button" class="expand-btn" onclick="toggleExpand({p.id})">عرض المزيد</button>') if p.body else ""
        else:
            body_html = f'<div class="post-body">{linkify_text(body_text)}</div>' if p.body else ""
        av = avatar_url(u)
        un = html_escape_text(u.short_name)
        prof_url = url_for("view_profile", username=u.username)
        card = (
            '<div class="tg-post">'
            '<div class="post-head">'
            f'<img class="avatar-sm" src="{av}" onclick="openAvatar(\'{av}\')">'
            f'<div style="flex:1"><a href="{prof_url}" style="color:inherit;text-decoration:none">'
            f'<div class="pn">{verified_html(u)}{un}</div></a>'
            f'<div class="pt">{time_ago_sd(p.created_at)}</div></div>'
            '</div>'
            + body_html + media
            + '<div class="post-foot" style="flex-wrap:wrap;gap:8px">'
            + (f'{avatars_block}<span class="rxn">{reaction_summary}</span>' if reaction_summary else '<span style="color:var(--tg-muted);font-size:12px">لا تفاعلات</span>')
            + f'<button type="button" onclick="showReactors({p.id})" style="background:none;border:none;color:var(--tg-muted);font-size:12px;cursor:pointer;padding:0">👁 المتفاعلون</button>'
            + f'<button type="button" onclick="toggleComments({p.id})" style="background:none;border:none;color:var(--tg-muted);font-size:12px;cursor:pointer;padding:0">💬 {comments_count} تعليق</button>'
            + report_btn + delete_link + '</div>'
            + f'<div id="reactors-{p.id}" style="display:none;margin-top:8px;padding-top:8px;border-top:1px dashed var(--tg-border)"></div>'
            + emoji_picker
            + f'<div id="comments-{p.id}" style="display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--tg-border)">'
              f'<div id="comments-list-{p.id}"></div>'
              f'<form method="POST" action="{url_for("post_comments", pid=p.id)}" style="margin-top:8px">'
              f'<div style="display:flex;gap:6px">'
              f'<input name="body" placeholder="اكتب تعليقاً..." required style="flex:1;padding:8px 12px;font-size:13px;border-radius:20px;margin:0">'
              f'<button type="submit" style="width:auto;padding:8px 14px;margin:0;border-radius:20px">إرسال</button>'
              f'</div></form>'
              f'</div>'
            + '</div>'
        )
        rows += card
    if not rows: rows = '<p class="empty">لا منشورات بعد.</p>'
    return render_page(
        FLASH_BLOCK + tg_topbar("المنشورات", f"{Post.query.count()} منشور")
        + '<a class="btn btn-primary" href="' + url_for('new_post') + '" style="margin-bottom:14px">+ منشور جديد</a>'
        + rows + tg_tabs("posts"), title="المنشورات")

@app.route("/post/new", methods=["GET","POST"])
@login_required
def new_post():
    if request.method == "POST":
        body = request.form.get("body","").strip()
        f = request.files.get("media")
        media_fn = ""; media_type = ""
        if f and f.filename:
            low = f.filename.lower()
            if allowed_video(low) and check_video_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(STATUS_DIR, fn)); media_fn = fn; media_type = "video"
            elif allowed_image(low) and check_image_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(STATUS_DIR, fn)); media_fn = fn; media_type = "image"
        if not body and not media_fn:
            flash("أضف نصاً أو وسائط.","error"); return redirect(url_for("new_post"))
        p = Post(user_id=current_user.id, body=body[:5000], media=media_fn, media_type=media_type)
        db.session.add(p); db.session.commit()
        log_activity("post", f"منشور من @{current_user.username}", user_id=current_user.id)
        return redirect(url_for("posts_feed"))
    return render_page(FLASH_BLOCK + tg_topbar("منشور جديد", back_url=url_for("posts_feed")) + f"""
    <div class="card"><form method="POST" enctype="multipart/form-data">
    <label>النص</label><textarea name="body" maxlength="5000" rows="6"></textarea>
    <label>صورة/فيديو</label><input type="file" name="media" accept="image/*,video/*">
    <button type="submit">نشر</button></form></div>""", title="منشور جديد")

@app.route("/post/<int:pid>/react", methods=["POST"])
@login_required
def post_react(pid):
    p = db.session.get(Post, pid)
    if not p: abort(404)
    emoji = (request.form.get("emoji") or "👍").strip()[:8]
    existing = PostReaction.query.filter_by(post_id=pid, user_id=current_user.id).first()
    if existing:
        if existing.emoji == emoji:
            db.session.delete(existing); db.session.commit()
            return redirect(url_for("posts_feed"))
        existing.emoji = emoji
    else:
        db.session.add(PostReaction(post_id=pid, user_id=current_user.id, emoji=emoji))
    db.session.commit()
    if p.user_id != current_user.id:
        notify(p.user_id, "reaction", f"{current_user.short_name} تفاعل على منشورك", f'{emoji} {(p.body or "[وسائط]")[:80]}', url_for("posts_feed"))
    return redirect(url_for("posts_feed"))

@app.route("/post/<int:pid>/reactors")
@login_required
def post_reactors(pid):
    reactions = PostReaction.query.filter_by(post_id=pid).all()
    html = ""
    for r in reactions:
        u = db.session.get(User, r.user_id)
        if not u: continue
        av = avatar_url(u)
        html += (f'<div style="display:flex;gap:6px;margin-bottom:6px;align-items:center">'
            f'<img class="avatar-sm" src="{av}" style="width:28px;height:28px">'
            f'<a href="{url_for("view_profile", username=u.username)}" style="flex:1;font-size:13px;color:var(--tg-text);text-decoration:none">{verified_html(u)}{html_escape_text(u.short_name)}</a>'
            f'<span style="font-size:18px">{r.emoji}</span></div>')
    if not html: html = '<p style="color:var(--tg-muted);font-size:12px">لا متفاعلين بعد.</p>'
    return jsonify({"html": html})

@app.route("/post/<int:pid>/comments-ajax")
@login_required
def post_comments_ajax(pid):
    comments = Comment.query.filter_by(post_id=pid).order_by(Comment.created_at.desc()).limit(50).all()
    html = ""
    for c in comments:
        u = c.user
        if not u: continue
        av = avatar_url(u)
        html += (f'<div class="comment-box">'
            f'<img class="avatar-sm" src="{av}" onclick="openAvatar(\'{av}\')" style="width:32px;height:32px">'
            f'<div class="comment-body">'
            f'<a href="{url_for("view_profile", username=u.username)}" class="comment-name">{verified_html(u)}{html_escape_text(u.short_name)}</a>'
            f'<div class="comment-text">{linkify_text(c.body)}</div>'
            f'<div class="comment-time">{time_ago_sd(c.created_at)}</div>'
            f'</div></div>')
    if not html: html = '<p style="color:var(--tg-muted);font-size:13px;text-align:center">لا تعليقات. كن الأول!</p>'
    return jsonify({"html": html})

@app.route("/post/<int:pid>/comments", methods=["GET","POST"])
@login_required
def post_comments(pid):
    p = db.session.get(Post, pid)
    if not p or p.is_hidden: abort(404)
    if request.method == "POST":
        body = request.form.get("body","").strip()
        if body:
            c = Comment(post_id=p.id, user_id=current_user.id, body=body[:2000])
            db.session.add(c); db.session.commit()
            if p.user_id != current_user.id:
                notify(p.user_id, "comment", f"{current_user.short_name} علّق على منشورك", body[:100], url_for("posts_feed"))
            flash("تم إضافة التعليق.","success")
        return redirect(url_for("posts_feed"))
    return redirect(url_for("posts_feed"))

@app.route("/post/<int:pid>/delete")
@login_required
def delete_post(pid):
    p = db.session.get(Post, pid)
    if not p: abort(404)
    if p.user_id != current_user.id and not session.get("support_authed"): abort(403)
    p.is_hidden = True; db.session.commit()
    flash("تم الحذف.","success")
    return redirect(url_for("posts_feed"))

# ==================== NOTIFICATIONS ====================
@app.route("/notifications")
@login_required
def notifications_page():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    rows = ""
    kind_icon = {"comment":"💬","message":"📩","status":"📸","verified":"✅","ad":"📢","reaction":"👍","mention":"📣"}
    for n in notifs:
        ic = kind_icon.get(n.kind, "🔔")
        link_attr = f'href="{n.link}"' if n.link else ''
        rows += (f'<a class="list-item" {link_attr}>'
            f'<div style="font-size:22px">{ic}</div>'
            f'<div style="flex:1"><div class="li-name">{html_escape_text(n.title)}</div>'
            f'<div class="li-sub">{html_escape_text(n.body)}</div>'
            f'<div class="li-sub" style="font-size:11px">{time_ago_sd(n.created_at)}</div></div></a>')
    if not rows: rows = '<p class="empty">لا تنبيهات.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("التنبيهات") + f"""
    <div class="card">{rows}</div>
    """ + tg_tabs("notif"), title="التنبيهات")

# ==================== STATUS ====================
@app.route("/feed")
@login_required
def feed():
    session["last_status_seen_ts"] = int(time.time())
    cutoff = now_utc_naive() - timedelta(hours=24)
    sts = Status.query.filter(Status.created_at >= cutoff).order_by(Status.created_at.desc()).all()
    by_user = {}
    for s in sts: by_user.setdefault(s.user_id, []).append(s)
    strip = ""
    for uid, items in by_user.items():
        u = items[0].user
        if u.id == current_user.id: continue
        strip += (f'<a href="javascript:void(0)" onclick="openStatusMenu({uid})" '
            f'style="display:flex;flex-direction:column;align-items:center;gap:4px;text-decoration:none;flex:0 0 auto;width:72px">'
            f'<span class="status-ring"><img src="{avatar_url(u)}"></span>'
            f'<span style="font-size:11px;color:var(--tg-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70px">{html_escape_text(u.short_name)}</span></a>')
    viewers = ""
    for uid, items in by_user.items():
        for s in items:
            m = ""
            if s.media:
                url = upload_url("statuses", s.media)
                m = f'<video src="{url}" controls style="max-width:95vw;max-height:80vh;border-radius:12px"></video>' if s.media_type=="video" else f'<img src="{url}" onclick="openMedia(\'{url}\',false)" style="max-width:95vw;max-height:80vh;border-radius:12px;cursor:pointer">'
            text = f'<div class="stext">{html_escape_text(s.text)}</div>' if s.text else ''
            dl = f'<a class="dl" href="{url}" download title="تحميل">⬇</a>' if s.media else ''
            rep = f'<button type="button" onclick="event.stopPropagation();reportItem(\'status\',{s.id})" style="position:absolute;top:70px;right:16px;background:rgba(239,68,68,.9);color:#fff;border:none;width:44px;height:44px;border-radius:50%;cursor:pointer;padding:0;margin:0">🚩</button>'
            viewers += (f'<div id="sv-{s.id}" onclick="if(event.target===this)this.style.display=\'none\'" class="status-view">'
                f'<button class="close" onclick="event.stopPropagation();this.parentElement.style.display=\'none\'">✕</button>'
                f'{dl}{rep}{m}{text}</div>')
    menu_html = ""
    for uid, items in by_user.items():
        u = items[0].user
        menu_html += (f'<div id="menu-{uid}" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:8500;align-items:center;justify-content:center;padding:20px">'
            f'<div style="background:var(--tg-surface);border-radius:16px;padding:20px;max-width:360px;width:100%">'
            f'<div style="text-align:center;margin-bottom:14px"><img src="{avatar_url(u)}" style="width:72px;height:72px;border-radius:50%;object-fit:cover">'
            f'<div style="font-weight:800;font-size:16px;margin-top:8px">{verified_html(u)}{html_escape_text(u.short_name)}</div></div>'
            f'<a class="btn btn-primary" href="javascript:void(0)" onclick="document.getElementById(\'menu-{uid}\').style.display=\'none\';document.getElementById(\'sv-{items[0].id}\').style.display=\'flex\'">عرض الحالة</a>'
            f'<a class="btn" href="{url_for("view_profile", username=u.username)}" style="margin-top:6px">الملف الشخصي</a>'
            f'<button type="button" onclick="document.getElementById(\'menu-{uid}\').style.display=\'none\'" style="margin-top:6px;background:var(--tg-hover);color:var(--tg-text)">إغلاق</button></div></div>')
    return render_page(FLASH_BLOCK + tg_topbar("الحالات", "24 ساعة") + f"""
    <a class="btn btn-primary" href="{url_for('post_status')}" style="margin-bottom:14px">+ حالة جديدة</a>
    <div class="card"><div style="display:flex;gap:12px;overflow-x:auto;padding-bottom:6px">{strip or '<p class="empty">لا حالات.</p>'}</div></div>
    {viewers}{menu_html}
    <script>function openStatusMenu(uid){{var m=document.getElementById('menu-'+uid);if(m)m.style.display='flex';}}</script>
    """ + tg_tabs("chats"), title="الحالات")

@app.route("/status/new", methods=["GET","POST"])
@login_required
def post_status():
    if request.method == "POST":
        text = request.form.get("text","").strip()
        f = request.files.get("media")
        media_fn = ""; media_type = ""
        if f and f.filename:
            low = f.filename.lower()
            if allowed_video(low) and check_video_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(STATUS_DIR, fn)); media_fn = fn; media_type = "video"
            elif allowed_image(low) and check_image_magic(f):
                fn = f"{uuid.uuid4().hex}.{low.rsplit('.',1)[1]}"
                f.save(os.path.join(STATUS_DIR, fn)); media_fn = fn; media_type = "image"
        if not text and not media_fn: flash("فارغ.","error"); return redirect(url_for("post_status"))
        s = Status(user_id=current_user.id, text=text[:300], media=media_fn, media_type=media_type)
        db.session.add(s); db.session.commit()
        for friend in get_friends(current_user.id):
            notify(friend.id, "status", f"{current_user.short_name} رفع حالة جديدة", (text[:100] or "[وسائط]"), url_for("feed"))
        return redirect(url_for("feed"))
    return render_page(FLASH_BLOCK + tg_topbar("حالة جديدة", back_url=url_for("feed")) + f"""
    <div class="card"><form method="POST" enctype="multipart/form-data">
    <label>النص</label><textarea name="text" maxlength="300"></textarea>
    <label>وسائط</label><input type="file" name="media" accept="image/*,video/*">
    <button type="submit">نشر</button></form></div>""", title="حالة")

# ==================== GROUPS ====================
@app.route("/groups")
@login_required
def groups_list():
    my = db.session.query(Group).join(GroupMember).filter(GroupMember.user_id == current_user.id).all()
    rows = ""
    for g in my:
        members_count = GroupMember.query.filter_by(group_id=g.id).count()
        unread = Mention.query.filter_by(group_id=g.id, mentioned_user_id=current_user.id, is_read=False).count()
        ub = f'<span style="background:var(--tg-danger);color:#fff;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:700;margin-right:6px">{unread}</span>' if unread else ''
        rows += (f'<a class="list-item" href="{url_for("group_chat", gid=g.id)}">'
            f'<img class="avatar-sm" src="{group_avatar_url(g)}" style="border-radius:14px" onclick="event.preventDefault();openAvatar(\'{group_avatar_url(g)}\')">'
            f'<div style="flex:1"><div class="li-name">{ub}{html_escape_text(g.name)}</div>'
            f'<div class="li-sub">{members_count} عضو · ID: {g.public_id}</div></div></a>')
    if not rows: rows = '<p class="empty">لا مجموعات.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("المجموعات") + f"""
    <a class="btn btn-primary" href="{url_for('group_create')}" style="margin-bottom:12px">+ إنشاء مجموعة</a>
    <div class="card" style="padding:6px 4px">{rows}</div>
    """ + tg_tabs("groups"), title="المجموعات")

@app.route("/group/create", methods=["GET","POST"])
@login_required
def group_create():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        desc = request.form.get("description","").strip()
        if len(name) < 2: flash("الاسم قصير.","error"); return redirect(url_for("group_create"))
        pid = gen_public_id()
        while Group.query.filter_by(public_id=pid).first(): pid = gen_public_id()
        g = Group(name=name[:64], description=desc[:500], public_id=pid, owner_id=current_user.id)
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename and allowed_image(avatar_file.filename) and check_image_magic(avatar_file):
            ext = avatar_file.filename.rsplit(".",1)[1].lower()
            fn = f"grp_{uuid.uuid4().hex}.{ext}"
            avatar_file.save(os.path.join(GROUP_DIR, fn)); g.avatar = fn
        db.session.add(g); db.session.flush()
        db.session.add(GroupMember(group_id=g.id, user_id=current_user.id, role="owner"))
        db.session.commit()
        return redirect(url_for("group_chat", gid=g.id))
    return render_page(FLASH_BLOCK + tg_topbar("مجموعة جديدة", back_url=url_for("groups_list")) + f"""
    <div class="card"><form method="POST" enctype="multipart/form-data">
    <label>الاسم</label><input name="name" maxlength="64" required>
    <label>الوصف</label><textarea name="description" maxlength="500"></textarea>
    <label>صورة المجموعة</label><input type="file" name="avatar" accept="image/*">
    <button type="submit">إنشاء</button></form></div>""", title="إنشاء")

@app.route("/group/<int:gid>/profile", methods=["GET","POST"])
@login_required
def group_profile(gid):
    g = db.session.get(Group, gid)
    if not g: abort(404)
    me = get_group_member(gid, current_user.id)
    if request.method == "POST" and me and me.role in ("owner","admin"):
        desc = request.form.get("description","").strip()
        g.description = desc[:500]
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename and allowed_image(avatar_file.filename) and check_image_magic(avatar_file):
            ext = avatar_file.filename.rsplit(".",1)[1].lower()
            fn = f"grp_{uuid.uuid4().hex}.{ext}"
            avatar_file.save(os.path.join(GROUP_DIR, fn))
            if g.avatar:
                try: os.remove(os.path.join(GROUP_DIR, g.avatar))
                except OSError: pass
            g.avatar = fn
        db.session.commit()
        flash("تم الحفظ.","success")
        return redirect(url_for("group_profile", gid=gid))
    members_count = GroupMember.query.filter_by(group_id=gid).count()
    gav = group_avatar_url(g)
    edit_form = ""
    if me and me.role in ("owner","admin"):
        edit_form = (f'<div class="card" style="margin-top:12px">'
            f'<form method="POST" enctype="multipart/form-data">'
            f'<label>تعديل الوصف</label><textarea name="description" maxlength="500">{html_escape_text(g.description or "")}</textarea>'
            f'<label>تعديل الصورة</label><input type="file" name="avatar" accept="image/*">'
            f'<button type="submit">حفظ</button></form></div>')
    return render_page(FLASH_BLOCK + f"""
    <style>
    .grp-profile-header{{position:relative;background:linear-gradient(135deg,#0e1621,#17212b);border-radius:16px;padding:30px 20px;text-align:center;overflow:hidden;margin-bottom:12px}}
    .grp-profile-header img{{width:120px;height:120px;border-radius:24px;object-fit:cover;border:4px solid rgba(255,255,255,.2);cursor:pointer}}
    .grp-profile-header .close-x{{position:absolute;top:10px;left:10px;background:rgba(0,0,0,.6);color:#fff;border:none;width:38px;height:38px;border-radius:50%;font-size:18px;cursor:pointer;padding:0;margin:0;display:flex;align-items:center;justify-content:center}}
    .grp-profile-header .dl-btn{{position:absolute;top:10px;right:10px;background:rgba(42,171,238,.9);color:#fff;border:none;width:38px;height:38px;border-radius:50%;font-size:16px;cursor:pointer;padding:0;margin:0;display:flex;align-items:center;justify-content:center;text-decoration:none}}
    .grp-profile-header h2{{color:#fff;margin-top:12px;font-size:22px;font-weight:800}}
    .grp-profile-header p{{color:#cbd5e1;margin-top:6px;font-size:14px}}
    </style>
    <div class="grp-profile-header">
    <button class="close-x" onclick="history.back()">✕</button>
    <a class="dl-btn" href="{gav}" download>⬇</a>
    <img src="{gav}" onclick="openMedia('{gav}',false)">
    <h2>{html_escape_text(g.name)}</h2>
    <p>{html_escape_text(g.description or "لا يوجد وصف")}</p>
    <p style="margin-top:10px;color:#94a3b8;font-size:12px">ID: {g.public_id} · {members_count} عضو</p>
    </div>
    {edit_form}
    <a class="btn btn-primary" href="{url_for('group_chat', gid=gid)}">فتح المحادثة</a>
    <button type="button" class="report-btn" onclick="reportItem('group',{gid})" style="margin-top:8px;background:transparent;border:1px solid var(--tg-danger);color:var(--tg-danger);padding:10px;border-radius:10px;width:100%;font-weight:700">🚩 إبلاغ عن المجموعة</button>
    """, title="بروفايل المجموعة")

@app.route("/group/<int:gid>/add", methods=["GET","POST"])
@login_required
def group_add_members(gid):
    g = db.session.get(Group, gid)
    if not g: abort(404)
    me = get_group_member(gid, current_user.id)
    if not me or me.role not in ("owner","admin"):
        flash("ليس لديك صلاحية.","error"); return redirect(url_for("group_chat", gid=gid))
    if request.method == "POST":
        username = request.form.get("username","").strip().lower().lstrip("@")
        u = User.query.filter_by(username=username).first()
        if not u: flash("المستخدم غير موجود.","error")
        elif GroupMember.query.filter_by(group_id=gid, user_id=u.id).first(): flash("عضو بالفعل.","error")
        else:
            db.session.add(GroupMember(group_id=gid, user_id=u.id, role="member"))
            db.session.commit()
            notify(u.id, "group", f"تمت إضافتك إلى {g.name}", f"بواسطة @{current_user.username}", url_for("group_chat", gid=gid))
            flash(f"تمت إضافة @{u.username}.","success")
        return redirect(url_for("group_add_members", gid=gid))
    friends = get_friends(current_user.id)
    members = {m.user_id for m in GroupMember.query.filter_by(group_id=gid).all()}
    rows = ""
    for f in friends:
        if f.id in members: continue
        rows += (f'<form method="POST" style="display:inline;margin:0;width:100%">'
            f'<input type="hidden" name="username" value="{f.username}">'
            f'<button type="submit" class="list-item" style="width:100%;text-align:right;border:none;background:var(--tg-surface)">'
            f'<img class="avatar-sm" src="{avatar_url(f)}">'
            f'<div style="flex:1"><div class="li-name">{verified_html(f)}{html_escape_text(f.short_name)}</div>'
            f'<div class="li-sub">@{f.username}</div></div>'
            f'<span style="color:var(--tg-accent);font-weight:700">+ إضافة</span></button></form>')
    if not rows: rows = '<p class="empty">كل أصدقائك أعضاء بالفعل.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("إضافة أعضاء", back_url=url_for("group_chat", gid=gid)) + f"""
    <div class="card">
    <form method="POST" style="display:flex;gap:8px">
    <input name="username" placeholder="أو اكتب @username" style="flex:1;margin:0">
    <button type="submit" style="width:auto;padding:11px 18px;margin:0">إضافة</button>
    </form></div>
    <div class="card" style="padding:6px 4px">{rows}</div>""", title="إضافة أعضاء")

@app.route("/group/<int:gid>/chat", methods=["GET","POST"])
@login_required
def group_chat(gid):
    g = db.session.get(Group, gid)
    if not g: abort(404)
    me = get_group_member(gid, current_user.id)
    if not me: flash("لست عضوًا.","error"); return redirect(url_for("groups_list"))
    if request.method == "POST":
        body = request.form.get("body","").strip()
        if body:
            msg = GroupMessage(group_id=gid, sender_id=current_user.id, body=encrypt_message(body[:2000]))
            db.session.add(msg); db.session.flush()
            mentions_found = re.findall(r'@([a-zA-Z0-9_]{3,5})', body)
            for username in set(mentions_found):
                u = User.query.filter_by(username=username.lower()).first()
                if u and u.id != current_user.id:
                    db.session.add(Mention(message_id=msg.id, group_id=gid, mentioned_user_id=u.id))
                    notify(u.id, "mention", f"تم ذكرك في {g.name}", f"{current_user.short_name}: {body[:80]}", url_for("group_chat", gid=gid))
            if "@all" in body or "@everyone" in body:
                members = GroupMember.query.filter_by(group_id=gid).all()
                for m in members:
                    if m.user_id != current_user.id:
                        db.session.add(Mention(message_id=msg.id, group_id=gid, mentioned_user_id=m.user_id, is_everyone=True))
                        notify(m.user_id, "mention", f"منشن للجميع في {g.name}", f"{current_user.short_name}: {body[:80]}", url_for("group_chat", gid=gid))
            db.session.commit()
        return redirect(url_for("group_chat", gid=gid))
    Mention.query.filter_by(group_id=gid).filter(Mention.mentioned_user_id == current_user.id).update({"is_read": True})
    db.session.commit()
    msgs = GroupMessage.query.filter_by(group_id=gid).order_by(GroupMessage.created_at.asc()).limit(500).all()
    bubbles = ""
    for m in msgs:
        cls = "me" if m.sender_id == current_user.id else "them"
        plain = m.body_plain or ""
        def highlight_mention(match):
            uname = match.group(1)
            return f'<a href="{url_for("view_profile", username=uname)}" style="color:var(--tg-accent);font-weight:700">@{uname}</a>'
        rendered = linkify_text(plain)
        rendered = re.sub(r'@([a-zA-Z0-9_]{3,5})', highlight_mention, rendered)
        body_html = f'<div>{rendered}</div>' if rendered else ""
        header = f'<div style="font-size:11px;color:var(--tg-accent);font-weight:700;margin-bottom:3px">{html_escape_text(m.sender.short_name)}</div>' if m.sender else ""
        bubbles += f'<div class="bubble-wrap"><div class="bubble {cls}">{header}{body_html}<span class="t">{fmt_sd(m.created_at,"%H:%M")}</span></div></div>'
    if request.args.get("ajax") == "1": return jsonify({"html": bubbles})
    members = GroupMember.query.filter_by(group_id=gid).all()
    members_json = ", ".join([f'"{m.user.username}"' for m in members if m.user])
    member_html = "".join([f'<a class="list-item" href="{url_for("view_profile", username=m.user.username)}"><img class="avatar-sm" src="{avatar_url(m.user)}"><div style="flex:1"><div class="li-name">{verified_html(m.user)}{html_escape_text(m.user.short_name)}</div><div class="li-sub">@{m.user.username}</div></div></a>' for m in members if m.user])
    add_btn = f'<a class="btn btn-primary" href="{url_for("group_add_members", gid=gid)}" style="margin-bottom:8px">+ إضافة عضو</a>' if me.role in ("owner","admin") else ""
    gav = group_avatar_url(g)
    return render_page(
        f"""
        <div class="tg-chat-head">
        <a class="tg-back" href="{url_for('groups_list')}">{icon('back',22)}</a>
        <img class="avatar-sm" src="{gav}" style="border-radius:14px" onclick="openMedia('{gav}',false)">
        <div style="flex:1"><a href="{url_for('group_profile', gid=gid)}" style="color:inherit;text-decoration:none"><div style="font-weight:800;font-size:15.5px">{html_escape_text(g.name)}</div></a>
        <div style="color:var(--tg-muted);font-size:12px">ID: {g.public_id} · {len(members)} عضو</div></div>
        <a class="tg-back" href="javascript:void(0)" onclick="document.getElementById('member-list').classList.toggle('show')">👥</a>
        </div>
        <div id="member-list" class="sticker-panel">
        <div style="font-size:12px;color:var(--tg-muted);margin:6px 4px;font-weight:700">الأعضاء ({len(members)})</div>
        {add_btn}{member_html}
        </div>
        <div class="chat-box" id="chatbox">{bubbles}</div>
        <div class="mention-hint"><b>إرشادات:</b> استخدم <b>@username</b> لمنشن شخص، <b>@all</b> لمنشن الجميع.</div>
        <form class="chat-input" method="POST" id="msg-form">
        <input name="body" placeholder="رسالة للمجموعة..." autocomplete="off" id="g-input">
        <button type="submit">{icon('send',22)}</button></form>
        <script>
        startLiveUpdates('{url_for("group_chat", gid=gid)}',1500);
        var members = [{members_json}];
        var inp = document.getElementById('g-input');
        inp.addEventListener('input', function(){{
          var val = this.value;
          var m = val.match(/@([a-zA-Z0-9_]{{0,5}})$/);
          var old = document.getElementById('mention-suggest'); if(old) old.remove();
          if(!m) return;
          var prefix = m[1].toLowerCase();
          var matches = members.filter(function(u){{return u.startsWith(prefix);}}).slice(0,5);
          if(matches.length === 0) return;
          var box = document.createElement('div');
          box.id = 'mention-suggest';
          box.style.cssText = 'position:fixed;bottom:140px;left:10px;right:10px;background:var(--tg-surface);border:1px solid var(--tg-border);border-radius:10px;padding:6px;z-index:500;box-shadow:0 -4px 20px rgba(0,0,0,.2);max-width:720px;margin:0 auto';
          box.innerHTML = matches.map(function(u){{return '<div onclick="pickMention(\\''+u+'\\')" style="padding:8px;cursor:pointer;border-radius:6px;color:var(--tg-text)">@'+u+'</div>';}}).join('');
          document.body.appendChild(box);
        }});
        function pickMention(u){{
          var inp = document.getElementById('g-input');
          inp.value = inp.value.replace(/@([a-zA-Z0-9_]{{0,5}})$/, '@' + u + ' ');
          var box = document.getElementById('mention-suggest'); if(box) box.remove();
          inp.focus();
        }}
        </script>
        """ + tg_tabs("groups"), title=g.name)

# ==================== FRIENDS + DISCOVER ====================
@app.route("/friends")
@login_required
def friends_hub():
    friends = get_friends(current_user.id)
    incoming = Friendship.query.filter_by(addressee_id=current_user.id, status="pending").count()
    outgoing = Friendship.query.filter_by(requester_id=current_user.id, status="pending").count()
    rows = ""
    for f in friends:
        dot, _ = online_status_html(f, show_text=False)
        rows += (f'<a class="list-item" href="{url_for("chat_with", username=f.username)}">'
            f'<div style="position:relative"><img class="avatar-sm" src="{avatar_url(f)}"><div style="position:absolute;bottom:0;right:0">{dot}</div></div>'
            f'<div style="flex:1"><div class="li-name">{verified_html(f)}{html_escape_text(f.short_name)}</div>'
            f'<div class="li-sub">@{f.username}</div></div></a>')
    if not rows: rows = '<p class="empty">لا أصدقاء بعد.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("الأصدقاء", f"{len(friends)} صديق") + f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px">
    <a class="btn btn-primary" href="{url_for('discover')}">🔍 بحث</a>
    <a class="btn" href="{url_for('random_friend')}">🎲 عشوائي</a>
    </div>
    <a class="btn btn-sm" href="{url_for('friends_requests')}" style="margin-bottom:12px">الطلبات ({incoming + outgoing})</a>
    <div class="card" style="padding:6px 4px">{rows}</div>
    """ + tg_tabs("friends"), title="الأصدقاء")

@app.route("/friends/random")
@login_required
def random_friend():
    friend_ids = {u.id for u in get_friends(current_user.id)}
    pending = {r.addressee_id for r in Friendship.query.filter_by(requester_id=current_user.id, status="pending").all()}
    pending |= {r.requester_id for r in Friendship.query.filter_by(addressee_id=current_user.id, status="pending").all()}
    query = User.query.filter(User.is_banned == False, User.id != current_user.id)
    exclude_ids = friend_ids | pending
    if exclude_ids: query = query.filter(~User.id.in_(exclude_ids))
    candidates = query.all()
    if not candidates: flash("لا يوجد مرشحون.","info"); return redirect(url_for("friends_hub"))
    target = random.choice(candidates)
    db.session.add(Friendship(requester_id=current_user.id, addressee_id=target.id, status="pending"))
    db.session.commit()
    flash(f"تم إرسال طلب إلى @{target.username}.","success")
    return redirect(url_for("friends_hub"))

@app.route("/discover")
@login_required
def discover():
    q = request.args.get("q","").strip()
    query = User.query.filter(User.is_banned == False, User.id != current_user.id)
    if q:
        ql = q.lower().lstrip("@")
        query = query.filter(or_(User.username.ilike(f"%{ql}%"), User.public_id.ilike(f"%{ql}%"), User.nickname.ilike(f"%{ql}%")))
    users = query.limit(50).all()
    rows = ""
    for u in users:
        st, _ = friendship_status(current_user.id, u.id)
        if st == "friends": act = '<span style="color:#22c55e;font-size:12px;font-weight:700">صديق</span>'
        elif st == "pending_out": act = '<span style="color:var(--tg-muted);font-size:12px">بانتظار</span>'
        elif st == "pending_in": act = f'<a class="btn btn-sm btn-primary" href="{url_for("friends_requests")}">اقبل</a>'
        else: act = f'<a class="btn btn-sm btn-primary" href="{url_for("friend_request", username=u.username)}">إضافة</a>'
        chat_link = f'<a class="btn btn-sm" href="{url_for("chat_with", username=u.username)}" style="margin-right:4px">💬</a>'
        rows += f'<div class="list-item"><img class="avatar-sm" src="{avatar_url(u)}"><div style="flex:1"><div class="li-name">{verified_html(u)}{html_escape_text(u.short_name)}</div><div class="li-sub">@{u.username}</div></div>{chat_link}{act}</div>'
    if not rows: rows = '<p class="empty">لا نتائج.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("اكتشف أشخاص", back_url=url_for("friends_hub")) + f"""
    <div class="card"><form method="GET" style="display:flex;gap:8px;margin-bottom:10px">
    <input name="q" value="{q}" placeholder="ابحث..." style="flex:1;margin:0">
    <button type="submit" style="width:auto;padding:11px 18px;margin:0">بحث</button></form>{rows}</div>
    """ + tg_tabs("friends"), title="اكتشف")

# ==================== PROFILE ====================
@app.route("/u/<username>")
def view_profile(username):
    user = User.query.filter_by(username=username.lower().lstrip("@")).first()
    if not user or user.is_banned: flash("غير موجود.","error"); return redirect(url_for("index"))
    if not current_user.is_authenticated: return redirect(url_for("login"))
    is_own = current_user.id == user.id
    av = avatar_url(user)
    dot, stext = online_status_html(user)
    mood = f'<div class="mood-cloud">{html_escape_text(user.mood_text)}</div>' if user.mood_text else ""
    st = "none" if is_own else friendship_status(current_user.id, user.id)[0]
    if is_own:
        actions = f'<a class="btn btn-primary" href="{url_for("edit_profile")}">تعديل الحساب</a><a class="btn" href="{url_for("logout")}">خروج</a>'
    elif st == "friends":
        actions = f'<a class="btn btn-primary" href="{url_for("chat_with", username=user.username)}">دردشة</a>'
    elif st == "pending_out": actions = '<div class="btn btn-disabled">بانتظار</div>'
    elif st == "pending_in": actions = f'<a class="btn btn-primary" href="{url_for("friends_requests")}">اقبل</a>'
    else: actions = f'<a class="btn btn-primary" href="{url_for("friend_request", username=user.username)}">إضافة صديق</a>'
    if not is_own:
        actions += f'<a class="btn" href="{url_for("chat_with", username=user.username)}" style="margin-top:6px">💬 محادثة</a>'
    camera = ""
    if is_own:
        camera = f'<a href="{url_for("edit_profile")}" style="position:absolute;bottom:0;left:0;width:32px;height:32px;border-radius:50%;background:#000;color:#fff;display:flex;align-items:center;justify-content:center;font-size:14px;text-decoration:none;border:2px solid var(--tg-surface);box-shadow:0 2px 6px rgba(0,0,0,.4)">📷</a>'
    return render_page(FLASH_BLOCK + tg_topbar(user.short_name, back_url=url_for("chats")) + f"""
    <div class="card center profile-head">
    <div style="position:relative;display:inline-block">
      <img class="avatar" src="{av}" onclick="openAvatar('{av}')">
      {camera}
    </div>
    <div class="name" style="margin-top:10px">{verified_html(user, True)}{html_escape_text(user.short_name)}</div>
    <div style="margin-top:6px;display:flex;align-items:center;gap:6px">{dot}{stext}</div>
    {mood}
    <div class="acct-box" style="text-align:right;width:100%">
    <div class="acct-row"><span class="k">USERNAME</span><span class="v">@{user.username}</span></div>
    <div class="acct-row"><span class="k">ID</span><span class="v">{user.public_id}</span></div>
    </div>
    <div class="actions">{actions}</div></div>
    """ + tg_tabs("profile"), title=user.short_name)

@app.route("/profile/me")
@login_required
def profile_me(): return redirect(url_for("view_profile", username=current_user.username))

@app.route("/profile/edit", methods=["GET","POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        action = request.form.get("action","save")
        if action == "delete_account":
            uid = current_user.id
            Post.query.filter_by(user_id=uid).update({"is_hidden": True})
            Status.query.filter_by(user_id=uid).delete()
            ChatMessage.query.filter(or_(ChatMessage.sender_id == uid, ChatMessage.receiver_id == uid)).delete()
            Comment.query.filter_by(user_id=uid).delete()
            Friendship.query.filter(or_(Friendship.requester_id == uid, Friendship.addressee_id == uid)).delete()
            GroupMember.query.filter_by(user_id=uid).delete()
            GroupMessage.query.filter_by(sender_id=uid).delete()
            u = db.session.get(User, uid)
            db.session.delete(u)
            db.session.commit()
            logout_user()
            flash("تم حذف حسابك بالكامل.","success")
            return redirect(url_for("login"))
        if action == "change_username":
            new_username = request.form.get("new_username","").strip().lower().lstrip("@")
            if not is_valid_username(new_username): flash("يوزر غير صالح (3-5).","error"); return redirect(url_for("edit_profile"))
            if User.query.filter_by(username=new_username).first(): flash("اليوزر محجوز.","error"); return redirect(url_for("edit_profile"))
            if current_user.last_username_change and (now_utc_naive() - current_user.last_username_change) < timedelta(days=30):
                remaining = timedelta(days=30) - (now_utc_naive() - current_user.last_username_change)
                flash(f"يمكنك تغيير اليوزر بعد {remaining.days} يوم.","info"); return redirect(url_for("edit_profile"))
            current_user.username = new_username
            current_user.last_username_change = now_utc_naive()
            db.session.commit()
            flash("تم تغيير اليوزر.","success")
            return redirect(url_for("profile_me"))
        n = request.form.get("nickname","").strip()
        bio = request.form.get("bio","").strip()
        mood = request.form.get("mood_text","").strip()
        if not is_valid_nickname(n): flash("اللقب 1-4 كلمات.","error"); return redirect(url_for("edit_profile"))
        current_user.nickname = n; current_user.bio = bio[:200]; current_user.mood_text = mood[:30]
        f = request.files.get("avatar")
        if f and f.filename and allowed_image(f.filename) and check_image_magic(f):
            ext = f.filename.rsplit(".",1)[1].lower()
            fn = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(AVATAR_DIR, fn))
            if current_user.avatar:
                try: os.remove(os.path.join(AVATAR_DIR, current_user.avatar))
                except OSError: pass
            current_user.avatar = fn
        db.session.commit(); flash("تم.","success"); return redirect(url_for("profile_me"))
    can_change_username = True
    username_msg = ""
    if current_user.last_username_change and (now_utc_naive() - current_user.last_username_change) < timedelta(days=30):
        remaining = timedelta(days=30) - (now_utc_naive() - current_user.last_username_change)
        can_change_username = False
        username_msg = f"يمكنك تغيير اليوزر بعد {remaining.days} يوم"
    delete_btn = f'<a class="btn btn-sm btn-danger" href="{url_for("delete_avatar")}" onclick="return confirm(\'حذف الصورة؟\')" style="margin-top:8px;display:inline-block">حذف الصورة</a>' if current_user.avatar else ''
    disabled_attr = "disabled" if not can_change_username else ""
    opacity_style = "opacity:.5" if not can_change_username else ""
    username_form = (f'<div class="card" style="margin-top:12px"><h2>تغيير اليوزر</h2>'
        f'{f"<div class=flash info>{username_msg}</div>" if username_msg else ""}'
        f'<form method="POST"><input type="hidden" name="action" value="change_username">'
        f'<label>اليوزر الجديد</label><input name="new_username" maxlength="5" placeholder="{current_user.username}" {disabled_attr}>'
        f'<button type="submit" {disabled_attr} style="{opacity_style}">تغيير اليوزر</button></form></div>')
    delete_form = (f'<div class="card" style="margin-top:12px;border:2px solid var(--tg-danger)">'
        f'<h2 style="color:var(--tg-danger)">مسح الحساب</h2>'
        f'<p style="color:var(--tg-muted);font-size:13px;margin-bottom:12px">سيتم حذف حسابك وكل منشوراتك ورسائلك نهائياً.</p>'
        f'<form method="POST" onsubmit="return confirm(\'متأكد 100%؟\');">'
        f'<input type="hidden" name="action" value="delete_account">'
        f'<button type="submit" style="background:var(--tg-danger)">مسح الحساب نهائياً</button></form></div>')
    return render_page(FLASH_BLOCK + tg_topbar("تعديل الحساب", back_url=url_for("profile_me")) + f"""
    <div class="card"><form method="POST" enctype="multipart/form-data">
    <input type="hidden" name="action" value="save">
    <div style="text-align:center;position:relative;display:inline-block;width:100%">
      <img class="avatar" src="{avatar_url(current_user)}" style="cursor:default;display:inline-block">
      <label for="avatar-input" style="position:absolute;bottom:14px;right:calc(50% - 48px);width:32px;height:32px;border-radius:50%;background:#000;color:#fff;display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;border:2px solid var(--tg-surface);box-shadow:0 2px 6px rgba(0,0,0,.4)">📷</label>
    </div>
    <div style="text-align:center">{delete_btn}</div>
    <input type="file" name="avatar" accept="image/*" id="avatar-input" style="display:none">
    <label>اللقب</label><input name="nickname" value="{current_user.nickname}" maxlength="64" required>
    <label>النبذة</label><textarea name="bio" maxlength="200">{current_user.bio}</textarea>
    <label>الحالة المزاجية</label><input name="mood_text" value="{current_user.mood_text}" maxlength="30">
    <button type="submit">حفظ</button></form></div>
    {username_form}
    {delete_form}
    """, title="تعديل")

@app.route("/profile/avatar/delete")
@login_required
def delete_avatar():
    if current_user.avatar:
        try: os.remove(os.path.join(AVATAR_DIR, current_user.avatar))
        except OSError: pass
        current_user.avatar = ""
        db.session.commit()
        flash("تم حذف الصورة.","success")
    return redirect(url_for("edit_profile"))

@app.route("/friends/requests")
@login_required
def friends_requests():
    inc = Friendship.query.filter_by(addressee_id=current_user.id, status="pending").all()
    rows = ""
    for r in inc:
        rows += f'<div class="list-item"><img class="avatar-sm" src="{avatar_url(r.requester)}"><div style="flex:1"><div class="li-name">{r.requester.short_name}</div></div><a class="btn btn-sm btn-primary" href="{url_for("friend_accept", fid=r.id)}">قبول</a><a class="btn btn-sm" href="{url_for("friend_reject", fid=r.id)}">رفض</a></div>'
    if not rows: rows = '<p class="empty">لا طلبات.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("طلبات الصداقة", back_url=url_for("friends_hub")) + f"""
    <div class="card">{rows}</div>""", title="طلبات")

@app.route("/friend/request/<username>")
@login_required
def friend_request(username):
    t = User.query.filter_by(username=username.lower().lstrip("@")).first_or_404()
    if t.id == current_user.id: return redirect(url_for("profile_me"))
    st, _ = friendship_status(current_user.id, t.id)
    if st == "none":
        db.session.add(Friendship(requester_id=current_user.id, addressee_id=t.id, status="pending"))
        db.session.commit(); flash("تم الإرسال.","success")
    return redirect(url_for("view_profile", username=t.username))

@app.route("/friend/accept/<int:fid>")
@login_required
def friend_accept(fid):
    r = db.session.get(Friendship, fid)
    if r and r.addressee_id == current_user.id:
        r.status = "accepted"; db.session.commit(); flash("تم.","success")
    return redirect(url_for("friends_requests"))

@app.route("/friend/reject/<int:fid>")
@login_required
def friend_reject(fid):
    r = db.session.get(Friendship, fid)
    if r and (r.addressee_id == current_user.id or r.requester_id == current_user.id):
        db.session.delete(r); db.session.commit()
    return redirect(url_for("friends_requests"))

# ==================== STICKERS ====================
@app.route("/stickers")
@login_required
def sticker_packs():
    packs = StickerPack.query.filter(or_(StickerPack.owner_id == current_user.id, StickerPack.is_public == True)).order_by(StickerPack.created_at.desc()).all()
    rows = ""
    for p in packs:
        cover = upload_url("stickers", p.cover) if p.cover else ""
        count = Sticker.query.filter_by(pack_id=p.id).count()
        rows += (f'<a class="list-item" href="{url_for("sticker_pack_view", pid=p.id)}">'
            f'<img class="avatar-sm" src="{cover}" style="border-radius:14px;background:var(--tg-hover)">'
            f'<div style="flex:1"><div class="li-name">{html_escape_text(p.name)}</div>'
            f'<div class="li-sub">{count} استيكر</div></div></a>')
    if not rows: rows = '<p class="empty">لا حزم.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("الاستيكرات") + f"""
    <a class="btn btn-primary" href="{url_for('sticker_pack_new')}" style="margin-bottom:12px">+ حزمة جديدة</a>
    <div class="card">{rows}</div>""", title="استيكرات")

@app.route("/stickers/new", methods=["GET","POST"])
@login_required
def sticker_pack_new():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if len(name) < 2: flash("الاسم قصير.","error"); return redirect(url_for("sticker_pack_new"))
        p = StickerPack(name=name[:80], owner_id=current_user.id)
        cover = request.files.get("cover")
        if cover and cover.filename:
            ext = cover.filename.rsplit(".",1)[-1].lower()
            if ext in {"png","jpg","jpeg","webp","gif"}:
                fn = f"pack_{uuid.uuid4().hex}.{ext}"
                cover.save(os.path.join(STICKER_DIR, fn)); p.cover = fn
        db.session.add(p); db.session.commit()
        return redirect(url_for("sticker_pack_view", pid=p.id))
    return render_page(FLASH_BLOCK + tg_topbar("حزمة جديدة", back_url=url_for("sticker_packs")) + f"""
    <div class="card"><form method="POST" enctype="multipart/form-data">
    <label>اسم الحزمة</label><input name="name" maxlength="80" required>
    <label>صورة الغلاف</label><input type="file" name="cover" accept="image/*">
    <button type="submit">إنشاء</button></form></div>""", title="حزمة")

@app.route("/stickers/<int:pid>", methods=["GET","POST"])
@login_required
def sticker_pack_view(pid):
    p = db.session.get(StickerPack, pid)
    if not p: abort(404)
    is_owner = p.owner_id == current_user.id
    if request.method == "POST" and is_owner:
        files = request.files.getlist("stickers")
        added = 0
        for f in files:
            if not f or not f.filename: continue
            ext = f.filename.rsplit(".",1)[-1].lower()
            if ext in {"png","jpg","jpeg","webp","gif"}:
                fn = f"stk_{uuid.uuid4().hex}.{ext}"
                f.save(os.path.join(STICKER_DIR, fn))
                db.session.add(Sticker(pack_id=p.id, media=fn))
                added += 1
        if added: db.session.commit(); flash(f"تم إضافة {added}.","success")
        return redirect(url_for("sticker_pack_view", pid=p.id))
    stickers = Sticker.query.filter_by(pack_id=p.id).order_by(Sticker.created_at.desc()).all()
    grid = "".join([f'<div style="padding:8px;background:var(--tg-hover);border-radius:10px;text-align:center"><img src="{upload_url("stickers", s.media)}" style="width:100px;height:100px;object-fit:contain"></div>' for s in stickers]) or '<p class="empty">لا استيكرات.</p>'
    upload_form = ""
    if is_owner:
        upload_form = f'<div class="card" style="margin-top:12px"><form method="POST" enctype="multipart/form-data"><label>ملفات</label><input type="file" name="stickers" accept="image/*,.gif" multiple><button type="submit">إضافة</button></form></div>'
    return render_page(FLASH_BLOCK + tg_topbar(p.name, f"{len(stickers)} استيكر", back_url=url_for("sticker_packs")) + f"""
    <div class="card"><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px">{grid}</div></div>
    {upload_form}""", title=p.name)

# ==================== ADS ====================
@app.route("/ads")
@login_required
def ads_page():
    ads = Ad.query.filter_by(is_active=True).order_by(Ad.created_at.desc()).all()
    rows = ""
    for a in ads:
        img_url = upload_url("ads", a.image)
        img_html = f'<div class="ad-image-box"><img src="{img_url}" onclick="openMedia(\'{img_url}\',false)"></div>' if a.image else ""
        body = html_escape_text(a.body) if a.body else ""
        adv = html_escape_text(a.advertiser) if a.advertiser else ""
        phone = html_escape_text(a.phone) if a.phone else ""
        title = html_escape_text(a.title)
        if a.link:
            btn = f'<a class="ad-btn" href="{a.link}" target="_blank" rel="noopener">اضغط هنا للتفاصيل ←</a>'
        elif phone:
            wa_phone = phone.replace("+","").replace(" ","").replace("-","")
            btn = f'<a class="ad-btn" href="https://wa.me/{wa_phone}" target="_blank" rel="noopener">تواصل على واتساب ←</a>'
        else:
            btn = '<span class="ad-btn" style="background:#94a3b8;cursor:default">لا يوجد رابط</span>'
        report_btn = f'<button type="button" class="report-btn" onclick="reportItem(\'ad\',{a.id})" style="margin-top:8px;width:100%">🚩 إبلاغ عن الإعلان</button>'
        rows += ('<div class="ad-card">'
            + f'<div class="ad-title">{title}</div>'
            + img_html
            + (f'<div class="ad-body">{body}</div>' if body else '')
            + (f'<div style="font-size:11px;color:var(--tg-muted);margin-bottom:8px">{adv}</div>' if adv else '')
            + btn + report_btn + '</div>')
    if not rows: rows = '<p class="empty">لا إعلانات حالياً.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("الإعلانات", "إعلانات محلية") + f"""
    <div style="margin-bottom:14px">{rows}</div>""", title="الإعلانات")
    # ==============================================================================
# SUDANESE-X v31 — PART 3/3
# ==============================================================================

# ==================== VERIFIED LIST ====================
@app.route("/verified")
@login_required
def verified_list():
    users = User.query.filter(User.is_verified == True, User.is_banned == False).order_by(User.verified_until.asc().nullslast()).all()
    rows = ""
    for u in users:
        until = f'حتى {fmt_sd(u.verified_until,"%Y-%m-%d")}' if u.verified_until else 'موثق'
        rows += (
            f'<a class="list-item" href="{url_for("view_profile", username=u.username)}">'
            f'<img class="avatar-sm" src="{avatar_url(u)}">'
            f'<div style="flex:1"><div class="li-name">{verified_html(u)}{html_escape_text(u.short_name)}</div>'
            f'<div class="li-sub">{until}</div></div></a>'
        )
    if not rows: rows = '<p class="empty">لا موثقين بعد.</p>'
    pay = PaymentInfo.query.filter_by(is_active=True).first()
    if pay:
        pay_block = f"""
        <div class="card">
        <h2>طرق التوثيق</h2>
        <div class="acct-box">
          <div class="acct-row"><span class="k">الطريقة</span><span class="v">{html_escape_text(pay.method)}</span></div>
          <div class="acct-row"><span class="k">الحساب</span><span class="v">{html_escape_text(pay.account)} <button class="copy-btn" onclick="copyText('{pay.account}',this)">نسخ</button></span></div>
          <div class="acct-row"><span class="k">صاحب الحساب</span><span class="v" style="font-family:inherit">{html_escape_text(pay.owner_name)}</span></div>
          {f'<div style="font-size:12px;color:var(--tg-muted);margin-top:6px">{html_escape_text(pay.note)}</div>' if pay.note else ''}
        </div>
        <a class="btn btn-primary" href="{url_for('verify_page')}" style="margin-top:12px">أرسل بيانات التوثيق</a>
        </div>"""
    else:
        pay_block = f"""
        <div class="card center">
        <h2>التوثيق</h2>
        <p style="color:var(--tg-muted);margin-bottom:10px">لم يحدد الأدمن طريقة الدفع بعد.</p>
        <a class="btn btn-primary" href="{url_for('verify_page')}">أرسل بيانات التوثيق</a>
        </div>"""
    return render_page(FLASH_BLOCK + tg_topbar("الموثقون", f"{len(users)} حساب موثق") + f"""
    {pay_block}
    <div class="card"><h2>الحسابات الموثقة ({len(users)})</h2>{rows}</div>
    """ + tg_tabs("verified"), title="الموثقون")

# ==================== VERIFY ====================
VERIFY_DURATION = timedelta(days=7)
VERIFY_COOLDOWN = timedelta(days=7)

@app.route("/verify", methods=["GET","POST"])
@login_required
def verify_page():
    last = VerificationRequest.query.filter_by(user_id=current_user.id).order_by(VerificationRequest.created_at.desc()).first()
    now = utc_now()
    if last and last.status in ("approved","rejected"):
        if last.reviewed_at and (now - last.reviewed_at) < VERIFY_COOLDOWN:
            remaining = VERIFY_COOLDOWN - (now - last.reviewed_at)
            flash(f"يمكنك تقديم طلب توثيق جديد بعد {remaining.days} يوم و{remaining.seconds//3600} ساعة.","info")
            return redirect(url_for("verify_status"))
    pending = VerificationRequest.query.filter_by(user_id=current_user.id, status="pending").first()
    if pending:
        flash("لديك طلب قيد المراجعة.","info")
        return redirect(url_for("verify_status"))
    if current_user.is_verified and current_user.verified_until and current_user.verified_until > utc_now():
        flash("موثّق حتى " + fmt_sd(current_user.verified_until), "info")
        return redirect(url_for("verify_status"))
    pay = PaymentInfo.query.filter_by(is_active=True).first()
    pay_box = ""
    if pay:
        pay_box = f"""
        <div class="acct-box" style="margin-bottom:14px">
          <div class="acct-row"><span class="k">ادفع إلى</span><span class="v">{html_escape_text(pay.method)}</span></div>
          <div class="acct-row"><span class="k">رقم</span><span class="v">{html_escape_text(pay.account)} <button type="button" class="copy-btn" onclick="copyText('{pay.account}',this)">نسخ</button></span></div>
          <div class="acct-row"><span class="k">صاحب</span><span class="v" style="font-family:inherit">{html_escape_text(pay.owner_name)}</span></div>
        </div>"""
    if request.method == "POST":
        kind = request.form.get("kind","personal")
        if kind not in ("personal","company"): kind = "personal"
        id_doc = request.files.get("id_doc")
        fin_doc = request.files.get("financial_doc")
        co_doc = request.files.get("company_doc")
        if not id_doc or not id_doc.filename: flash("أرفق الرقم.","error"); return redirect(url_for("verify_page"))
        if not fin_doc or not fin_doc.filename: flash("أرفق الإشعار.","error"); return redirect(url_for("verify_page"))
        u_folder = os.path.join(VERIFY_DIR, f"u{current_user.id}_{int(time.time())}")
        os.makedirs(u_folder, exist_ok=True)
        def save_doc(f, tag):
            if not f or not f.filename: return ""
            ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else "bin"
            if ext not in IMAGE_EXT and ext != "pdf": return ""
            fn = f"{tag}_{uuid.uuid4().hex[:8]}.{ext}"
            f.save(os.path.join(u_folder, fn))
            return os.path.relpath(os.path.join(u_folder, fn), VERIFY_DIR)
        req = VerificationRequest(user_id=current_user.id, kind=kind,
                                   id_doc=save_doc(id_doc,"id"),
                                   financial_doc=save_doc(fin_doc,"fin"),
                                   company_doc=save_doc(co_doc,"co") if kind == "company" else "")
        db.session.add(req); db.session.commit()
        log_activity("verification", f"طلب توثيق من @{current_user.username}", user_id=current_user.id)
        flash("تم الإرسال.","success"); return redirect(url_for("verify_status"))
    return render_page(FLASH_BLOCK + tg_topbar("التوثيق", back_url=url_for("verified_list")) + f"""
    <div class="card">
    <div class="flash info">يمكنك تقديم طلب توثيق جديد بعد أسبوع من آخر قرار.</div>
    {pay_box}
    <form method="POST" enctype="multipart/form-data">
    <label>النوع</label><select name="kind" onchange="document.getElementById('co-block').style.display=this.value==='company'?'block':'none'">
    <option value="personal">خاص</option><option value="company">شركات</option></select>
    <label>صورة الرقم الوطني/الجواز</label><input type="file" name="id_doc" accept="image/*,.pdf" required>
    <label>صورة الإشعار المالي</label><input type="file" name="financial_doc" accept="image/*,.pdf" required>
    <div id="co-block" style="display:none"><label>تقرير الشركة</label><input type="file" name="company_doc" accept="image/*,.pdf"></div>
    <button type="submit">إرسال</button></form>
    <a class="btn" href="{url_for('verify_status')}" style="margin-top:10px">حالة طلبي</a></div>""", title="توثيق")

@app.route("/verify/status")
@login_required
def verify_status():
    pending = VerificationRequest.query.filter_by(user_id=current_user.id, status="pending").first()
    latest = VerificationRequest.query.filter_by(user_id=current_user.id).order_by(VerificationRequest.created_at.desc()).first()
    info = ""
    if current_user.is_verified and current_user.verified_until:
        info = f'<div class="flash success"><b>موثّق</b> حتى {fmt_sd(current_user.verified_until)}</div>'
    if pending: info += '<div class="flash info">طلب قيد المراجعة.</div>'
    elif latest and latest.status == "rejected":
        info += f'<div class="flash error">مرفوض: {html_escape_text(latest.admin_note or "بدون سبب")}</div>'
    return render_page(FLASH_BLOCK + tg_topbar("حالة التوثيق", back_url=url_for("profile_me")) + f"""
    <div class="card center">{info}
    <div class="actions"><a class="btn btn-primary" href="{url_for('verify_page')}">طلب توثيق</a>
    <a class="btn" href="{url_for('verified_list')}">قائمة الموثقين</a></div></div>""", title="حالة")

# ==================== ADMIN ROOM ====================
@app.route("/admin")
def admin_room():
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        flash("دخول الدعم مطلوب.","error")
        return redirect(url_for("support_login"))
    events = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()
    reports = Report.query.filter_by(is_resolved=False).order_by(Report.created_at.desc()).limit(50).all()
    if request.args.get("ajax") == "1":
        rows = ""
        for e in events:
            rows += f'<div class="list-item"><div style="flex:1"><div class="li-name"><span style="background:var(--tg-accent);color:#fff;font-size:10px;font-weight:800;padding:2px 8px;border-radius:6px;text-transform:uppercase">{e.kind}</span> {html_escape_text(e.summary)}</div><div class="li-sub">{fmt_sd(e.created_at,"%H:%M:%S")}</div></div></div>'
        if not rows: rows = '<p class="empty">لا أحداث.</p>'
        return jsonify({"html": rows})
    events_html = ""
    for e in events:
        events_html += f'<div class="list-item"><div style="flex:1"><div class="li-name"><span style="background:var(--tg-accent);color:#fff;font-size:10px;font-weight:800;padding:2px 8px;border-radius:6px;text-transform:uppercase">{e.kind}</span> {html_escape_text(e.summary)}</div><div class="li-sub">{fmt_sd(e.created_at,"%H:%M:%S")}</div></div></div>'
    if not events_html: events_html = '<p class="empty">لا أحداث.</p>'
    # reports section
    reports_html = ""
    for r in reports:
        reporter = db.session.get(User, r.reporter_id) if r.reporter_id else None
        target_user = db.session.get(User, r.target_user_id) if r.target_user_id else None
        rname = f"@{reporter.username}" if reporter else "مجهول"
        target_name = f"@{target_user.username}" if target_user else "—"
        ban_btn = f'<a class="btn btn-sm btn-danger" href="{url_for("admin_ban_user", uid=target_user.id)}" onclick="return confirm(\'حظر؟\')">حظر</a>' if target_user else ''
        reports_html += (f'<div class="list-item"><div style="flex:1"><div class="li-name">🚩 {r.kind} #{r.target_id} — {target_name}</div>'
            f'<div class="li-sub">من: {rname} · السبب: {html_escape_text(r.reason)}</div>'
            f'<div class="li-sub" style="font-size:11px">{fmt_sd(r.created_at)}</div></div>'
            f'{ban_btn}'
            f'<a class="btn btn-sm" href="{url_for("admin_resolve_report", rid=r.id)}">تجاهل</a></div>')
    if not reports_html: reports_html = '<p class="empty">لا بلاغات.</p>'
    # ads manage
    ads = Ad.query.order_by(Ad.created_at.desc()).limit(20).all()
    ads_html = ""
    for a in ads:
        ads_html += (f'<div class="list-item"><div style="flex:1"><div class="li-name">{html_escape_text(a.title)} {"✅" if a.is_active else "⛔"}</div>'
            f'<div class="li-sub">{html_escape_text(a.advertiser or "")}</div></div>'
            f'<a class="btn btn-sm" href="{url_for("admin_ad_toggle", aid=a.id)}">{"إيقاف" if a.is_active else "تشغيل"}</a>'
            f'<a class="btn btn-sm btn-danger" href="{url_for("admin_ad_delete", aid=a.id)}" onclick="return confirm(\'حذف نهائي؟\')">حذف</a></div>')
    if not ads_html: ads_html = '<p class="empty">لا إعلانات.</p>'
    # posts manage
    posts = Post.query.filter_by(is_hidden=False).order_by(Post.created_at.desc()).limit(20).all()
    posts_html = ""
    for p in posts:
        u = p.user
        posts_html += (f'<div class="list-item"><div style="flex:1"><div class="li-name">{html_escape_text((p.body or "[وسائط]")[:60])}</div>'
            f'<div class="li-sub">@{u.username if u else "?"}</div></div>'
            f'<a class="btn btn-sm btn-danger" href="{url_for("admin_post_hide", pid=p.id)}" onclick="return confirm(\'حذف المنشور؟\')">حذف</a></div>')
    if not posts_html: posts_html = '<p class="empty">لا منشورات.</p>'
    return render_page(tg_topbar("غرفة الإدارة", "مراقبة مباشرة") + f"""
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
    <a class="btn btn-sm btn-primary" href="{url_for('admin_verifications')}">التوثيقات</a>
    <a class="btn btn-sm" href="{url_for('admin_ads')}">إدارة الإعلانات</a>
    <a class="btn btn-sm" href="{url_for('admin_payments')}">الدفع</a>
    <a class="btn btn-sm" href="{url_for('admin_splash')}">Splash</a>
    <a class="btn btn-sm" href="{url_for('support_dashboard')}">الدعم</a>
    </div>
    <div class="card"><h2>🚩 البلاغات ({len(reports)})</h2>{reports_html}</div>
    <div class="card"><h2>📢 إدارة الإعلانات</h2>{ads_html}</div>
    <div class="card"><h2>📝 إدارة المنشورات</h2>{posts_html}</div>
    <div class="card"><h2>📊 آخر الأحداث</h2><div id="admin-events">{events_html}</div></div>
    <script>
    setInterval(function(){{fetch('{url_for("admin_room")}?ajax=1',{{credentials:'same-origin'}})
    .then(function(r){{return r.json()}}).then(function(d){{document.getElementById('admin-events').innerHTML=d.html}});}},5000);
    </script>
    """, title="الإدارة")

@app.route("/admin/ban/<int:uid>")
def admin_ban_user(uid):
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        abort(403)
    u = db.session.get(User, uid)
    if u:
        u.is_banned = True
        Post.query.filter_by(user_id=uid).update({"is_hidden": True})
        Status.query.filter_by(user_id=uid).delete()
        ChatMessage.query.filter(or_(ChatMessage.sender_id == uid, ChatMessage.receiver_id == uid)).delete()
        GroupMessage.query.filter_by(sender_id=uid).delete()
        Comment.query.filter_by(user_id=uid).delete()
        db.session.commit()
        log_activity("ban", f"حظر @{u.username} + إزالة كل محتواه", user_id=uid)
        flash(f"تم حظر @{u.username} وحذف محتواه.","success")
    return redirect(url_for("admin_room"))

@app.route("/admin/report/<int:rid>/resolve")
def admin_resolve_report(rid):
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        abort(403)
    r = db.session.get(Report, rid)
    if r: r.is_resolved = True; db.session.commit()
    flash("تم تجاهل البلاغ.","success")
    return redirect(url_for("admin_room"))

@app.route("/admin/post/<int:pid>/hide")
def admin_post_hide(pid):
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        abort(403)
    p = db.session.get(Post, pid)
    if p:
        p.is_hidden = True; db.session.commit()
        log_activity("admin_post_hide", f"حذف منشور #{pid}", user_id=current_user.id if current_user.is_authenticated else None)
        flash("تم حذف المنشور.","success")
    return redirect(url_for("admin_room"))

@app.route("/admin/ad/<int:aid>/delete")
def admin_ad_delete(aid):
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        abort(403)
    a = db.session.get(Ad, aid)
    if a:
        if a.image:
            try: os.remove(os.path.join(ADS_DIR, a.image))
            except OSError: pass
        db.session.delete(a); db.session.commit()
        flash("تم حذف الإعلان.","success")
    return redirect(url_for("admin_room"))

@app.route("/admin/splash", methods=["GET","POST"])
def admin_splash():
    if not session.get("support_authed") and not (current_user.is_authenticated and current_user.username == "admin"):
        abort(403)
    if request.method == "POST":
        enabled = "1" if request.form.get("enabled") == "1" else "0"
        set_setting("splash_enabled", enabled)
        try:
            sec = int(request.form.get("seconds", 5))
            sec = max(1, min(sec, 30))
        except Exception: sec = 5
        set_setting("splash_seconds", str(sec))
        f = request.files.get("image_file")
        if f and f.filename:
            ext = f.filename.rsplit(".",1)[-1].lower()
            if ext in {"png","jpg","jpeg","webp","gif"}:
                fn = f"splash_{uuid.uuid4().hex}.{ext}"
                f.save(os.path.join(SPLASH_DIR, fn))
                set_setting("splash_image", url_for("serve_upload", subpath=f"splash/{fn}"))
        flash("تم حفظ splash.","success")
        return redirect(url_for("admin_splash"))
    enabled = get_setting("splash_enabled","1") == "1"
    img = get_setting("splash_image","")
    sec = get_setting("splash_seconds","5")
    preview = f'<img src="{img}" style="max-width:100%;border-radius:12px;margin:10px 0">' if img else ""
    checked = "checked" if enabled else ""
    return render_page(FLASH_BLOCK + tg_topbar("شاشة البداية", back_url=url_for("admin_room")) + f"""
    <div class="card">
    <h2>شاشة البداية</h2>
    {preview}
    <form method="POST" enctype="multipart/form-data">
    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
    <input type="checkbox" name="enabled" value="1" {checked} style="width:auto;margin:0">
    <span>تفعيل Splash</span></label>
    <label>صورة شاشة البداية</label>
    <input type="file" name="image_file" accept="image/*">
    <label>المدة (ثواني)</label>
    <input type="number" name="seconds" min="1" max="30" value="{sec}">
    <button type="submit">حفظ</button>
    </form>
    <a class="btn" href="{url_for('admin_room')}" style="margin-top:10px">رجوع</a>
    </div>""", title="Splash")

# ==================== SUPPORT ====================
def support_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not session.get("support_authed"): return redirect(url_for("support_login"))
        return f(*a, **kw)
    return decorated

@app.route("/support", methods=["GET","POST"])
def support_login():
    if request.method == "POST":
        if request.form.get("password","") == SUPPORT_PASSWORD:
            session["support_authed"] = True; session.permanent = True
            return redirect(url_for("support_dashboard"))
        flash("خطأ.","error"); return redirect(url_for("support_login"))
    return render_page(FLASH_BLOCK + tg_topbar("لوحة الدعم") + f"""
    <div class="card"><h2>دخول الدعم</h2>
    <form method="POST"><div class="pw-wrap"><input name="password" id="sp" type="password" required>
    <button type="button" class="pw-toggle" onclick="togglePw('sp')">👁</button></div>
    <button type="submit">دخول</button></form></div>""", title="دعم")

@app.route("/support/logout")
def support_logout():
    session.pop("support_authed", None)
    return redirect(url_for("login"))

@app.route("/support/dashboard")
@support_required
def support_dashboard():
    users_count = User.query.count()
    banned = User.query.filter_by(is_banned=True).count()
    verif_pending = VerificationRequest.query.filter_by(status="pending").count()
    reports_count = Report.query.filter_by(is_resolved=False).count()
    return render_page(FLASH_BLOCK + tg_topbar("لوحة الدعم") + f"""
    <div class="card">
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:10px">
    <div style="background:var(--tg-hover);padding:14px;border-radius:12px;text-align:center">
    <div style="font-size:22px;font-weight:900;color:var(--tg-accent)">{users_count}</div><div style="font-size:11px;color:var(--tg-muted)">مستخدمون</div></div>
    <div style="background:var(--tg-hover);padding:14px;border-radius:12px;text-align:center">
    <div style="font-size:22px;font-weight:900;color:var(--tg-danger)">{banned}</div><div style="font-size:11px;color:var(--tg-muted)">محظورون</div></div>
    <div style="background:var(--tg-hover);padding:14px;border-radius:12px;text-align:center">
    <div style="font-size:22px;font-weight:900;color:var(--tg-warning)">{verif_pending}</div><div style="font-size:11px;color:var(--tg-muted)">توثيقات</div></div>
    <div style="background:var(--tg-hover);padding:14px;border-radius:12px;text-align:center">
    <div style="font-size:22px;font-weight:900;color:var(--tg-danger)">{reports_count}</div><div style="font-size:11px;color:var(--tg-muted)">بلاغات</div></div>
    </div>
    <div class="actions">
    <a class="btn btn-primary" href="{url_for('admin_room')}">غرفة الإدارة</a>
    <a class="btn" href="{url_for('admin_verifications')}">طلبات التوثيق ({verif_pending})</a>
    <a class="btn" href="{url_for('admin_ads')}">إدارة الإعلانات</a>
    <a class="btn" href="{url_for('admin_payments')}">معلومات الدفع</a>
    <a class="btn" href="{url_for('admin_splash')}">Splash Screen</a>
    <a class="btn" href="{url_for('support_users')}">المستخدمون</a>
    <a class="btn" href="{url_for('support_logout')}">خروج</a>
    </div></div>""", title="دعم")

@app.route("/support/users")
@support_required
def support_users():
    users = User.query.order_by(User.created_at.desc()).limit(100).all()
    rows = ""
    for u in users:
        st = '<span style="color:var(--tg-danger)">محظور</span>' if u.is_banned else '<span style="color:var(--tg-success)">نشط</span>'
        ban_a = f'<a class="btn btn-sm btn-danger" href="{url_for("admin_ban_user", uid=u.id)}" onclick="return confirm(\'حظر؟\')">حظر</a>' if not u.is_banned else ''
        rows += f'<div class="list-item"><img class="avatar-sm" src="{avatar_url(u)}"><div style="flex:1"><div class="li-name">{verified_html(u)}{html_escape_text(u.short_name)} {st}</div><div class="li-sub">@{u.username} · ID: {u.public_id}</div></div>{ban_a}</div>'
    return render_page(FLASH_BLOCK + tg_topbar("المستخدمون", back_url=url_for("support_dashboard")) + f"""
    <div class="card">{rows}</div>""", title="مستخدمون")

@app.route("/support/verifications")
@support_required
def admin_verifications():
    reqs = VerificationRequest.query.filter_by(status="pending").order_by(VerificationRequest.created_at.desc()).all()
    rows = ""
    for r in reqs:
        u = r.user
        id_url = url_for("serve_verify", path=r.id_doc) if r.id_doc else ""
        fin_url = url_for("serve_verify", path=r.financial_doc) if r.financial_doc else ""
        co_url = url_for("serve_verify", path=r.company_doc) if r.company_doc else ""
        id_btn = f'<a class="btn btn-sm" href="{id_url}" target="_blank">رقم/جواز</a>' if id_url else ''
        fin_btn = f'<a class="btn btn-sm" href="{fin_url}" target="_blank">إشعار</a>' if fin_url else ''
        co_btn = f'<a class="btn btn-sm" href="{co_url}" target="_blank">شركة</a>' if co_url else ''
        rows += f"""<div class="list-item" style="flex-wrap:wrap">
        <img class="avatar-sm" src="{avatar_url(u)}">
        <div style="flex:1;min-width:200px">
        <div class="li-name">@{u.username} ({r.kind})</div>
        <div class="li-sub">{fmt_sd(r.created_at)}</div>
        <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">{id_btn}{fin_btn}{co_btn}</div></div>
        <div style="display:flex;gap:6px;flex-direction:column;min-width:160px">
        <form method="POST" action="{url_for('admin_verify_decide', rid=r.id)}" style="margin:0">
        <input type="hidden" name="decision" value="approved">
        <input type="number" name="days" value="7" min="1" max="90" style="padding:6px;font-size:12px;margin-bottom:4px">
        <button class="btn btn-sm btn-primary" type="submit">قبول</button></form>
        <form method="POST" action="{url_for('admin_verify_decide', rid=r.id)}" style="margin:0">
        <input type="hidden" name="decision" value="rejected">
        <button class="btn btn-sm btn-danger" type="submit">رفض</button></form>
        </div></div>"""
    if not rows: rows = '<p class="empty">لا طلبات.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("طلبات التوثيق", back_url=url_for("support_dashboard")) + f"""
    <div class="card">{rows}</div>""", title="توثيقات")

@app.route("/support/verifications/<int:rid>/decide", methods=["POST"])
@support_required
def admin_verify_decide(rid):
    r = db.session.get(VerificationRequest, rid)
    if not r: abort(404)
    decision = request.form.get("decision","")
    if decision == "approved":
        r.status = "approved"; r.reviewed_at = now_utc_naive()
        u = r.user
        u.is_verified = True
        days = request.form.get("days", type=int) or 7
        u.verified_until = utc_now() + timedelta(days=days)
        db.session.commit()
        notify(u.id, "verified", "مبروك! تم توثيق حسابك", f"تم توثيق حسابك لمدة {days} يوم، حتى {fmt_sd(u.verified_until)}", url_for("verified_list"))
        flash("تم القبول.","success")
    elif decision == "rejected":
        r.status = "rejected"; r.admin_note = request.form.get("note","")[:500]
        r.reviewed_at = now_utc_naive(); db.session.commit()
        notify(r.user_id, "verified", "طلب التوثيق مرفوض", r.admin_note or "بدون سبب", url_for("verify_status"))
        flash("تم الرفض.","success")
    return redirect(url_for("admin_verifications"))

@app.route("/support/ads", methods=["GET","POST"])
@support_required
def admin_ads():
    if request.method == "POST":
        title = request.form.get("title","").strip()
        if not title: flash("العنوان مطلوب.","error"); return redirect(url_for("admin_ads"))
        a = Ad(title=title[:100], body=request.form.get("body","")[:300],
               link=request.form.get("link","")[:300], phone=request.form.get("phone","")[:30],
               advertiser=request.form.get("advertiser","")[:100])
        img = request.files.get("image")
        if img and img.filename and allowed_image(img.filename) and check_image_magic(img):
            fn = f"ad_{uuid.uuid4().hex}.{img.filename.rsplit('.',1)[1].lower()}"
            img.save(os.path.join(ADS_DIR, fn)); a.image = fn
        db.session.add(a); db.session.commit()
        flash("تم.","success"); return redirect(url_for("admin_ads"))
    ads = Ad.query.order_by(Ad.created_at.desc()).all()
    rows = ""
    for a in ads:
        rows += f'<div class="list-item"><div style="flex:1"><div class="li-name">{html_escape_text(a.title)} {"✅" if a.is_active else "⛔"}</div><div class="li-sub">{html_escape_text(a.advertiser or "")}</div></div><a class="btn btn-sm" href="{url_for("admin_ad_toggle", aid=a.id)}">{"إيقاف" if a.is_active else "تشغيل"}</a><a class="btn btn-sm btn-danger" href="{url_for("admin_ad_delete", aid=a.id)}" onclick="return confirm(\'حذف؟\')">حذف</a></div>'
    if not rows: rows = '<p class="empty">لا إعلانات.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("إعلانات", back_url=url_for("support_dashboard")) + f"""
    <div class="card">
    <form method="POST" enctype="multipart/form-data">
    <label>عنوان الإعلان</label><input name="title" required maxlength="100">
    <label>الوصف (يظهر أسفل الصورة)</label><textarea name="body" maxlength="300" rows="3"></textarea>
    <label>المعلن</label><input name="advertiser" maxlength="100">
    <label>رقم واتساب أو هاتف</label><input name="phone" maxlength="30" placeholder="مثال: +249123456789">
    <label>رابط (زر "اضغط هنا")</label><input name="link" maxlength="300" placeholder="https://...">
    <label>صورة الإعلان (مستطيل)</label><input type="file" name="image" accept="image/*">
    <button type="submit">إضافة الإعلان</button></form>
    <div style="margin-top:14px">{rows}</div></div>""", title="إعلانات")

@app.route("/support/ads/<int:aid>/toggle")
@support_required
def admin_ad_toggle(aid):
    a = db.session.get(Ad, aid)
    if a: a.is_active = not a.is_active; db.session.commit()
    return redirect(url_for("admin_ads"))

# ==================== PAYMENTS ====================
@app.route("/support/payments", methods=["GET","POST"])
@support_required
def admin_payments():
    if request.method == "POST":
        method = request.form.get("method","bank").strip()
        account = request.form.get("account","").strip()
        owner = request.form.get("owner_name","").strip()
        note = request.form.get("note","").strip()
        PaymentInfo.query.update({"is_active": False})
        db.session.add(PaymentInfo(method=method, account=account[:120], owner_name=owner[:120], note=note[:200], is_active=True))
        db.session.commit()
        flash("تم حفظ معلومات الدفع.","success")
        return redirect(url_for("admin_payments"))
    pays = PaymentInfo.query.order_by(PaymentInfo.created_at.desc()).all()
    rows = ""
    for p in pays:
        rows += (f'<div class="list-item"><div style="flex:1"><div class="li-name">{html_escape_text(p.method)} — {html_escape_text(p.account)}</div>'
                 f'<div class="li-sub">{html_escape_text(p.owner_name)}</div></div>'
                 f'<a class="btn btn-sm" href="{url_for("admin_payment_toggle", pid=p.id)}">{"إيقاف" if p.is_active else "تشغيل"}</a>'
                 f'<a class="btn btn-sm btn-danger" href="{url_for("admin_payment_delete", pid=p.id)}" onclick="return confirm(\'حذف؟\')">حذف</a></div>')
    if not rows: rows = '<p class="empty">لا معلومات دفع.</p>'
    return render_page(FLASH_BLOCK + tg_topbar("معلومات الدفع", back_url=url_for("support_dashboard")) + f"""
    <div class="card">
    <form method="POST">
    <label>طريقة الدفع</label>
    <select name="method">
      <option value="بنك">بنك</option><option value="MBank">MBank</option><option value="Fawry">Fawry</option>
      <option value="Vodafone Cash">Vodafone Cash</option><option value="Zain Cash">Zain Cash</option><option value="MTN MoMo">MTN MoMo</option>
    </select>
    <label>رقم الحساب</label><input name="account" maxlength="120" required>
    <label>اسم صاحب الحساب</label><input name="owner_name" maxlength="120">
    <label>ملاحظة</label><input name="note" maxlength="200">
    <button type="submit">حفظ وتفعيل</button></form>
    <div style="margin-top:14px">{rows}</div></div>""", title="الدفع")

@app.route("/support/payments/<int:pid>/toggle")
@support_required
def admin_payment_toggle(pid):
    p = db.session.get(PaymentInfo, pid)
    if p: p.is_active = not p.is_active; db.session.commit()
    return redirect(url_for("admin_payments"))

@app.route("/support/payments/<int:pid>/delete")
@support_required
def admin_payment_delete(pid):
    p = db.session.get(PaymentInfo, pid)
    if p: db.session.delete(p); db.session.commit()
    flash("تم الحذف.","success")
    return redirect(url_for("admin_payments"))

# ==================== MAIN ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_ENV") != "production"
    if socketio:
        socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=port, debug=debug)
