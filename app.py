# =========================
# Import Libraries
# =========================
import os
import uuid
import numpy as np
import requests
from datetime import datetime, timedelta, date
from functools import wraps
import sys

from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from pony.orm import Database, Required, Optional, PrimaryKey, Set, db_session, select
from PIL import Image
import bcrypt
from itsdangerous import URLSafeTimedSerializer
import logging
from flask_mail import Mail, Message

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# Konfigurasi Aplikasi & Constants
# =========================

app = Flask(__name__)

# HARDCODED CONFIGURATION - PINDAHIN KE ENVIRONMENT VARIABLES KALO MAU
app.secret_key = "@Viti412"
GEMINI_API_KEY = "AIzaSyBlv6T1_IzO7rTXQKkQ1Y5vpGU08ZFZvyA"
LUNO_API_KEY_ID = "jnm42w8w23t8v"
LUNO_API_KEY_SECRET = "QSRtcDAysoiAs3IiRrDtqaXeO35SPzFMXU0niYUHNnc"

# Konfigurasi Upload
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Harga Paket & Reward
PREMIUM_PRICE = 150000.0
REWARD_RUMAH_SAKIT = 100000.0
REWARD_DATA_AI = 200000.0

# Konfigurasi Email untuk Flask-Mail
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USERNAME='anandatechnologysolution@gmail.com',
    MAIL_PASSWORD='kqdv naan znzx encd',        # <-- GANTI INI DENGAN APP PASSWORD YANG BENAR
    MAIL_DEFAULT_SENDER='anandatechnologysolution@gmail.com',
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
)

# Inisialisasi Flask-Mail
mail = Mail(app)
s = URLSafeTimedSerializer(app.secret_key)

# =========================
# Utilitas & Helper Functions
# =========================

def send_email(subject, recipients, body):
    """Mengirim email menggunakan Flask-Mail."""
    try:
        msg = Message(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
        logger.info(f"Email sent to {recipients}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

def hash_password(password: str):
    """Hash password menggunakan bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_password: str, hashed_password: str):
    """Verifikasi password dengan hash bcrypt."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def jsonify_error(message: str, status_code: int = 400):
    """Mengembalikan respons error JSON."""
    return jsonify({"success": False, "error": message}), status_code

def redirect_flash(message: str, category: str, anchor: str = None):
    """Flash message dan redirect ke anchor tertentu."""
    flash(message, category)
    return redirect(url_for('home') + f"#{anchor}" if anchor else url_for('home'))

def login_required(f):
    """Decorator untuk mengecek sesi login dan menambahkan objek user ke kwargs."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify_error("Unauthorized. Please log in.", 401)
            return redirect_flash("Anda harus login terlebih dahulu.", "error", "login-section")

        with db_session:
            try:
                user = User.get(UserID=session["user_id"])
                if not user:
                    session.clear()
                    return redirect_flash("Sesi tidak valid, silakan login lagi.", "error", "login-section")

                kwargs['user'] = user
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in login_required decorator: {str(e)}")
                session.clear()
                return redirect_flash("Terjadi kesalahan server. Silakan login kembali.", "error", "login-section")
    return decorated_function

def validate_image_file(file):
    """Validasi file gambar yang diunggah."""
    if not file or not file.filename:
        return False, "Tidak ada file yang dipilih"
    if not file.filename.lower().endswith(('.jpg', '.jpeg', '.png')):
        return False, "Tipe file tidak valid. Hanya .jpg, .jpeg, .png"
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > 10 * 1024 * 1024:
        return False, "Ukuran file terlalu besar. Maksimal 10MB"
    try:
        img = Image.open(file)
        img.verify()
        file.seek(0)
        return True, "File valid"
    except Exception:
        return False, "File bukan gambar yang valid"

def get_user_upload_count(user, today_date):
    """Menghitung jumlah upload user untuk deteksi pada hari ini."""
    return select(
        ex for ex in user.exchanges
        if ex.Tujuan == 'deteksi' and ex.Tanggal.date() == today_date
    ).count()

def is_premium_user(user):
    """Memeriksa apakah user memiliki akses premium."""
    return user.PaketAktif

# =========================
# Database Setup & Models
# =========================

db = Database()

# --- HANYA POSTGRES, TANPA FALLBACK ---
try:
    db.bind(
        provider='postgres',
        database='kusehatdb',
        host='ep-silent-cell-a13xb1pn-pooler.ap-southeast-1.aws.neon.tech',
        user='neondb_owner',
        password='npg_UhDrtBkwO12T',
        port=5432,
        sslmode='require'
    )
    logger.info("Database connected successfully to PostgreSQL")
except Exception as e:
    logger.error(f"Database connection error: {str(e)}")
    print("\n!!! GAGAL KONEKSI KE DATABASE POSTGRES !!!")
    print(f"Error: {str(e)}")
    print("Aplikasi akan berhenti. Silakan periksa konfigurasi database Anda.")
    sys.exit(1) # HENTI APLIKASI JIKA GAGAL KONEKSI

class User(db.Entity):
    _table_ = "user"
    UserID = PrimaryKey(int, auto=True)
    NamaUser = Required(str)
    Email = Required(str, unique=True)
    Password = Required(str)
    Register_Date = Required(datetime)
    Login_Date = Optional(datetime)
    Saldo = Required(float, default=0.0)
    PaketAktif = Required(bool, default=False)
    reset_token = Optional(str)
    reset_token_expiration = Optional(datetime)
    
    is_verified = Required(bool, default=False)
    email_verification_token = Optional(str)
    email_verification_token_expiration = Optional(datetime)
    
    topups = Set("TopUp")
    exchanges = Set("Exchange")

class TopUp(db.Entity):
    _table_ = "topup"
    ID = PrimaryKey(int, auto=True)
    User = Required(User)
    Jumlah = Required(float)
    Metode = Required(str)
    Tanggal = Required(datetime)

class Exchange(db.Entity):
    _table_ = "exchange"
    ID = PrimaryKey(int, auto=True)
    User = Required(User)
    Tujuan = Required(str)
    Gambar = Required(str)
    Diagnosa = Required(str)
    Tanggal = Required(datetime)
    SaldoReward = Required(float)

db.generate_mapping(create_tables=True)

# =========================
# AI Model & Analysis Functions
# =========================

model = None
class_names = []

def load_ai_model():
    global model, class_names
    if model is not None:
        return
    try:
        from keras.models import load_model
        model_path, labels_path = "model/keras_model.h5", "model/labels.txt"
        if not (os.path.isfile(model_path) and os.path.isfile(labels_path)):
            logger.warning("Model files tidak ditemukan")
            return
        _model = load_model(model_path, compile=False)
        with open(labels_path, "r") as f:
            _class_names = [line.strip() for line in f]
        model, class_names = _model, _class_names
        logger.info("Model AI berhasil dimuat.")
    except Exception as e:
        logger.error(f"Gagal load model AI: {e}")

def detect_disease(image_path: str):
    load_ai_model()
    if model is None:
        return {"class_name": "Model tidak tersedia", "confidence": 0.0}
    try:
        image = Image.open(image_path).convert("RGB").resize((224, 224))
        image_array = (np.asarray(image, dtype=np.float32).reshape(1, 224, 224, 3) / 127.5) - 1
        prediction = model.predict(image_array)
        index = int(np.argmax(prediction))
        confidence = float(prediction[0][index])
        return {"class_name": class_names[index].strip(), "confidence": confidence}
    except Exception as e:
        logger.error(f"Error saat mendeteksi penyakit: {e}")
        return {"class_name": "Error processing image", "confidence": 0.0}

def analyze_with_gemini(disease_name: str, confidence: float):
    if not GEMINI_API_KEY:
        return "GEMINI_API_KEY belum diatur."
    disease_name = disease_name.replace('"', '').replace("'", "").replace(";", "").replace(":", "").replace("\\", "")
    prompt = (
        f"Terdeteksi penyakit: {disease_name} ({confidence:.2%}). "
        "Berikan analisis medis: 1. Deskripsi 2. Obat/tindakan 3. Cara penyembuhan 4. Kapan ke dokter."
    )
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            headers={"Content-Type": "application/json"}
        )
        if response.ok:
            data = response.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                content = data["candidates"][0].get("content", {})
                if "parts" in content and len(content["parts"]) > 0:
                    return content["parts"][0].get("text", "Tidak ada hasil.")
            return "Format respons tidak valid dari Gemini"
        return f"Error Gemini: {response.text}"
    except Exception as e:
        logger.error(f"Gagal akses Gemini: {str(e)}")
        return f"Gagal akses Gemini: {str(e)}"

# =========================
# Routes / Endpoints
# =========================

@app.route("/health")
def health():
    """Healthcheck sederhana agar mudah mengecek 200 OK tanpa template/db."""
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"}), 200

@app.route("/")
@db_session
def home():
    if "user_id" in session:
        user = User.get(UserID=session["user_id"])
        if not user:
            session.clear()
            return render_template("auth.html")
        today_date = date.today()
        upload_count_today = get_user_upload_count(user, today_date)
        return render_template("main.html", user=user, upload_count_today=upload_count_today)
    return render_template("auth.html")
    
    

# ==== Tambahan: robots.txt ====
@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /static/",
        "Disallow: /upload",
        "Disallow: /analyze",
        "Disallow: /exchange",
        "Disallow: /topup",
        "Disallow: /activate_premium",
        f"Sitemap: {SITE_BASE_URL}/sitemap.xml",
        ""
    ]
    resp = make_response("\n".join(lines))
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    return resp

# ==== Tambahan: sitemap.xml ====
@app.route("/sitemap.xml")
def sitemap_xml():
    try:
        urls = []
        paths = discover_public_paths(app)
        lastmod = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        for path in paths:
            loc = f"{SITE_BASE_URL}{path if path.startswith('/') else '/' + path}"
            if path == "/":
                changefreq = "daily"
                priority = "1.0"
            else:
                changefreq = "weekly"
                priority = "0.7"
            urls.append(
                f"  <url>\n"
                f"    <loc>{loc}</loc>\n"
                f"    <lastmod>{lastmod}</lastmod>\n"
                f"    <changefreq>{changefreq}</changefreq>\n"
                f"    <priority>{priority}</priority>\n"
                f"  </url>"
            )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) +
            "\n</urlset>"
        )
        resp = make_response(xml)
        resp.headers["Content-Type"] = "application/xml; charset=utf-8"
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    except Exception:
        logger.exception("Error generate sitemap")
        return jsonify_error("Gagal membuat sitemap.", 500)


@app.route("/login", methods=["POST"])
@db_session
def login():
    try:
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            return redirect_flash("Email dan password harus diisi.", "error", "login-section")
        user = User.get(Email=email)
        if user and check_password(password, user.Password):
            if not user.is_verified:
                return redirect_flash("Silakan verifikasi email Anda terlebih dahulu. Periksa inbox atau folder spam.", "error", "login-section")
            session["user_id"] = user.UserID
            user.Login_Date = datetime.now()
            return redirect_flash("Login berhasil!", "success")
        return redirect_flash("Email atau Password salah.", "error", "login-section")
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return redirect_flash("Terjadi kesalahan saat login.", "error", "login-section")

@app.route("/register", methods=["POST"])
@db_session
def register():
    try:
        form_data = {k: v.strip() for k, v in request.form.items() if v}
        if not all(k in form_data for k in ("nama", "email", "password")):
            return redirect_flash("Semua field harus diisi.", "error", "register-section")
        if User.exists(Email=form_data['email']):
            return redirect_flash("Email sudah terdaftar.", "error", "register-section")
        if len(form_data['password']) < 6:
            return redirect_flash("Password minimal 6 karakter.", "error", "register-section")

        new_user = User(
            NamaUser=form_data['nama'],
            Email=form_data['email'],
            Password=hash_password(form_data['password']),
            Register_Date=datetime.now()
        )

        token = s.dumps(new_user.Email, salt='email-confirmation-salt')
        new_user.email_verification_token = token
        new_user.email_verification_token_expiration = datetime.now() + timedelta(hours=1)
        verify_url = url_for('verify_email', token=token, _external=True)

        email_body = f"""Halo {new_user.NamaUser},
        
Terima kasih telah mendaftar di KuSehat. Klik tautan berikut untuk memverifikasi alamat email Anda:
{verify_url}

Tautan ini akan kadaluarsa dalam 1 jam.
Terima kasih,
Tim KuSehat
        """
        send_email("Verifikasi Email - KuSehat", [new_user.Email], email_body)

        return redirect_flash("Registrasi berhasil! Silakan periksa email Anda untuk verifikasi sebelum login.", "success", "login-section")
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return redirect_flash("Terjadi kesalahan saat registrasi.", "error", "register-section")

@app.route("/logout")
def logout():
    session.clear()
    return redirect_flash("Anda telah logout.", "success")

@app.route("/forgot-password", methods=["POST"])
@db_session
def forgot_password():
    try:
        email = request.form.get("email", "").strip()
        if not email:
            return redirect_flash("Email harus diisi.", "error", "login-section")
        user = User.get(Email=email)
        if user:
            token = s.dumps(user.Email, salt='password-reset-salt')
            user.reset_token = token
            user.reset_token_expiration = datetime.now() + timedelta(hours=1)
            reset_url = url_for('reset_password', token=token, _external=True)
            email_body = f"""Halo {user.NamaUser},
            Kami menerima permintaan untuk mereset password akun Anda. Klik tautan berikut untuk membuat password baru:
            {reset_url}
            Tautan ini akan kadaluarsa dalam 1 jam untuk keamanan akun Anda.
            Jika Anda tidak meminta reset password, abaikan email ini.
            Terima kasih,
            Tim KuSehat
            """
            send_email("Reset Password - KuSehat", [user.Email], email_body)
        return redirect_flash("Jika email Anda terdaftar, instruksi reset password telah dikirim.", "success", "login-section")
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        return redirect_flash("Terjadi kesalahan saat memproses permintaan reset password.", "error", "login-section")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
@db_session
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        return redirect_flash("Tautan reset tidak valid atau kadaluarsa.", "error", "login-section")
    user = User.get(Email=email)
    if not user or user.reset_token != token or user.reset_token_expiration < datetime.now():
        return redirect_flash("Tautan reset tidak valid atau kadaluarsa.", "error", "login-section")
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not password or not confirm:
            return redirect_flash("Password tidak boleh kosong.", "error")
        if password != confirm:
            return redirect_flash("Password tidak cocok.", "error")
        if len(password) < 6:
            return redirect_flash("Password minimal 6 karakter.", "error")
        try:
            user.Password = hash_password(password)
            user.reset_token = ""
            user.reset_token_expiration = datetime.now() - timedelta(days=1)
            email_body = f"""Halo {user.NamaUser},
            Password akun Anda telah berhasil direset.
            Anda sekarang dapat login dengan password baru Anda.
            Jika Anda tidak mereset password, segera hubungi kami.
            Terima kasih,
            Tim KuSehat
            """
            send_email("Password Berhasil Direset - KuSehat", [user.Email], email_body)
            return redirect_flash("Password berhasil direset. Silakan login.", "success", "login-section")
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            return redirect_flash("Terjadi kesalahan saat mereset password.", "error")
    return render_template("reset_password.html", token=token)

@app.route("/verify_email/<token>")
@db_session
def verify_email(token):
    try:
        email = s.loads(token, salt='email-confirmation-salt', max_age=3600)
    except:
        return render_template("verify_email.html", success=False)
    
    user = User.get(Email=email)
    if user and user.email_verification_token == token and user.email_verification_token_expiration > datetime.now():
        user.is_verified = True
        user.email_verification_token = ""
        user.email_verification_token_expiration = None
        return render_template("verify_email.html", success=True)
    else:
        return render_template("verify_email.html", success=False)

# --- ROUTE PROFIL DAN UPDATE DIHAPUS/DIUBAH ---
# --- DIHAPUS: Route /profile dan /update_profile tidak lagi diperlukan ---

@app.route("/upload", methods=["POST"])
@db_session
@login_required
def upload_analyze(user):
    method = request.form.get("method", "")
    if method != "upload":
        return redirect(url_for('home'))
    file = request.files.get('image')
    is_valid, message = validate_image_file(file)
    if not is_valid:
        flash(message, "error")
        return redirect(url_for('home'))
    today_date = date.today()
    upload_count_today = get_user_upload_count(user, today_date)
    if not is_premium_user(user):
        if upload_count_today >= 3:
            flash("Anda telah mencapai batas 3 analisis gratis hari ini. Silakan upgrade ke Premium untuk analisis tanpa batas.", "error")
            return redirect(url_for('home'))
    try:
        filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(image_path)
        result = detect_disease(image_path)
        diagnosis = (
            f"Penyakit: {result['class_name']} ({result['confidence']:.2%})\n\n"
            f"Analisis Gemini:\n{analyze_with_gemini(result['class_name'], result['confidence'])}"
        )
        Exchange(
            User=user,
            Tujuan='deteksi',
            Gambar=filename,
            Diagnosa=diagnosis,
            Tanggal=datetime.now(),
            SaldoReward=0.0
        )
        return render_template("main.html", user=user,
                               upload_count_today=upload_count_today + 1,
                               diagnosis=diagnosis, image_path=filename)
    except Exception as e:
        logger.error(f"Upload analyze error: {str(e)}")
        flash("Terjadi kesalahan saat memproses gambar.", "error")
        return redirect(url_for('home'))

# --- ROUTE UPDATE USER SUDAH ADA DAN DIGUNAKAN OLEH FORM PROFIL ---
@app.route("/update_user", methods=["POST"])
@db_session
@login_required
def update_user(user):
    try:
        old_password = request.form.get("old_password", "")
        # --- DIUBAH: Validasi password lama hanya jika password baru diisi ---
        new_pass = request.form.get("new_password", "")
        if new_pass and not old_password:
            return redirect_flash("Password lama harus diisi untuk mengubah password.", "error", "profile-section")
        if old_password and not check_password(old_password, user.Password):
            return redirect_flash("Password lama salah.", "error", "profile-section")
        
        email_baru = request.form.get("email", "").strip()
        if not email_baru:
            return redirect_flash("Email tidak boleh kosong.", "error", "profile-section")
        if User.exists(Email=email_baru) and User.get(Email=email_baru).UserID != user.UserID:
            return redirect_flash("Email sudah digunakan.", "error", "profile-section")
        
        user.NamaUser = request.form.get("nama", "").strip()
        user.Email = email_baru
        
        if new_pass:
            if len(new_pass) < 6:
                return redirect_flash("Password baru minimal 6 karakter.", "error", "profile-section")
            user.Password = hash_password(new_pass)
        
        # --- DIUBAH: Redirect ke halaman utama dengan anchor profile-section ---
        return redirect_flash("Profil berhasil diperbarui.", "success", "profile-section")
    except Exception as e:
        logger.error(f"Update user error: {str(e)}")
        return redirect_flash("Terjadi kesalahan saat memperbarui profil.", "error", "profile-section")

@app.route("/activate_premium", methods=["POST"])
@login_required
def activate_premium(user):
    try:
        if user.PaketAktif:
            return jsonify_error("Paket sudah aktif", 400)
        if user.Saldo < PREMIUM_PRICE:
            return jsonify_error(f"Saldo tidak mencukupi. Dibutuhkan Rp {PREMIUM_PRICE:,.0f}", 400)
        user.Saldo -= PREMIUM_PRICE
        user.PaketAktif = True
        return jsonify({"success": True, "message": "Paket Premium berhasil diaktifkan", "new_balance": user.Saldo})
    except Exception as e:
        logger.error(f"Activate premium error: {str(e)}")
        return jsonify_error("Terjadi kesalahan saat mengaktifkan paket premium.", 500)

@app.route("/analyze", methods=["POST"])
@login_required
def analyze(user):
    try:
        file = request.files.get('image')
        is_valid, message = validate_image_file(file)
        if not is_valid:
            return jsonify_error(message)
        today_date = date.today()
        upload_count_today = get_user_upload_count(user, today_date)
        if not is_premium_user(user) and upload_count_today >= 3:
            return jsonify_error("Anda telah mencapai batas 3 analisis gratis hari ini. Silakan upgrade ke Premium untuk analisis tanpa batas.", 403)
        filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(image_path)
        result = detect_disease(image_path)
        diagnosis = (
            f"Penyakit: {result['class_name']} ({result['confidence']:.2%})\n\n"
            f"Analisis Gemini:\n{analyze_with_gemini(result['class_name'], result['confidence'])}"
        )
        Exchange(
            User=user,
            Tujuan='deteksi',
            Gambar=filename,
            Diagnosa=diagnosis,
            Tanggal=datetime.now(),
            SaldoReward=0.0
        )
        return jsonify({
            "success": True,
            "diagnosis": diagnosis,
            "image_path": url_for('static', filename=f'uploads/{filename}'),
            "timestamp": datetime.now().strftime("%d %b %Y, %H:%M")
        })
    except Exception as e:
        logger.error(f"Analyze error: {str(e)}")
        return jsonify_error("Terjadi kesalahan saat menganalisis gambar.", 500)

@app.route("/topup", methods=["POST"])
@login_required
def topup(user):
    try:
        jumlah_str = request.form.get("jumlah", "").strip()
        metode = request.form.get("metode", "").strip()
        if not jumlah_str or not metode:
            return jsonify_error("Jumlah dan metode harus diisi.")
        try:
            jumlah = float(jumlah_str)
            if jumlah <= 0:
                return jsonify_error("Jumlah harus lebih dari 0.")
        except ValueError:
            return jsonify_error("Jumlah tidak valid.")
        try:
            from luno_python.client import Client
            asset = "XBT" if metode == "btc" else "ETH"
            client = Client(api_key_id=LUNO_API_KEY_ID, api_key_secret=LUNO_API_KEY_SECRET)
            funding_address = None
            try:
                funding_address = client.get_funding_address(asset=asset).get('address')
            except Exception:
                pass
            if not funding_address:
                try:
                    funding_address = client.create_funding_address(asset=asset).get('address')
                except Exception as e:
                    logger.error(f"Error creating funding address: {str(e)}")
            if not funding_address:
                raise Exception("Gagal membuat alamat funding di Luno. Silakan coba lagi atau hubungi admin.")
            TopUp(User=user, Jumlah=jumlah, Metode=metode.upper(), Tanggal=datetime.now())
            return jsonify({
                "success": True,
                "message": "Permintaan Top Up berhasil. Silakan kirim dana.",
                "address": funding_address
            })
        except ImportError:
            logger.error("Luno client not installed")
            return jsonify_error("Library Luno tidak terinstall. Hubungi administrator.")
        except Exception as e:
            logger.error(f"Topup error: {str(e)}")
            return jsonify_error(f"Terjadi kesalahan: {e}")
    except Exception as e:
        logger.error(f"Topup form error: {str(e)}")
        return jsonify_error("Terjadi kesalahan saat memproses topup.")

@app.route("/exchange", methods=["POST"])
@login_required
def exchange(user):
    try:
        file = request.files.get("image")
        is_valid, message = validate_image_file(file)
        if not is_valid:
            return jsonify_error(message)
        filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(image_path)
        tujuan = request.form.get("tujuan", "").strip()
        if tujuan == "dokter" or tujuan == "rumah_sakit":
            reward = REWARD_RUMAH_SAKIT
            tujuan_text = "dokter"
        elif tujuan == "data_ai":
            reward = REWARD_DATA_AI
            tujuan_text = "data_ai"
        else:
            return jsonify_error("Tujuan penukaran tidak valid.")
        Exchange(User=user, Tujuan=tujuan_text, Gambar=filename, Diagnosa="Upload ke exchange", Tanggal=datetime.now(), SaldoReward=reward)
        user.Saldo += reward
        return jsonify({
            "success": True,
            "message": f"Gambar ditukar! Saldo +IDR {reward:,.2f}",
            "new_balance": user.Saldo,
            "image_path": url_for('static', filename=f'uploads/{filename}'),
            "tujuan_display": "Data Medis Rumah Sakit" if tujuan_text == "dokter" else "Data Pelatihan AI",
            "reward_amount": reward
        })
    except Exception as e:
        logger.error(f"Exchange error: {str(e)}")
        return jsonify_error(f"Terjadi kesalahan saat menukar gambar: {str(e)}")

# =========================
# Error Handlers
# =========================

@app.errorhandler(413)
def too_large(e):
    return jsonify_error("File terlalu besar. Maksimal 10MB", 413)

@app.errorhandler(404)
def not_found(e):
    return redirect_flash("Halaman tidak ditemukan.", "error")

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {str(e)}")
    return redirect_flash("Terjadi kesalahan server. Silakan coba lagi.", "error")

# =========================
# Jalankan Aplikasi
# =========================
if __name__ == "__main__":
    load_ai_model()
    app.run(host='0.0.0.0', port=5000, debug=True)
