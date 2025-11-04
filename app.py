# -*- coding: utf-8 -*-
# =========================
# Import Libraries
# =========================
import os
import uuid
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from pony.orm import Database, Required, Optional, PrimaryKey, Set, db_session, select
from PIL import Image
import bcrypt
from itsdangerous import URLSafeTimedSerializer
import logging
import smtplib
from werkzeug.exceptions import RequestEntityTooLarge

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# Konfigurasi Aplikasi & Constants
# =========================

app = Flask(__name__)

# ---- HARDCODED (gunakan nilai dummy/placeholder yang aman) ----
app.secret_key = "CHANGE_THIS_TO_A_SECURE_RANDOM_SECRET"
GEMINI_API_KEY = "AIzaSyBlv6T1_IzO7rTXQKkQ1Y5vpGU08ZFZvyA"
LUNO_API_KEY_ID="jnm42w8w23t8v"
LUNO_API_KEY_SECRET="QSRtcDAysoiAs3IiRrDtqaXeO35SPzFMXU0niYUHNnc"

# DEV flag: tampilkan detail error ke client (hanya untuk debugging lokal)
SHOW_DETAILED_ERRORS = True

# Konfigurasi Upload
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Harga Paket & Reward
PREMIUM_PRICE = 150000.0
REWARD_RUMAH_SAKIT = 100000.0
REWARD_DATA_AI = 200000.0

# Konfigurasi Email (gunakan App Password bila pakai Gmail)
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USERNAME='anandatechnologysolution@gmail.com',
    MAIL_PASSWORD='@Viti412',
    MAIL_SENDER='anandatechnologysolution@gmail.com',
)
s = URLSafeTimedSerializer(app.secret_key)

# =========================
# Utilitas & Helper Functions
# =========================

def send_email(subject, recipients, body):
    try:
        if not (app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD'] and app.config['MAIL_SENDER']):
            logger.warning("Email config kosong; lewati pengiriman email.")
            return False
        message = f"Subject: {subject}\nTo: {', '.join(recipients)}\nFrom: {app.config['MAIL_SENDER']}\n\n{body}"
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.sendmail(app.config['MAIL_SENDER'], recipients, message)
        logger.info(f"Email sent to {recipients}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

def hash_password(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def jsonify_error(message: str, status_code: int = 400):
    return jsonify({"success": False, "error": message}), status_code

def _extract_luno_address(resp):
    try:
        if not isinstance(resp, dict):
            return None
        for key in ("address", "receive_address", "deposit_address"):
            if key in resp and resp[key]:
                return resp[key]
        if "funding_address" in resp and isinstance(resp["funding_address"], dict):
            addr = resp["funding_address"].get("address")
            if addr:
                return addr
        for list_key in ("addresses", "funding_addresses"):
            if list_key in resp and isinstance(resp[list_key], (list, tuple)) and resp[list_key]:
                first = resp[list_key][0]
                if isinstance(first, dict):
                    for key in ("address", "receive_address", "deposit_address"):
                        if key in first and first[key]:
                            return first[key]
        return None
    except Exception:
        return None

def redirect_flash(message: str, category: str, anchor: str = None):
    flash(message, category)
    return redirect(url_for('home') + f"#{anchor}" if anchor else url_for('home'))

def login_required(f):
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

def _get_file_size(fs):
    for attr in ("stream",):
        s = getattr(fs, attr, None)
        if s and hasattr(s, "seek") and hasattr(s, "tell"):
            try:
                pos = s.tell()
                s.seek(0, os.SEEK_END)
                size = s.tell()
                s.seek(pos)
                return size
            except Exception:
                pass
    try:
        pos = fs.tell()
        fs.seek(0, os.SEEK_END)
        size = fs.tell()
        fs.seek(pos)
        return size
    except Exception:
        return None

def validate_image_file(file):
    if not file or not getattr(file, "filename", ""):
        return False, "Tidak ada file yang dipilih"

    filename = file.filename.lower().strip()
    allowed_ext = ('.jpg', '.jpeg', '.png')
    if not any(filename.endswith(ext) for ext in allowed_ext):
        return False, "Tipe file tidak valid. Hanya .jpg, .jpeg, .png"

    size = _get_file_size(file)
    if size is None:
        return False, "Gagal membaca ukuran file"
    if size > app.config['MAX_CONTENT_LENGTH']:
        return False, f"Ukuran file terlalu besar. Maksimal {app.config['MAX_CONTENT_LENGTH'] // (1024*1024)}MB"

    try:
        file.stream.seek(0)
        img = Image.open(file.stream)
        img.verify()
        file.stream.seek(0)
        return True, "File valid"
    except Exception:
        return False, "File bukan gambar yang valid"

def get_user_upload_count(user, today_date):
    return select(
        ex for ex in user.exchanges 
        if ex.Tujuan == 'deteksi' and ex.Tanggal.date() == today_date
    ).count()

def is_premium_user(user):
    return user.PaketAktif

# =========================
# Database Setup & Models
# =========================

db = Database()

try:
    import pymysql
    db.bind(
        provider='mysql',
        host="localhost",
        user="root",
        passwd="",
        db="kusehatv1",
        charset="utf8mb4"
    )
    logger.info("Database MySQL connected successfully via PyMySQL (no ENV)")
except Exception as e:
    logger.error(f"Database connection error (MySQL): {str(e)}")
    db.bind(provider='sqlite', filename='database.sqlite', create_db=True)

class User(db.Entity):
    UserID = PrimaryKey(int, auto=True)
    NamaUser = Required(str)
    Email = Required(str, unique=True)
    Password = Required(str)
    Register_Date = Optional(datetime)
    Login_Date = Optional(datetime)
    PaketAktif = Required(bool, default=False)
    Saldo = Required(float, default=0.0)
    reset_token = Optional(str)
    reset_token_expiration = Optional(datetime)
    exchanges = Set('Exchange')
    topups = Set('TopUp')

class Exchange(db.Entity):
    ExchangeID = PrimaryKey(int, auto=True)
    User = Required(User)
    Tujuan = Required(str)              # 'deteksi' | 'dokter' | 'data_ai'
    Gambar = Optional(str)
    Diagnosa = Optional(str)
    Tanggal = Required(datetime)
    SaldoReward = Required(float, default=0.0)

class TopUp(db.Entity):
    TopUpID = PrimaryKey(int, auto=True)
    User = Required(User)
    Jumlah = Required(float)
    Metode = Required(str)              # e.g., 'BTC', 'ETH', 'BANK'
    Tanggal = Required(datetime)

db.generate_mapping(create_tables=True)

# =========================
# AI Model & Analysis Functions (stub-safe)
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
        with open(labels_path, "r", encoding="utf-8") as f:
            _class_names = [line.strip() for line in f]
        model, class_names = _model, _class_names
        logger.info("Model AI berhasil dimuat.")
    except Exception as e:
        logger.warning(f"Lewati load model AI (optional): {e}")

def detect_disease(image_path: str):
    load_ai_model()
    if model is None:
        return {"class_name": "Model tidak tersedia", "confidence": 0.0}
    try:
        image = Image.open(image_path).convert("RGB").resize((224, 224))
        image_array = (np.asarray(image, dtype=np.float32).reshape(1, 224, 224, 3) / 127.5) - 1
        prediction = model.predict(image_array)
        import numpy as _np
        index = int(_np.argmax(prediction))
        confidence = float(prediction[0][index])
        cname = class_names[index].strip() if 0 <= index < len(class_names) else f"Class_{index}"
        return {"class_name": cname, "confidence": confidence}
    except Exception as e:
        logger.error(f"Error saat mendeteksi penyakit: {e}")
        return {"class_name": "Error processing image", "confidence": 0.0}

# =========================
# Routes / Endpoints
# =========================

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
        User(
            NamaUser=form_data['nama'],
            Email=form_data['email'],
            Password=hash_password(form_data['password']), 
            Register_Date=datetime.now()
        )
        return redirect_flash("Registrasi berhasil, silakan login.", "success", "login-section")
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
            email_body = f"Halo {user.NamaUser},\n\nKlik tautan berikut untuk reset password (berlaku 1 jam):\n{reset_url}\n\nJika bukan Anda, abaikan email ini."
            send_email("Reset Password - KuSehat", [user.Email], email_body)
        return redirect_flash("Jika email Anda terdaftar, instruksi reset password telah dikirim.", "success", "login-section")
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        return redirect_flash("Terjadi kesalahan saat memproses reset password.", "error", "login-section")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
@db_session
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        return redirect_flash("Tautan reset tidak valid atau kadaluarsa.", "error", "login-section")
    user = User.get(Email=email)
    if not user or user.reset_token != token or (user.reset_token_expiration and user.reset_token_expiration < datetime.now()):
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
            send_email("Password Berhasil Direset - KuSehat", [user.Email], "Password akun Anda telah berhasil direset.")
            return redirect_flash("Password berhasil direset. Silakan login.", "success", "login-section")
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            return redirect_flash("Terjadi kesalahan saat mereset password.", "error")
    return render_template("reset_password.html", token=token)

# --- Tukar Gambar + Analisis ---
@app.route("/exchange", methods=["POST"])
@login_required
@db_session
def exchange(user):
    try:
        file = request.files.get("image")
        if file is None:
            return jsonify_error("Input file 'image' tidak ditemukan di form.")
        is_valid, message = validate_image_file(file)
        if not is_valid:
            return jsonify_error(message)

        tujuan = request.form.get("tujuan", "").strip().lower()
        if tujuan in ("dokter", "rumah_sakit"):
            reward = REWARD_RUMAH_SAKIT
            tujuan_text = "dokter"
            tujuan_display = "Data Medis Rumah Sakit"
        elif tujuan == "data_ai":
            reward = REWARD_DATA_AI
            tujuan_text = "data_ai"
            tujuan_display = "Data Pelatihan AI"
        else:
            return jsonify_error("Tujuan penukaran tidak valid.")

        original_name = secure_filename(file.filename)
        filename = f"{uuid.uuid4().hex}_{original_name}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(image_path)

        analysis = detect_disease(image_path)

        Exchange(
            User=user,
            Tujuan=tujuan_text,
            Gambar=filename,
            Diagnosa=analysis.get("class_name") or "Upload ke exchange",
            Tanggal=datetime.now(),
            SaldoReward=reward
        )
        user.Saldo += reward

        return jsonify({
            "success": True,
            "message": f"Gambar ditukar! Saldo +IDR {reward:,.2f}",
            "new_balance": user.Saldo,
            "image_path": url_for('static', filename=f'uploads/{filename}', _external=True),
            "tujuan_display": tujuan_display,
            "reward_amount": reward,
            "analysis": {
                "class_name": analysis.get("class_name", "N/A"),
                "confidence": analysis.get("confidence", 0.0)
            }
        })
    except Exception as e:
        logger.exception("Exchange error")
        msg = f"Gagal memproses permintaan: {e.__class__.__name__}: {e}" if SHOW_DETAILED_ERRORS else "Gagal memproses permintaan."
        return jsonify_error(msg, 500)

# --- Endpoint optional untuk tombol "Mulai Analisis" ---
@app.route("/analyze-image", methods=["POST"])
@login_required
def analyze_image():
    try:
        file = request.files.get("image")
        existing_path = request.form.get("image_path", "").strip()

        if file:
            is_valid, message = validate_image_file(file)
            if not is_valid:
                return jsonify_error(message)
            original_name = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_name}"
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(image_path)
        elif existing_path:
            if existing_path.startswith("http"):
                basename = existing_path.split("/")[-1]
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], basename)
            else:
                basename = os.path.basename(existing_path)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], basename)
            if not os.path.isfile(image_path):
                return jsonify_error("Gambar tidak ditemukan di server.")
        else:
            return jsonify_error("Mohon unggah gambar atau sertakan image_path.")

        analysis = detect_disease(image_path)
        return jsonify({
            "success": True,
            "image_path": url_for('static', filename=f'uploads/{os.path.basename(image_path)}', _external=True),
            "analysis": analysis
        })
    except Exception as e:
        logger.exception("Analyze error")
        msg = f"Gagal menganalisis gambar: {e.__class__.__name__}: {e}" if SHOW_DETAILED_ERRORS else "Gagal menganalisis gambar."
        return jsonify_error(msg, 500)

@app.route("/activate_premium", methods=["POST"])
@login_required
@db_session
def activate_premium(user):
    try:
        if user.PaketAktif:
            return jsonify_error("Paket sudah aktif", 400)

        if user.Saldo < PREMIUM_PRICE:
            return jsonify_error(f"Saldo tidak mencukupi. Dibutuhkan Rp {PREMIUM_PRICE:,.0f}", 400)

        user.Saldo -= PREMIUM_PRICE
        user.PaketAktif = True

        return jsonify({
            "success": True,
            "message": "Paket Premium berhasil diaktifkan",
            "new_balance": user.Saldo,
            "premium_active": True
        })
    except Exception as e:
        logger.error(f"Activate premium error: {str(e)}")
        msg = f"Terjadi kesalahan saat mengaktifkan paket premium: {e.__class__.__name__}: {e}" if SHOW_DETAILED_ERRORS else "Terjadi kesalahan saat mengaktifkan paket premium."
        return jsonify_error(msg, 500)

@app.route("/topup", methods=["POST"])
@login_required
@db_session
def topup(user):
    try:
        jumlah_str = request.form.get("jumlah", "").strip()
        metode = request.form.get("metode", "").strip().lower()

        if not jumlah_str or not metode:
            return jsonify_error("Jumlah dan metode harus diisi.")

        try:
            jumlah = float(jumlah_str)
            if jumlah <= 0:
                return jsonify_error("Jumlah harus lebih dari 0.")
        except ValueError:
            return jsonify_error("Jumlah tidak valid.")

        allowed = {"btc", "eth", "bank"}
        if metode not in allowed:
            return jsonify_error("Metode tidak dikenal. Pilih: btc, eth, atau bank.")

        address = None
        mode = "manual"
        reference_code = None
        instructions = None

        if metode in {"btc", "eth"}:
            asset = "XBT" if metode == "btc" else "ETH"
            try:
                from luno_python.client import Client
                if not (LUNO_API_KEY_ID and LUNO_API_KEY_SECRET):
                    raise RuntimeError("Luno credential kosong")
                client = Client(api_key_id=LUNO_API_KEY_ID, api_key_secret=LUNO_API_KEY_SECRET)

                try:
                    resp = client.get_funding_address(asset=asset)
                    payload = resp if isinstance(resp, dict) else getattr(resp, "__dict__", {})
                    address = _extract_luno_address(payload)
                except Exception as e:
                    logger.warning(f"Luno get_funding_address error: {e}")

                if not address:
                    try:
                        resp = client.create_funding_address(asset=asset)
                        payload = resp if isinstance(resp, dict) else getattr(resp, "__dict__", {})
                        address = _extract_luno_address(payload)
                    except Exception as e:
                        logger.warning(f"Luno create_funding_address error: {e}")

                if address:
                    mode = "wallet"
                else:
                    import uuid as _uuid
                    reference_code = f"TOPUP-{asset}-{_uuid.uuid4().hex[:10].upper()}"
                    instructions = "Alamat wallet tidak tersedia dari Luno. Gunakan Kode Referensi ini dan hubungi admin untuk konfirmasi deposit."
                    mode = "manual"

            except ImportError:
                logger.warning("luno_python tidak terinstal; beralih ke mode manual")
                import uuid as _uuid
                reference_code = f"TOPUP-{asset}-{_uuid.uuid4().hex[:10].upper()}"
                instructions = "Library Luno tidak tersedia. Gunakan Kode Referensi ini dan hubungi admin untuk konfirmasi deposit."
                mode = "manual"
            except Exception as e:
                logger.error(f"Luno API error (umum): {str(e)}")
                import uuid as _uuid
                reference_code = f"TOPUP-{asset}-{_uuid.uuid4().hex[:10].upper()}"
                instructions = "Terjadi masalah saat menghubungi Luno. Gunakan Kode Referensi ini dan hubungi admin."
                mode = "manual"

        elif metode == "bank":
            import uuid as _uuid
            reference_code = f"TOPUP-BANK-{_uuid.uuid4().hex[:10].upper()}"
            instructions = "Silakan transfer ke rekening perusahaan dan cantumkan Kode Referensi pada berita/notes transfer."

        TopUp(User=user, Jumlah=jumlah, Metode=metode.upper(), Tanggal=datetime.now())

        return jsonify({
            "success": True,
            "message": "Permintaan Top Up dibuat.",
            "mode": mode,
            "address": address,
            "reference_code": reference_code,
            "instructions": instructions
        })
    except Exception as e:
        logger.error(f"Topup error: {str(e)}")
        msg = f"Gagal membuat alamat deposit: {e.__class__.__name__}: {e}" if SHOW_DETAILED_ERRORS else "Gagal membuat alamat deposit. Silakan coba lagi atau pilih metode lain."
        return jsonify_error(msg, 500)

# =========================
# Error Handlers
# =========================

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify_error("File terlalu besar. Maksimal 10MB."), 413

@app.errorhandler(Exception)
def handle_general_error(e):
    wants_json = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    if wants_json:
        logger.exception("Unhandled error")
        msg = f"Kesalahan tak terduga di server: {e.__class__.__name__}: {e}" if SHOW_DETAILED_ERRORS else "Kesalahan tak terduga di server."
        return jsonify_error(msg), 500
    raise e

# =========================
# App Runner (optional for local)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
