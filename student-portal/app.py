import os
import secrets
import base64
import binascii
from io import BytesIO
from datetime import datetime, timezone
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from flask import Flask, request, session, jsonify, render_template_string, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SCHOOL_NAME = "Alh. Lalo Kanteh Islamic Institute"
SETUP_KEY = os.environ.get("PORTAL_SETUP_KEY", "")
ADMIN_RESET_TOKEN = os.environ.get("ADMIN_PASSWORD_RESET_TOKEN", "")
ADMIN_EMAIL = "Lalokanteh1998@gmail.com".lower()
REGISTRATION_OPEN = os.environ.get("STUDENT_REGISTRATION_OPEN", "false").lower() == "true"
DEMO_MODE = os.environ.get("PORTAL_DEMO_MODE", "true").lower() == "true"

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_users (
                id BIGSERIAL PRIMARY KEY,
                full_name VARCHAR(120) NOT NULL,
                father_name VARCHAR(120) NOT NULL DEFAULT '',
                guardian_name VARCHAR(120) NOT NULL DEFAULT '',
                surname VARCHAR(120) NOT NULL DEFAULT '',
                arabic_name VARCHAR(200) NOT NULL DEFAULT '',
                phone VARCHAR(40) NOT NULL DEFAULT '',
                email VARCHAR(254) NOT NULL UNIQUE,
                student_id VARCHAR(40) UNIQUE,
                password_hash TEXT NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'student' CHECK (role IN ('student','staff','admin')),
                status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
                class_name VARCHAR(80) NOT NULL DEFAULT '',
                grade VARCHAR(80) NOT NULL DEFAULT '',
                date_of_birth DATE,
                profile_image TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                approved_at TIMESTAMPTZ
            )
        """)
        conn.execute("ALTER TABLE portal_users DROP CONSTRAINT IF EXISTS portal_users_role_check")
        conn.execute("ALTER TABLE portal_users ADD CONSTRAINT portal_users_role_check CHECK (role IN ('student','staff','admin'))")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS profile_image TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS father_name VARCHAR(120) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS guardian_name VARCHAR(120) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS surname VARCHAR(120) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS arabic_name VARCHAR(200) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS phone VARCHAR(40) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS grade VARCHAR(80) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS gender VARCHAR(20) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS nationality VARCHAR(100) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS date_of_birth DATE")
        conn.execute("CREATE INDEX IF NOT EXISTS portal_users_status_idx ON portal_users(status)")
        conn.execute("CREATE TABLE IF NOT EXISTS student_id_counters (admission_year INTEGER PRIMARY KEY, last_number INTEGER NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_password_reset_uses (token_hash TEXT PRIMARY KEY, used_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS student_activity (
            id BIGSERIAL PRIMARY KEY,
            student_user_id BIGINT NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
            actor_user_id BIGINT REFERENCES portal_users(id) ON DELETE SET NULL,
            activity_type VARCHAR(40) NOT NULL,
            description VARCHAR(240) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS student_activity_student_created_idx ON student_activity(student_user_id, created_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS student_report_cards (
            id BIGSERIAL PRIMARY KEY,
            student_user_id BIGINT NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
            title VARCHAR(160) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_data BYTEA NOT NULL,
            uploaded_by BIGINT REFERENCES portal_users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS student_report_cards_student_idx ON student_report_cards(student_user_id, created_at DESC)")
        conn.commit()

@app.before_request
def prepare():
    if not app.secret_key:
        return
    if request.endpoint == "health":
        return
    try:
        init_db()
    except Exception:
        app.logger.exception("Student portal database initialization failed")

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]

def verify_csrf():
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
        return False
    return True

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Please sign in."}), 401
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Please sign in."}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Administrator access required."}), 403
        return fn(*args, **kwargs)
    return wrapped

def generate_student_id(conn, admission_year=None):
    year = int(admission_year or datetime.now().year)
    row = conn.execute("INSERT INTO student_id_counters(admission_year,last_number) VALUES (%s,1) ON CONFLICT(admission_year) DO UPDATE SET last_number=student_id_counters.last_number+1 RETURNING last_number", (year,)).fetchone()
    return f"LKI-{year}-{row['last_number']:04d}"

def user_public(row):
    return {k: row.get(k) for k in ("id", "full_name", "father_name", "guardian_name", "surname", "arabic_name", "phone", "email", "student_id", "role", "status", "class_name", "grade", "date_of_birth", "profile_image", "gender", "nationality", "created_at")}

@app.get("/health")
def health():
    try:
        init_db()
        with db() as conn:
            conn.execute("SELECT 1")
        return jsonify({"status": "ok", "database": "connected", "schema": "ready"})
    except Exception:
        return jsonify({"status": "database_not_ready"}), 503

@app.get("/api/setup-status")
def setup_status():
    try:
        with db() as conn:
            exists = conn.execute("SELECT id FROM portal_users WHERE role='admin' LIMIT 1").fetchone()
        return jsonify({"setup_needed": not bool(exists), "database_ready": True})
    except Exception:
        app.logger.exception("Student portal setup-status database check failed")
        return jsonify({"setup_needed": False, "database_ready": False}), 503

@app.get("/api/csrf")
def csrf():
    if not app.secret_key:
        return jsonify({"error": "Portal security settings are incomplete."}), 503
    return jsonify({"csrf_token": csrf_token()})

@app.post("/api/setup-admin")
def setup_admin():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    if not SETUP_KEY or not secrets.compare_digest(str(request.json.get("setup_key", "")), SETUP_KEY):
        return jsonify({"error": "The setup key is not valid."}), 403
    data = request.json or {}
    requested_role = str(data.get("role", "student")).strip().lower()
    if requested_role not in ("student", "staff"):
        return jsonify({"error": "Choose Student or Staff."}), 400
    name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or "@" not in email or len(password) < 6:
        return jsonify({"error": "Enter a name, valid email, and password of at least 6 characters."}), 400
    with db() as conn:
        exists = conn.execute("SELECT id FROM portal_users WHERE role='admin' LIMIT 1").fetchone()
        if exists:
            return jsonify({"error": "An administrator has already been created."}), 409
        row = conn.execute(
            "INSERT INTO portal_users(full_name,email,password_hash,role,status) VALUES (%s,%s,%s,'admin','approved') RETURNING *",
            (name, email, generate_password_hash(password))
        ).fetchone()
        conn.commit()
    session.clear()
    session["user_id"], session["role"], session["full_name"] = row["id"], "admin", row["full_name"]
    session.permanent = True
    return jsonify({"user": user_public(row)}), 201

@app.route("/admin-password-reset/<token>", methods=["GET", "POST"])
def admin_password_reset(token):
    if not ADMIN_RESET_TOKEN or not secrets.compare_digest(token, ADMIN_RESET_TOKEN):
        return "This password reset link is invalid or expired.", 403
    if request.method == "GET":
        return """<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin password reset</title><body style="font-family:Arial;max-width:420px;margin:50px auto;padding:20px"><h2>Reset school administrator password</h2><form method="post"><label>New password (at least 10 characters)<input name="password" type="password" minlength="10" required style="display:block;width:100%;padding:12px;margin:10px 0"></label><label>Confirm new password<input name="confirm" type="password" minlength="10" required style="display:block;width:100%;padding:12px;margin:10px 0"></label><button style="padding:12px 18px">Set new password</button></form></body></html>"""
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if len(password) < 10 or password != confirm:
        return "Passwords must match and contain at least 10 characters.", 400
    token_hash = __import__("hashlib").sha256(token.encode("utf-8")).hexdigest()
    with db() as conn:
        try:
            conn.execute("INSERT INTO admin_password_reset_uses(token_hash) VALUES (%s)", (token_hash,))
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            return "This password reset link has already been used.", 410
        admin = conn.execute("SELECT id FROM portal_users WHERE role='admin' ORDER BY id ASC LIMIT 1").fetchone()
        if not admin:
            conn.rollback()
            return "The school administrator account was not found. Contact the portal administrator.", 404
        conn.execute("UPDATE portal_users SET password_hash=%s WHERE id=%s", (generate_password_hash(password), admin["id"]))
        conn.commit()
    return "Administrator password updated successfully. You can now sign in to the student portal."

register_heif_opener()

def normalize_profile_image(value):
    """Decode common raster formats and store a compact, normalized JPEG."""
    if not isinstance(value, str) or not value.startswith("data:image/") or ";base64," not in value:
        return None
    try:
        _, encoded = value.split(",", 1)
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > 5 * 1024 * 1024:
            return None
        with Image.open(BytesIO(raw)) as source:
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.load()
            if image.width < 1 or image.height < 1 or image.width * image.height > 40_000_000:
                return None
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((480, 480), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (ValueError, binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None


@app.post("/api/register")
def register():
    if DEMO_MODE or not REGISTRATION_OPEN:
        return jsonify({"error": "This is a demonstration portal. Student registration will open only after the school officially approves the website."}), 403
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    name = str(data.get("full_name", "")).strip()
    father_name = str(data.get("father_name", "")).strip()
    guardian_name = str(data.get("guardian_name", "")).strip()
    surname = str(data.get("surname", "")).strip()
    phone = str(data.get("phone", "")).strip()
    date_of_birth = str(data.get("date_of_birth", "")).strip()
    class_name = str(data.get("class_name", "")).strip()
    gender = str(data.get("gender", "")).strip()
    nationality = str(data.get("nationality", "")).strip()
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    profile_image = normalize_profile_image(data.get("profile_image", ""))
    if not profile_image:
        return jsonify({"error": "Choose a valid image file up to 5 MB. Supported formats include JPG, PNG, WebP, GIF, BMP, TIFF, HEIC, HEIF and AVIF."}), 400
    if not all([name, phone, nationality]) or (requested_role == "student" and not all([father_name, guardian_name, surname, date_of_birth, class_name, gender])):
        return jsonify({"error": "Complete your name, father's name, surname, date of birth, class, and phone number."}), 400
    if len(name) > 120 or len(father_name) > 120 or len(guardian_name) > 120 or len(surname) > 120 or len(phone) > 40 or len(class_name) > 80:
        return jsonify({"error": "One or more fields are too long."}), 400
    if password != password_confirm:
        return jsonify({"error": "Passwords do not match."}), 400
    if len(password) < 6:
        return jsonify({"error": "Use a password with at least 6 characters."}), 400
    dob = None
    if requested_role == "student":
        try:
            dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
            if dob >= datetime.now().date():
                return jsonify({"error": "Enter a valid date of birth."}), 400
        except ValueError:
            return jsonify({"error": "Enter a valid date of birth."}), 400
    email = requested_role + "-" + "".join(ch for ch in phone if ch.isdigit()) + "@accounts.lalokanteh.local"
    try:
        with db() as conn:
            duplicate = conn.execute("SELECT id FROM portal_users WHERE phone=%s AND role=%s LIMIT 1", (phone, requested_role)).fetchone()
            if duplicate:
                return jsonify({"error": "This phone number already has a student account. Contact the school."}), 409
            student_id = generate_student_id(conn) if requested_role == "student" else None
            row = conn.execute(
                "INSERT INTO portal_users(full_name,father_name,guardian_name,surname,phone,email,student_id,password_hash,role,status,class_name,date_of_birth,profile_image,gender,nationality) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s) RETURNING id",
                (name, father_name, guardian_name, surname, phone, email, student_id, generate_password_hash(password), requested_role, class_name if requested_role == "student" else "", dob, profile_image, gender if requested_role == "student" else "", nationality)
            ).fetchone()
            conn.commit()
        return jsonify({"message": "Registration submitted. The school must approve your account before you can sign in.", "id": row["id"]}), 201
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "That phone number is already registered. Contact the school if you need help."}), 409

@app.post("/api/login")
def login():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    requested_role = str(data.get("role", "")).strip().lower()
    if requested_role not in ("student", "staff", "admin"):
        return jsonify({"error": "Choose Student or Staff."}), 400
    login_value = str(data.get("login", data.get("email", ""))).strip()
    password = str(data.get("password", ""))
    with db() as conn:
        row = conn.execute("SELECT * FROM portal_users WHERE lower(email)=lower(%s) OR phone=%s ORDER BY CASE WHEN phone=%s THEN 0 ELSE 1 END LIMIT 1", (login_value, login_value, login_value)).fetchone()
    if not row or row["role"] != requested_role or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Phone number or password is incorrect."}), 401
    if row["status"] != "approved":
        return jsonify({"error": "Your account is " + row["status"] + ". Please contact the school if you need help."}), 403
    session.clear()
    session["user_id"], session["role"], session["full_name"] = row["id"], row["role"], row["full_name"]
    session.permanent = True
    csrf_token()
    if row["role"] == "student":
        with db() as conn:
            conn.execute(
                "INSERT INTO student_activity(student_user_id,actor_user_id,activity_type,description) VALUES (%s,%s,'sign_in','Student signed in')",
                (row["id"], row["id"])
            )
            conn.commit()
    return jsonify({"user": user_public(row), "csrf_token": session["_csrf"]})

@app.post("/api/logout")
def logout():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    session.clear()
    return jsonify({"message": "Signed out."})

@app.get("/api/me")
@login_required
def me():
    with db() as conn:
        row = conn.execute("SELECT * FROM portal_users WHERE id=%s", (session["user_id"],)).fetchone()
    if not row:
        session.clear()
        return jsonify({"error": "Account not found."}), 404
    return jsonify({"user": user_public(row)})

@app.get("/api/admin/students")
@admin_required
def admin_students():
    with db() as conn:
        rows = conn.execute("SELECT * FROM portal_users WHERE role='student' ORDER BY created_at DESC LIMIT 500").fetchall()
    return jsonify({"students": [user_public(row) for row in rows]})

@app.get("/api/admin/students/<int:user_id>/overview")
@admin_required
def admin_student_overview(user_id):
    with db() as conn:
        student = conn.execute("SELECT * FROM portal_users WHERE id=%s AND role='student'", (user_id,)).fetchone()
        if not student:
            return jsonify({"error": "Student account not found."}), 404
        activities = conn.execute("""
            SELECT a.activity_type, a.description, a.created_at,
                   COALESCE(actor.full_name, 'System') AS actor_name
            FROM student_activity a
            LEFT JOIN portal_users actor ON actor.id=a.actor_user_id
            WHERE a.student_user_id=%s
            ORDER BY a.created_at DESC LIMIT 300
        """, (user_id,)).fetchall()
    return jsonify({
        "student": user_public(student),
        "activities": [{
            "activity_type": a["activity_type"],
            "description": a["description"],
            "actor_name": a["actor_name"],
            "created_at": a["created_at"].isoformat() if a["created_at"] else None
        } for a in activities]
    })

@app.get("/api/student/report-cards")
@login_required
def student_report_cards():
    if session.get("role") != "student":
        return jsonify({"error": "Student access required."}), 403
    with db() as conn:
        rows=conn.execute("SELECT id,title,file_name,created_at FROM student_report_cards WHERE student_user_id=%s ORDER BY created_at DESC",(session["user_id"],)).fetchall()
    return jsonify({"report_cards":[{"id":r["id"],"title":r["title"],"file_name":r["file_name"],"created_at":r["created_at"].isoformat() if r["created_at"] else None} for r in rows]})

@app.get("/api/student/report-cards/<int:report_id>/download")
@login_required
def download_student_report_card(report_id):
    if session.get("role") != "student":
        return jsonify({"error": "Student access required."}), 403
    from flask import Response
    with db() as conn:
        row=conn.execute("SELECT file_name,file_data FROM student_report_cards WHERE id=%s AND student_user_id=%s",(report_id,session["user_id"])).fetchone()
    if not row:
        return jsonify({"error":"Report card not found."}),404
    from urllib.parse import quote
    original_name = str(row["file_name"] or "report-card.pdf")
    # Use an ASCII fallback plus RFC 5987 UTF-8 filename for Arabic and other Unicode names.
    ascii_name = "".join(ch for ch in original_name if ch.isascii() and (ch.isalnum() or ch in " ._-"))[:100].strip(" .") or "report-card.pdf"
    encoded_name = quote(original_name, safe="")
    disposition = 'attachment; filename="' + ascii_name.replace('"', "") + '"; filename*=UTF-8\'\'' + encoded_name
    return Response(bytes(row["file_data"]),mimetype="application/pdf",headers={"Content-Disposition":disposition,"X-Content-Type-Options":"nosniff"})

@app.get("/api/admin/report-cards")
@admin_required
def admin_report_cards():
    with db() as conn:
        rows=conn.execute("""SELECT r.id,r.title,r.file_name,r.created_at,u.id AS student_id,u.full_name,u.student_id AS school_student_id
          FROM student_report_cards r JOIN portal_users u ON u.id=r.student_user_id
          ORDER BY r.created_at DESC LIMIT 300""").fetchall()
    return jsonify({"report_cards":[{"id":r["id"],"title":r["title"],"file_name":r["file_name"],"created_at":r["created_at"].isoformat() if r["created_at"] else None,"user_id":r["student_id"],"student_name":r["full_name"],"student_id":r["school_student_id"]} for r in rows]})

@app.post("/api/admin/report-cards")
@admin_required
def upload_student_report_card():
    if not verify_csrf():
        return jsonify({"error":"Refresh the page and try again."}),400
    student_id=str(request.form.get("student_user_id","")).strip()
    title=str(request.form.get("title","")).strip()
    uploaded=request.files.get("report_file")
    if not student_id.isdigit() or not title or len(title)>160 or not uploaded:
        return jsonify({"error":"Choose a student, enter a title and select a PDF report card."}),400
    data=uploaded.read(5*1024*1024+1)
    if len(data)>5*1024*1024:
        return jsonify({"error":"PDF must be 5 MB or smaller."}),413
    if not data.startswith(b"%PDF-"):
        return jsonify({"error":"Only valid PDF report cards are accepted."}),400
    filename=os.path.basename(uploaded.filename or "report-card.pdf")[:255]
    if not filename.lower().endswith(".pdf"):
        filename="report-card.pdf"
    with db() as conn:
        student=conn.execute("SELECT id FROM portal_users WHERE id=%s AND role='student' AND status='approved'",(int(student_id),)).fetchone()
        if not student:
            return jsonify({"error":"Approved student account not found."}),404
        row=conn.execute("INSERT INTO student_report_cards(student_user_id,title,file_name,file_data,uploaded_by) VALUES (%s,%s,%s,%s,%s) RETURNING id",(int(student_id),title,filename,psycopg.Binary(data),session["user_id"])).fetchone()
        conn.execute("INSERT INTO student_activity(student_user_id,actor_user_id,activity_type,description) VALUES (%s,%s,'report_card_uploaded',%s)",(int(student_id),session["user_id"],"Administrator uploaded report card: "+title[:180]))
        conn.commit()
    return jsonify({"message":"Report card uploaded and assigned to the student.","id":row["id"]}),201

@app.delete("/api/admin/report-cards/<int:report_id>")
@admin_required
def delete_student_report_card(report_id):
    if not verify_csrf():
        return jsonify({"error":"Refresh the page and try again."}),400
    with db() as conn:
        row=conn.execute("DELETE FROM student_report_cards WHERE id=%s RETURNING student_user_id,title",(report_id,)).fetchone()
        if not row:
            return jsonify({"error":"Report card not found."}),404
        conn.execute("INSERT INTO student_activity(student_user_id,actor_user_id,activity_type,description) VALUES (%s,%s,'report_card_deleted',%s)",(row["student_user_id"],session["user_id"],"Administrator removed report card: "+row["title"][:180]))
        conn.commit()
    return jsonify({"message":"Report card removed."})

@app.post("/api/admin/create-student")
@admin_required
def create_student():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    name = str(data.get("full_name", "")).strip()
    father_name = str(data.get("father_name", "")).strip()
    surname = str(data.get("surname", "")).strip()
    arabic_name = str(data.get("arabic_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    student_id = str(data.get("student_id", "")).strip() or None
    class_name = str(data.get("class_name", "")).strip()
    grade = str(data.get("grade", "")).strip()
    if len(name) < 2 or not father_name or not surname or not arabic_name or not phone or not class_name or not grade or "@" not in email:
        return jsonify({"error": "Enter a full name and valid email."}), 400
    if len(password) < 6:
        return jsonify({"error": "Temporary password must be at least 6 characters."}), 400
    try:
        with db() as conn:
            if not student_id:
                student_id = generate_student_id(conn)
            row = conn.execute(
                "INSERT INTO portal_users(full_name,father_name,surname,arabic_name,phone,email,student_id,password_hash,status,class_name,grade,approved_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,%s,NOW()) RETURNING *",
                (name, father_name, surname, arabic_name, phone, email, student_id, generate_password_hash(password), class_name, grade)
            ).fetchone()
            conn.commit()
        return jsonify({"student": user_public(row)}), 201
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "That email or student ID is already in use."}), 409

@app.post("/api/admin/students/<int:user_id>/edit")
@admin_required
def edit_student(user_id):
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    fields = ("full_name","father_name","guardian_name","surname","arabic_name","phone","email","student_id","class_name","grade","gender","nationality")
    values = {key: str(data.get(key, "")).strip() for key in fields}
    if not values["full_name"] or "@" not in values["email"]:
        return jsonify({"error": "Enter a student name and valid email."}), 400
    try:
        dob = datetime.strptime(str(data.get("date_of_birth", "")), "%Y-%m-%d").date() if data.get("date_of_birth") else None
    except ValueError:
        return jsonify({"error": "Enter a valid date of birth."}), 400
    try:
        with db() as conn:
            row = conn.execute("UPDATE portal_users SET full_name=%s,father_name=%s,guardian_name=%s,surname=%s,arabic_name=%s,phone=%s,email=%s,student_id=%s,class_name=%s,grade=%s,gender=%s,nationality=%s,date_of_birth=%s WHERE id=%s AND role=%s RETURNING *", (values["full_name"],values["father_name"],values["guardian_name"],values["surname"],values["arabic_name"],values["phone"],values["email"],values["student_id"] or None,values["class_name"],values["grade"],values["gender"],values["nationality"],dob,user_id,"student")).fetchone()
            if not row:
                return jsonify({"error": "Student account not found."}), 404
            conn.execute("INSERT INTO student_activity(student_user_id,actor_user_id,activity_type,description) VALUES (%s,%s,%s,%s)", (user_id,session["user_id"],"profile_updated","Administrator updated student profile"))
            conn.commit()
        return jsonify({"student": user_public(row)})
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "Email or student ID is already in use."}), 409

@app.post("/api/admin/students/<int:user_id>/reset-password")
@admin_required
def reset_student_password(user_id):
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    password = str(data.get("password", ""))
    confirm = str(data.get("confirm", ""))
    if len(password) < 10 or password != confirm:
        return jsonify({"error": "Passwords must match and be at least 10 characters."}), 400
    with db() as conn:
        student = conn.execute("SELECT id FROM portal_users WHERE id=%s AND role=%s", (user_id,"student")).fetchone()
        if not student:
            return jsonify({"error": "Student account not found."}), 404
        conn.execute("UPDATE portal_users SET password_hash=%s WHERE id=%s", (generate_password_hash(password),user_id))
        conn.execute("INSERT INTO student_activity(student_user_id,actor_user_id,activity_type,description) VALUES (%s,%s,%s,%s)", (user_id,session["user_id"],"password_reset","Administrator reset student password"))
        conn.commit()
    return jsonify({"message": "Student password reset successfully."})
@app.post("/api/admin/students/<int:user_id>/student-id")
@admin_required
def assign_student_id(user_id):
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    student_id = str((request.json or {}).get("student_id", "")).strip()
    if not student_id or len(student_id) > 40:
        return jsonify({"error": "Enter a student ID of 1 to 40 characters."}), 400
    try:
        with db() as conn:
            row = conn.execute(
                "UPDATE portal_users SET student_id=%s WHERE id=%s AND role='student' RETURNING *",
                (student_id, user_id)
            ).fetchone()
            conn.commit()
        if not row:
            return jsonify({"error": "Student account not found."}), 404
        return jsonify({"student": user_public(row)})
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "That student ID is already assigned to another student."}), 409

@app.post("/api/admin/students/<int:user_id>/status")
@admin_required
def update_status(user_id):
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    status = str((request.json or {}).get("status", ""))
    if status not in ("approved", "rejected", "pending"):
        return jsonify({"error": "Invalid status."}), 400
    with db() as conn:
        row = conn.execute(
            "UPDATE portal_users SET status=%s, approved_at=CASE WHEN %s='approved' THEN NOW() ELSE NULL END WHERE id=%s AND role='student' RETURNING *",
            (status, status, user_id)
        ).fetchone()
        conn.commit()
    if not row:
        return jsonify({"error": "Student account not found."}), 404
    return jsonify({"student": user_public(row)})

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#5a3d2b"><title>Student Portal | Alh. Lalo Kanteh Islamic Institute</title>
<style>
:root{--brown:#5a3d2b;--dark:#2f2119;--sand:#f3e8d7;--paper:#fffdf9;--line:#e7d8c5;--muted:#766b60}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--dark);font-family:Arial,Helvetica,sans-serif;line-height:1.5}
header{background:#fff;border-bottom:1px solid var(--line);padding:16px 5%;display:flex;align-items:center;justify-content:space-between;gap:12px}.header-actions{display:flex;align-items:center;gap:12px}.language-toggle{margin:0;white-space:nowrap}
.brand{font-weight:800;color:var(--brown);text-decoration:none;letter-spacing:.02em}.brand small{display:block;color:var(--muted);font-size:11px;letter-spacing:.1em}
main{max-width:1100px;margin:0 auto;padding:36px 18px 60px}.hero{background:linear-gradient(90deg,rgba(54,35,23,.82),rgba(54,35,23,.42)),url('https://i.ibb.co/vCJ0SBKH/IMG-20260924-WA0131.jpg') center/cover no-repeat;background-color:var(--brown);color:white;border-radius:22px;padding:clamp(24px,5vw,52px);margin-bottom:24px;min-height:250px;display:flex;flex-direction:column;justify-content:center}
.eyebrow{font-size:12px;letter-spacing:.16em;font-weight:700;color:#e8d5bd}.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.12;margin:12px 0}.hero p{max-width:650px;color:#f4e9dd}.layout{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:18px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 8px 28px #5a3d2b0b}
h2{margin:0 0 8px;font-size:23px}h3{margin:0 0 12px}label{display:block;font-weight:700;font-size:13px;margin:12px 0 5px}input,select{width:100%;padding:12px;border:1px solid #d8c7b2;border-radius:9px;font:inherit;background:#fff}
.password-field{position:relative}.password-field input{padding-right:52px}.password-toggle{position:absolute;right:7px;top:50%;transform:translateY(-50%);margin:0;padding:7px 9px;background:transparent;color:var(--brown);border:0;font-size:18px;line-height:1}.password-toggle:focus{outline:2px solid var(--brown);outline-offset:2px}button,.button{border:0;border-radius:10px;background:var(--brown);color:white;padding:12px 16px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;margin-top:14px}
button.secondary{background:var(--sand);color:var(--brown)}button:disabled{opacity:.5;cursor:wait}.muted{color:var(--muted);font-size:14px}.notice{padding:12px 14px;border-radius:10px;background:var(--sand);margin:12px 0}.error{background:#fff0ed;color:#7d2619}.success{background:#edf7ed;color:#23572b}

/* Administrator dashboard: blue, white and grey only. */
#adminPanel .card{background:#fff;border-color:#d8e0ea;color:#172b4d;box-shadow:0 8px 24px #183b6310}
#adminPanel h2,#adminPanel h3{color:#174a85}
#adminPanel .muted,#adminPanel .tiny{color:#64748b}
#adminPanel button{background:#1769aa;color:#fff}
#adminPanel button.secondary{background:#e8eef5;color:#243b53}
#adminPanel input{border-color:#cbd5e1;color:#172b4d}
.admin-table-wrap{width:100%;overflow-x:auto;border:1px solid #d8e0ea;border-radius:12px;background:#fff}
.admin-students-table{border-collapse:collapse;width:100%;min-width:1900px;font-size:13px;color:#243b53}
.admin-students-table th{position:sticky;top:0;background:#eaf1f8;color:#174a85;text-align:left;font-weight:700;white-space:nowrap}
.admin-students-table th,.admin-students-table td{padding:10px 12px;border-bottom:1px solid #e2e8f0;vertical-align:middle}
.admin-students-table tbody tr:nth-child(even){background:#f7f9fc}
.admin-students-table tbody tr:hover{background:#edf4fb}
.admin-student-photo{width:64px;height:64px;object-fit:cover;border-radius:8px;border:1px solid #cbd5e1}
.admin-no-photo,.admin-status{display:inline-block;padding:5px 8px;border-radius:7px;background:#edf2f7;color:#475569;white-space:nowrap}
.admin-students-table input{min-width:120px;padding:8px;border:1px solid #cbd5e1;border-radius:7px}
.admin-actions{display:flex;gap:6px;flex-wrap:wrap;min-width:180px}
.admin-actions button{margin:0;padding:7px 9px;font-size:12px}
.admin-security-note{color:#64748b;font-size:13px;margin-top:12px}

/* Report-card upload area */
.report-upload-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;align-items:end}
.report-upload-list{margin-top:16px;display:grid;gap:9px}
.report-upload-row{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:12px;border:1px solid #dce5ef;border-radius:11px}
.report-demo-badge{display:inline-block;padding:5px 9px;border-radius:7px;background:#fff3cd;color:#765500;font-size:11px;font-weight:800;letter-spacing:.05em}
/* Student dashboard */
.student-profile-head{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:12px 0 18px}
.student-avatar{width:76px;height:76px;object-fit:cover;border-radius:50%;border:3px solid #e4edf6}
.student-avatar-empty{display:grid;place-items:center;background:#edf3f9;font-size:30px}
.student-profile-head h3{margin:0;color:#174a85;font-size:20px}
.student-quick-facts,.student-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.student-quick-facts>div,.student-stat,.student-content-card{background:#fff;border:1px solid #dce5ef;border-radius:15px;padding:17px}
.student-quick-facts small,.student-account-grid small{display:block;color:#64748b;font-size:11px;font-weight:700;letter-spacing:.08em}
.student-quick-facts strong,.student-account-grid strong{display:block;margin-top:5px;color:#193b60;overflow-wrap:anywhere}
.student-workspace{margin-top:18px;color:#172b4d}
.student-nav{display:flex;gap:8px;overflow-x:auto;padding:5px 1px 14px}
.student-nav-btn{flex:0 0 auto;margin:0;background:#edf2f7!important;color:#29445f!important;border:1px solid #d8e2ed!important}
.student-nav-btn.active{background:#1769aa!important;color:#fff!important;border-color:#1769aa!important}
.student-section-heading{margin:12px 0 18px}
.student-kicker{font-size:11px;font-weight:800;letter-spacing:.13em;color:#1769aa;margin:0 0 5px}
.student-section-heading h2{color:#174a85;margin:0}
.student-stat{min-height:118px;box-shadow:0 5px 18px #183b6308}
.student-stat span,.student-stat small{display:block;color:#64748b}
.student-stat strong{display:block;font-size:28px;color:#174a85;margin:5px 0}
.student-feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:14px}
.student-content-card{margin-bottom:14px;box-shadow:0 5px 18px #183b6308}
.student-content-card h3{color:#174a85}
.student-empty{text-align:center;padding:18px 10px;color:#64748b}
.student-empty>span{font-size:27px;color:#8aa3bd}
.student-empty h3{margin:7px 0;color:#29445f}
.student-empty p{max-width:520px;margin:0 auto;font-size:14px}
.student-download-btn{background:#e8eef5!important;color:#64748b!important;cursor:not-allowed!important}
.student-account-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px}
@media(max-width:560px){.student-nav{margin-left:-4px;margin-right:-4px}.student-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.student-quick-facts{grid-template-columns:1fr 1fr}}

.hidden{display:none!important}.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.student{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.pill{font-size:12px;font-weight:700;background:var(--sand);color:var(--brown);padding:4px 8px;border-radius:999px}.tiny{font-size:12px;color:var(--muted)}
footer{text-align:center;padding:24px;color:var(--muted);border-top:1px solid var(--line)}a{color:var(--brown)}
</style></head><body>
<header><a class="brand" href="/">ALH. LALO KANTEH ISLAMIC INSTITUTE<small>TABOKOTO · THE GAMBIA</small></a><div class="header-actions"><a href="https://kelay-digital.onrender.com/school-demo/" class="tiny" data-i18n="School website ↗">School website ↗</a><button type="button" id="languageToggle" class="secondary language-toggle" aria-label="Switch language">العربية</button></div></header>
<main><section class="hero"><div class="eyebrow">STUDENT AREA</div><h1>Student Portal</h1><p>Access your student account, or request registration. Student accounts created by self-registration must be approved by the school.</p></section>
<div id="notice" class="notice hidden" role="status"></div>
<section id="setup" class="card hidden" style="margin-bottom:18px"><h2>First-time administrator setup</h2><p class="muted">Use this one-time setup only when the school is ready to appoint its first portal administrator. You need the private setup key configured by the site owner.</p><form id="setupForm"><label for="setupName">Administrator full name</label><input id="setupName" required maxlength="120" autocomplete="name"><label for="setupEmail">Administrator email</label><input id="setupEmail" type="email" required maxlength="254" autocomplete="email"><label for="setupPassword">Strong password (at least 6 characters)</label><input id="setupPassword" type="password" required minlength="6" autocomplete="new-password"><label for="setupKey">One-time setup key</label><input id="setupKey" type="password" required autocomplete="off"><button type="submit">Create first administrator</button></form><p class="tiny">Do not share the setup key. Once the first administrator exists, this setup endpoint cannot create another first administrator.</p></section>
<section id="auth" class="layout">
<div class="card"><h2>Sign in</h2><p class="muted">Use your approved school account.</p>
<form id="loginForm"><label for="loginRole">Sign in as</label><select id="loginRole" required><option value="student">Student</option><option value="staff">Staff</option></select><label for="loginEmail">Phone number</label><input id="loginEmail" autocomplete="username" required maxlength="254"><label for="loginPassword">Password</label><input id="loginPassword" type="password" autocomplete="current-password" required><p class="tiny"><a href="#passwordHelp" id="forgotPasswordLink">Forgot password?</a></p><button type="submit">Sign in</button></form></div>
<div class="card"><h2>Create an account</h2><p class="muted">Choose Student or Staff. The school must approve your account before you can sign in.</p><form id="registerForm"><label for="registerRole">Create account as</label><select id="registerRole" required><option value="student">Student</option><option value="staff">Staff</option></select><label for="regName">First name</label><input id="regName" required maxlength="120"><label for="regFather">Father's name</label><input id="regFather" required maxlength="120"><label for="regGuardian">Parent/Guardian's name</label><input id="regGuardian" required maxlength="120"><label for="regSurname">Surname</label><input id="regSurname" required maxlength="120"><label for="regDob">Date of birth</label><input id="regDob" type="date" required><label for="regClass">Current class</label><select id="regClass" required><option value="">Select class</option><option>Nursery 1</option><option>Nursery 2</option><option>Grade 1</option><option>Grade 2</option><option>Grade 3</option><option>Grade 4</option><option>Grade 5</option><option>Grade 6</option><option>Grade 7</option><option>Grade 8</option><option>Grade 9</option><option>Grade 10</option><option>Grade 11</option><option>Grade 12</option></select>
<label for="regGender">Gender</label><select id="regGender" required><option value="">Select gender</option><option value="Male">Male</option><option value="Female">Female</option></select>
<label for="regNationality">Nationality</label><select id="regNationality" required><option value="">Select nationality</option></select><label for="regPhone">Phone number</label><input id="regPhone" type="tel" required maxlength="40" autocomplete="tel"><label for="regPhoto">Profile picture (required)</label><input id="regPhoto" type="file" accept="image/*" required><p class="tiny">JPG, PNG, WebP, GIF, BMP, TIFF, HEIC, HEIF or AVIF. Up to 5 MB.</p><img id="photoPreview" class="hidden" alt="Profile picture preview" style="width:96px;height:96px;object-fit:cover;border-radius:50%;margin-top:8px;border:2px solid var(--line)"><label for="regPassword">Create password (6 characters minimum)</label><input id="regPassword" type="password" minlength="6" autocomplete="new-password" required><label for="regPasswordConfirm">Confirm password</label><input id="regPasswordConfirm" type="password" minlength="6" autocomplete="new-password" required><button type="submit">Submit registration</button></form></div>
</section>
<section id="passwordHelp" class="card hidden" style="max-width:620px;margin:0 auto"><h2>Password help</h2><p>If you are an administrator, use the secure one-time reset link provided by the school website administrator. If you are a student, contact the school administrator to verify your identity and reset your account password. For security, this page does not reveal or email existing passwords.</p><button type="button" class="secondary" id="closePasswordHelp">Back to sign in</button></section>
<section id="registrationSuccess" class="card hidden" style="max-width:680px;margin:0 auto;text-align:center;padding:clamp(28px,6vw,56px)"><div aria-hidden="true" style="font-size:48px;color:#23572b">✓</div><h2>Application submitted successfully!</h2><p class="muted" style="font-size:16px">Your student registration has been received. The school will review your application. You can sign in after the school approves your account.</p><p class="muted">Please keep your phone number and password safe. You do not need to submit the form again.</p><button type="button" id="backToSignIn">Back to sign in</button></section>
<section id="dashboard" class="hidden"><div class="card"><div class="bar"><div><p class="eyebrow" style="color:var(--brown)">YOUR ACCOUNT</p><h2 id="welcome">Welcome</h2></div><button class="secondary" id="logout">Sign out</button></div><div id="profile"></div></div><div id="adminPanel" class="hidden">
<div class="card" style="margin-top:18px"><h2>Student records</h2><p class="muted">Review each student's name and nationality, and assign a unique student ID. You can also approve or reject accounts.</p><div id="studentList">Loading student records…</div>
<div id="studentPage" class="card hidden" style="margin-top:18px">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
    <h3>Student account overview</h3><button type="button" id="closeStudentPage">Back to students</button>
  </div>
  <div id="studentOverview"></div>
</div></div>
<div class="card" style="margin-top:18px"><h2>Report Cards</h2><p class="muted">Upload a PDF report card and assign it to an approved student. Only that student can download it.</p><form id="reportUploadForm" class="report-upload-form"><label>Student<select id="reportStudent" name="student_user_id" required><option value="">Choose student</option></select></label><label>Report title<input id="reportTitle" name="title" maxlength="160" placeholder="e.g. Term 1 Report Card" required></label><label>PDF file<input id="reportFile" name="report_file" type="file" accept="application/pdf,.pdf" required></label><button type="submit">Upload report card</button></form><div id="adminReportCards" class="report-upload-list">Loading uploaded report cards…</div></div><div class="card" style="margin-top:18px"><h2>Create a student account</h2><form id="createStudent"><label for="newName">First name</label><input id="newName" required maxlength="120"><label for="newFather">Father name</label><input id="newFather" required maxlength="120"><label for="newSurname">Surname</label><input id="newSurname" required maxlength="120"><label for="newArabic">Full name in Arabic</label><input id="newArabic" required maxlength="200" dir="rtl"><label for="newPhone">Phone number</label><input id="newPhone" type="tel" required maxlength="40"><label for="newEmail">Email</label><input id="newEmail" type="email" required maxlength="254"><label for="newId">Student ID</label><input id="newId" maxlength="40"><label for="newClass">Class</label><input id="newClass" required maxlength="80"><label for="newGrade">Grade</label><input id="newGrade" required maxlength="80"><label for="newPassword">Temporary password (6 characters minimum)</label><input id="newPassword" type="password" minlength="6" required><button type="submit">Create approved account</button></form></div></div>
</section>
</main><footer>Alh. Lalo Kanteh Islamic Institute · Tabokoto, The Gambia</footer>
<script>
let csrf = "";
const $ = id => document.getElementById(id);
let currentLanguage = localStorage.getItem("studentPortalLanguage") || "en";
const originalText = new WeakMap();
const translations = {
"School website ↗":"موقع المدرسة ↗","STUDENT AREA":"منطقة الطلاب","Student Portal":"بوابة الطلاب",
"Access your student account, or request registration. Student accounts created by self-registration must be approved by the school.":"ادخل إلى حسابك الطلابي أو اطلب التسجيل. يجب أن توافق المدرسة على حسابات الطلاب التي يتم إنشاؤها بالتسجيل الذاتي.",
"Sign in":"تسجيل الدخول","Use your approved school account.":"استخدم حسابك المدرسي المعتمد.","Phone number or administrator email":"رقم الهاتف أو البريد الإلكتروني للإدارة","Password":"كلمة المرور",
"Application submitted successfully!":"تم إرسال طلب التسجيل بنجاح!","Your student registration has been received. The school will review your application. You can sign in after the school approves your account.":"تم استلام طلب تسجيلك. ستراجع المدرسة طلبك، ويمكنك تسجيل الدخول بعد موافقة المدرسة على حسابك.","Please keep your phone number and password safe. You do not need to submit the form again.":"يرجى الاحتفاظ برقم هاتفك وكلمة المرور. لا تحتاج إلى إرسال الطلب مرة أخرى.","Back to sign in":"العودة إلى تسجيل الدخول",
"Student registration":"تسجيل الطلاب","Register using your school details. The school must approve your account before you can sign in.":"سجّل باستخدام بياناتك المدرسية. يجب أن توافق المدرسة على حسابك قبل تسجيل الدخول.",
"First name":"الاسم الأول","Father's name":"اسم الأب","Father name":"اسم الأب","Parent/Guardian's name":"اسم ولي الأمر","Surname":"اسم العائلة","Date of birth":"تاريخ الميلاد","Current class":"الفصل الحالي","Gender":"الجنس","Select gender":"اختر الجنس","Nationality":"الجنسية","Select nationality":"اختر الجنسية","Select class":"اختر الصف","Phone number":"رقم الهاتف","Profile picture (required)":"الصورة الشخصية (مطلوبة)","JPG, PNG, WebP, GIF, BMP, TIFF, HEIC, HEIF or AVIF. Up to 5 MB.":"JPG أو PNG أو WebP أو GIF أو BMP أو TIFF أو HEIC أو HEIF أو AVIF. حتى 5 ميغابايت.",
"Create password (6 characters minimum)":"إنشاء كلمة مرور (6 أحرف على الأقل)","Confirm password":"تأكيد كلمة المرور","Submit registration":"إرسال طلب التسجيل",
"YOUR ACCOUNT":"حسابك","Welcome":"مرحبًا","Sign out":"تسجيل الخروج","Pending and approved students":"الطلاب قيد الانتظار والطلاب المعتمدون",
"Approve self-registrations or reject accounts. Only approved students can sign in.":"وافق على طلبات التسجيل الذاتي أو ارفض الحسابات. يمكن للطلاب المعتمدين فقط تسجيل الدخول.",
"Loading student records…":"جارٍ تحميل سجلات الطلاب…","Create a student account":"إنشاء حساب طالب","Full name in Arabic":"الاسم الكامل باللغة العربية","Email":"البريد الإلكتروني","Student ID":"رقم الطالب","Class":"الفصل","Grade":"الصف الدراسي","Temporary password (6 characters minimum)":"كلمة مرور مؤقتة (6 أحرف على الأقل)","Create approved account":"إنشاء حساب معتمد",
"Alh. Lalo Kanteh Islamic Institute · Tabokoto, The Gambia":"معهد الحاج لالو كانتي الإسلامي · تبوكتو، غامبيا",
"Not assigned":"غير محدد","Account status:":"حالة الحساب:","Exam results and attendance can be added when the school provides verified records.":"يمكن إضافة نتائج الامتحانات والحضور عندما توفر المدرسة سجلات موثقة.",
"No student accounts yet.":"لا توجد حسابات طلاب حتى الآن.","No photo":"لا توجد صورة","No student ID":"لا يوجد رقم طالب","No class":"لا يوجد فصل","Approve":"اعتماد","Reject":"رفض",
"Sign in successfully.":"تم تسجيل الدخول بنجاح.","Student status updated.":"تم تحديث حالة الطالب.","Student account created and approved.":"تم إنشاء حساب الطالب واعتماده.",
"Passwords do not match.":"كلمتا المرور غير متطابقتين.","Choose a valid image file up to 5 MB.":"اختر صورة صالحة بحجم لا يتجاوز 5 ميغابايت.","Choose a picture smaller than 5 MB.":"اختر صورة أصغر من 5 ميغابايت.","Could not read that picture.":"تعذرت قراءة الصورة.","That picture could not be opened.":"تعذر فتح الصورة.",
"Please sign in.":"يرجى تسجيل الدخول.","Phone number or password is incorrect.":"رقم الهاتف أو كلمة المرور غير صحيحة.","Student registration is not open yet. Please contact the school.":"لم يُفتح تسجيل الطلاب بعد. يرجى التواصل مع المدرسة.","Refresh the page and try again.":"حدّث الصفحة وحاول مرة أخرى.","Unexpected server response.":"استجابة غير متوقعة من الخادم.","Request failed.":"فشل الطلب.","Portal is not configured yet.":"لم يتم إعداد البوابة بعد.","Portal setup is not complete yet. Please contact the website administrator. ":"لم يكتمل إعداد البوابة بعد. يرجى التواصل مع مسؤول الموقع. ",
"Registration submitted. The school must approve your account before you can sign in.":"تم إرسال طلب التسجيل. يجب أن توافق المدرسة على حسابك قبل تسجيل الدخول.","DEMONSTRATION WEBSITE":"موقع تجريبي","— This is a proposed school website, not yet officially approved by the school. Please do not enter real student information.":"— هذا موقع مقترح للمدرسة ولم تتم الموافقة عليه رسميًا بعد. يرجى عدم إدخال معلومات حقيقية عن الطلاب.","This is a proposed school website, not yet officially approved by the school. Please do not enter real student information.":"هذا موقع مقترح للمدرسة ولم تتم الموافقة عليه رسميًا بعد. يرجى عدم إدخال معلومات حقيقية عن الطلاب.","This is a demonstration portal. Student registration will open only after the school officially approves the website.":"هذه بوابة تجريبية. سيتم فتح تسجيل الطلاب بعد موافقة المدرسة رسميًا على الموقع."
};
function applyLanguage(){
  const ar=currentLanguage==="ar";
  document.documentElement.lang=ar?"ar":"en";
  document.documentElement.dir=ar?"rtl":"ltr";
  document.body.dir=ar?"rtl":"ltr";
  document.querySelectorAll("body *:not(#languageToggle)").forEach(el=>{
    el.childNodes.forEach(node=>{
      if(node.nodeType===Node.TEXT_NODE && node.textContent.trim()){
        if(!originalText.has(node)) originalText.set(node,node.textContent);
        const source=originalText.get(node), trimmed=source.trim();
        const translated=ar?(translations[trimmed]||trimmed):trimmed;
        node.textContent=source.replace(trimmed,translated);
      }
    });
    ["placeholder","title","aria-label"].forEach(attr=>{
      if(!el.hasAttribute(attr)) return;
      const current=el.getAttribute(attr);
      if(!el.dataset["original"+attr.replace(/(^|-)(.)/g,(_,a,b)=>b.toUpperCase())]){
        el.dataset["original"+attr.replace(/(^|-)(.)/g,(_,a,b)=>b.toUpperCase())]=current;
      }
      const key=el.dataset["original"+attr.replace(/(^|-)(.)/g,(_,a,b)=>b.toUpperCase())];
      if(ar && translations[key]) el.setAttribute(attr,translations[key]);
      else if(!ar) el.setAttribute(attr,key);
    });
  });
  $("languageToggle").textContent=ar?"English":"العربية";
  $("languageToggle").setAttribute("aria-label",ar?"Switch to English":"Switch to Arabic");
}
$("languageToggle").addEventListener("click",()=>{
  currentLanguage=currentLanguage==="en"?"ar":"en";
  localStorage.setItem("studentPortalLanguage",currentLanguage);
  applyLanguage();
});
// Add accessible show/hide controls to every password field (admin and student forms).
document.querySelectorAll('input[type="password"]').forEach(input=>{
  const wrap=document.createElement("div");
  wrap.className="password-field";
  input.parentNode.insertBefore(wrap,input);
  wrap.appendChild(input);
  const toggle=document.createElement("button");
  toggle.type="button";
  toggle.className="password-toggle";
  toggle.textContent="◉";
  toggle.setAttribute("aria-label","Show password");
  toggle.setAttribute("aria-pressed","false");
  toggle.addEventListener("click",()=>{
    const showing=input.type==="password";
    input.type=showing?"text":"password";
    toggle.setAttribute("aria-label",showing?"Hide password":"Show password");
    toggle.setAttribute("aria-pressed",showing?"true":"false");
    toggle.textContent=showing?"◎":"◉";
  });
  wrap.appendChild(toggle);
});
$("forgotPasswordLink").addEventListener("click",e=>{e.preventDefault();toggle("auth",false);toggle("passwordHelp",true);});
$("closePasswordHelp").addEventListener("click",()=>{toggle("passwordHelp",false);toggle("auth",true);});
function showNotice(message, kind="notice"){const n=$("notice");n.textContent=message;n.className=kind;}
async function api(path, data, method="POST"){const res=await fetch(path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:method==="GET"?undefined:JSON.stringify(data||{})});const body=await res.json().catch(()=>({error:"Unexpected server response."}));if(body.csrf_token)csrf=body.csrf_token;if(!res.ok)throw new Error(body.error||"Request failed.");return body;}
function toggle(id,on){$(id).classList.toggle("hidden",!on);}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
async function loadCsrf(){const r=await fetch("/api/csrf");const d=await r.json();if(!r.ok)throw new Error(d.error||"Portal is not configured yet.");csrf=d.csrf_token;}
async function imageToDataUrl(file){if(!file)throw new Error("Choose a profile picture first.");if(!file.type.startsWith("image/"))throw new Error("Choose an image file.");if(file.size>5*1024*1024)throw new Error("Choose a picture smaller than 5 MB.");return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error("Could not read that image file."));reader.readAsDataURL(file);});}
$("regPhoto").addEventListener("change",async()=>{try{if($("regPhoto").files[0]){$("photoPreview").src=await imageToDataUrl($("regPhoto").files[0]);toggle("photoPreview",true);}}catch(e){toggle("photoPreview",false);showNotice(e.message,"error");}});
function renderProfile(u){
  $("welcome").textContent="Welcome, "+u.full_name;
  const photo=u.profile_image?'<img src="'+u.profile_image+'" alt="Student profile picture" class="student-avatar">':'<div class="student-avatar student-avatar-empty" aria-hidden="true">👤</div>';
  $("profile").innerHTML='<div class="student-profile-head">'+photo+'<div><h3>'+esc(u.full_name)+'</h3><p class="muted">Your personal student space</p><span class="pill">'+esc(u.status)+'</span></div></div><div class="student-quick-facts"><div><small>STUDENT ID</small><strong>'+esc(u.student_id||"Not assigned")+'</strong></div><div><small>CLASS</small><strong>'+esc(u.class_name||"Not assigned")+'</strong></div><div><small>PHONE</small><strong>'+esc(u.phone||"Not added")+'</strong></div></div>';
  if(u.role==="student") renderStudentWorkspace(u);
}
function renderStudentWorkspace(u){
  const sections=[
    ["overview","Overview","A quick summary of your school account."],
    ["academics","Academics","Your subjects, timetable, assignments and learning materials."],
    ["performance","Performance","Examination results and downloadable report cards."],
    ["attendance","Attendance","Your attendance history and school attendance record."],
    ["account","My Account","Your registered personal and school details."]
  ];
  $("studentWorkspace")?.remove();
  const root=document.createElement("section");root.id="studentWorkspace";root.className="student-workspace";
  root.innerHTML='<nav class="student-nav" aria-label="Student dashboard sections">'+sections.map(([id,label])=>'<button type="button" class="student-nav-btn" data-student-tab="'+id+'">'+label+'</button>').join("")+'</nav><div id="studentWorkspaceContent"></div>';
  $("dashboard").appendChild(root);
  const content=root.querySelector("#studentWorkspaceContent");
  function panel(id){
    const heading=sections.find(s=>s[0]===id);
    root.querySelectorAll("[data-student-tab]").forEach(btn=>{const active=btn.dataset.studentTab===id;btn.classList.toggle("active",active);btn.setAttribute("aria-current",active?"page":"false");});
    const empty=(title,detail)=>'<div class="student-empty"><span aria-hidden="true">▤</span><h3>'+title+'</h3><p>'+detail+'</p></div>';
    if(id==="overview"){
      content.innerHTML='<div class="student-section-heading"><div><p class="student-kicker">STUDENT DASHBOARD</p><h2>My overview</h2><p class="muted">Welcome to your school dashboard, '+esc(u.full_name)+'.</p></div></div><div class="student-stat-grid"><article class="student-stat"><span>My subjects</span><strong>—</strong><small>Not added yet</small></article><article class="student-stat"><span>Attendance</span><strong>—</strong><small>No attendance records yet</small></article><article class="student-stat"><span>Latest result</span><strong>—</strong><small>No results published yet</small></article><article class="student-stat"><span>Assignments</span><strong>—</strong><small>No assignments posted yet</small></article></div><div class="student-content-card"><h3>School announcements</h3>'+empty("No announcements yet","School announcements will appear here when published by the school.")+'</div>';
    }else if(id==="academics"){
      content.innerHTML='<div class="student-section-heading"><div><p class="student-kicker">LEARNING</p><h2>Academics</h2><p class="muted">'+heading[2]+'</p></div></div><div class="student-feature-grid"><article class="student-content-card"><h3>My subjects</h3>'+empty("Subjects not available","Your registered subjects will appear here.")+'</article><article class="student-content-card"><h3>Timetable</h3>'+empty("Timetable not published","Your weekly lesson schedule will appear here.")+'</article><article class="student-content-card"><h3>Assignments</h3>'+empty("No assignments posted","Teachers’ assignments and due dates will appear here.")+'</article><article class="student-content-card"><h3>Learning materials</h3>'+empty("No materials uploaded","Notes and learning files shared by teachers will appear here.")+'</article></div>';
    }else if(id==="performance"){
      content.innerHTML='<div class="student-section-heading"><div><p class="student-kicker">ACADEMIC RECORD</p><h2>Performance & report cards</h2><p class="muted">A sample layout is shown for demonstration. Your actual records appear separately when the school uploads them.</p></div></div><div class="student-content-card"><span class="report-demo-badge">DEMO DATA · NOT OFFICIAL</span><h3 style="margin-top:12px">Example examination summary</h3><div class="student-stat-grid"><article class="student-stat"><span>Mathematics</span><strong>78%</strong><small>Sample score</small></article><article class="student-stat"><span>English</span><strong>84%</strong><small>Sample score</small></article><article class="student-stat"><span>Islamic Studies</span><strong>91%</strong><small>Sample score</small></article><article class="student-stat"><span>General Science</span><strong>73%</strong><small>Sample score</small></article></div><p class="tiny">These fictional figures are placeholders to demonstrate the dashboard only. They are not linked to your academic record.</p></div><div class="student-content-card"><h3>My official report cards</h3><div id="studentReportCards" class="report-upload-list">Loading report cards…</div></div>';loadStudentReportCards();
    }else if(id==="attendance"){
      content.innerHTML='<div class="student-section-heading"><div><p class="student-kicker">SCHOOL RECORD</p><h2>Attendance</h2><p class="muted">Review your attendance once the school begins recording it in the portal.</p></div></div><div class="student-content-card">'+empty("No attendance record yet","Your attendance history and summary will appear here after records are entered by the school.")+'</div>';
    }else{
      content.innerHTML='<div class="student-section-heading"><div><p class="student-kicker">PERSONAL DETAILS</p><h2>My Account</h2><p class="muted">Your registered details. Contact the school to correct information.</p></div></div><div class="student-content-card student-account-grid">'+[["Full name",u.full_name],["Father’s name",u.father_name],["Surname",u.surname],["Arabic name",u.arabic_name],["Date of birth",u.date_of_birth],["Gender",u.gender],["Nationality",u.nationality],["Phone",u.phone],["Student ID",u.student_id],["Class",u.class_name],["Email / login",u.email]].map(([k,v])=>'<div><small>'+k+'</small><strong>'+esc(v||"—")+'</strong></div>').join("")+'</div>';
    }
  }
  root.querySelectorAll("[data-student-tab]").forEach(btn=>btn.addEventListener("click",()=>panel(btn.dataset.studentTab)));
  panel("overview");
}
async function loadAdminReportCards(){
 const [students,docs]=await Promise.all([api("/api/admin/students",null,"GET"),api("/api/admin/report-cards",null,"GET")]);
 const select=$("reportStudent");const selected=select.value;
 select.innerHTML='<option value="">Choose student</option>'+students.students.filter(s=>s.status==="approved").map(s=>'<option value="'+s.id+'">'+esc(s.full_name)+' · '+esc(s.student_id||"No ID")+'</option>').join("");
 if(selected)select.value=selected;
 const list=$("adminReportCards");
 list.innerHTML=docs.report_cards.length?docs.report_cards.map(d=>'<div class="report-upload-row"><div><strong>'+esc(d.title)+'</strong><div class="tiny">'+esc(d.student_name)+' · '+esc(d.student_id||"No student ID")+' · '+esc(d.file_name)+'</div></div><button type="button" class="secondary" data-delete-report="'+d.id+'">Remove</button></div>').join(""):'<p class="muted">No report cards uploaded yet.</p>';
 list.querySelectorAll("[data-delete-report]").forEach(btn=>btn.addEventListener("click",async()=>{if(!confirm("Remove this report card from the student's account?"))return;try{await api("/api/admin/report-cards/"+btn.dataset.deleteReport,{},"DELETE");showNotice("Report card removed.","success");await loadAdminReportCards();}catch(e){showNotice(e.message,"error");}}));
}
$("reportUploadForm").addEventListener("submit",async e=>{
 e.preventDefault();const file=$("reportFile").files[0];if(!file)return;
 if(file.size>5*1024*1024){showNotice("PDF must be 5 MB or smaller.","error");return;}
 const form=new FormData(e.target);
 try{const response=await fetch("/api/admin/report-cards",{method:"POST",headers:{"X-CSRF-Token":csrf},body:form});const result=await response.json().catch(()=>({error:"Unexpected server response."}));if(!response.ok)throw new Error(result.error||"Upload failed.");e.target.reset();showNotice(result.message,"success");await loadAdminReportCards();}catch(err){showNotice(err.message,"error");}
});
async function loadStudentReportCards(){
 const list=$("studentReportCards");if(!list)return;
 try{const d=await api("/api/student/report-cards",null,"GET");list.innerHTML=d.report_cards.length?d.report_cards.map(r=>'<div class="report-upload-row"><div><strong>'+esc(r.title)+'</strong><div class="tiny">'+esc(r.file_name)+' · '+esc(r.created_at?new Date(r.created_at).toLocaleDateString():"")+'</div></div><a class="button" href="/api/student/report-cards/'+r.id+'/download">Download PDF</a></div>').join(""):'<p class="muted">No official report cards have been uploaded to your account yet.</p>';}catch(e){list.textContent=e.message;}
}
async function refreshStudents(){
  const d=await api("/api/admin/students",null,"GET");
  const list=$("studentList");
  if(!d.students.length){list.textContent="No student accounts yet.";return;}
  const columns=["Profile","Full name","Arabic name","Father's name","Parent/guardian","Surname","Phone","Email","Student ID","Date of birth","Gender","Nationality","Class","Grade","Account status","Registered","Actions"];
  list.innerHTML='<div class="admin-table-wrap"><table class="admin-students-table"><thead><tr>'+columns.map(c=>'<th>'+c+'</th>').join("")+'</tr></thead><tbody>'+d.students.map(s=>{
    const photo=s.profile_image?'<img src="'+s.profile_image+'" alt="Profile picture of '+esc(s.full_name)+'" class="admin-student-photo">':'<span class="admin-no-photo">No photo</span>';
    const cells=[photo,esc(s.full_name),esc(s.arabic_name||"—"),esc(s.father_name||"—"),esc(s.guardian_name||"—"),esc(s.surname||"—"),esc(s.phone||"—"),esc(s.email||"—"),'<input aria-label="Student ID for '+esc(s.full_name)+'" data-student-id="'+s.id+'" value="'+esc(s.student_id||"")+'" maxlength="40" placeholder="Student ID">',esc(s.date_of_birth||"—"),esc(s.gender||"—"),esc(s.nationality||"—"),esc(s.class_name||"—"),esc(s.grade||"—"),'<span class="admin-status">'+esc(s.status)+'</span>',esc(s.created_at?new Date(s.created_at).toLocaleString():"—"),'<div class="admin-actions"><button type="button" data-open-student="'+s.id+'">Open student page</button><button type="button" data-save-id="'+s.id+'">Save ID</button>'+(s.status!=="approved"?'<button type="button" data-id="'+s.id+'" data-status="approved">Approve</button>':"")+(s.status!=="rejected"?'<button type="button" data-id="'+s.id+'" data-status="rejected">Reject</button>':"")+'</div>'];
    return '<tr>'+cells.map((v,n)=>'<td'+(n===2?' dir="rtl"':"")+'>'+v+'</td>').join("")+'</tr>';
  }).join("")+'</tbody></table></div><p class="admin-security-note">Passwords are securely hashed and cannot be viewed, including by administrators. Use a password reset process if a student needs a new password.</p>';
  list.querySelectorAll("button[data-open-student]").forEach(b=>b.addEventListener("click",async()=>{try{await openStudentPage(b.dataset.openStudent);}catch(e){showNotice(e.message,"error");}}));
  list.querySelectorAll("button[data-save-id]").forEach(b=>b.addEventListener("click",async()=>{const field=list.querySelector('input[data-student-id="'+b.dataset.saveId+'"]');try{await api("/api/admin/students/"+b.dataset.saveId+"/student-id",{student_id:field.value});showNotice("Student ID saved.","success");await refreshStudents();}catch(e){showNotice(e.message,"error");}}));
  list.querySelectorAll("button[data-id]").forEach(b=>b.addEventListener("click",async()=>{try{await api("/api/admin/students/"+b.dataset.id+"/status",{status:b.dataset.status});showNotice("Student status updated.","success");await refreshStudents();}catch(e){showNotice(e.message,"error");}}));
}
async function openStudentPage(id){
  const d=await api("/api/admin/students/"+id+"/overview",null,"GET");
  const u=d.student;
  const fields=[["Full name",u.full_name],["Arabic name",u.arabic_name],["Father's name",u.father_name],["Parent/guardian",u.guardian_name],["Surname",u.surname],["Phone",u.phone],["Email",u.email],["Student ID",u.student_id||"Not assigned"],["Date of birth",u.date_of_birth],["Gender",u.gender],["Nationality",u.nationality],["Class",u.class_name],["Grade",u.grade],["Account status",u.status],["Registration date",u.created_at?new Date(u.created_at).toLocaleString():"—"]];
  const photo=u.profile_image?'<img src="'+u.profile_image+'" alt="Student profile" style="width:104px;height:104px;object-fit:cover;border-radius:50%;border:2px solid var(--line)">':"";
  const profile='<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:12px 0">'+photo+'<div><h3>'+esc(u.full_name)+'</h3><p class="muted">Same account details available on the student dashboard</p></div></div><div class="student-overview-grid">'+fields.map(([k,v])=>'<div><small class="muted">'+esc(k)+'</small><p>'+esc(v||"—")+'</p></div>').join("")+'</div><p class="muted">Exam results and attendance are not currently stored in this portal.</p>';
  const history=d.activities.length?d.activities.map(a=>'<div style="padding:12px 0;border-bottom:1px solid var(--line)"><strong>'+esc(a.description)+'</strong><p class="muted">'+esc(a.activity_type)+' · '+esc(a.actor_name)+' · '+esc(a.created_at?new Date(a.created_at).toLocaleString():"")+'</p></div>').join(""):'<p class="muted">No activity has been recorded for this student yet. Activity history starts when tracking is enabled.</p>';
  const editFields=[["full_name","Full name"],["arabic_name","Arabic name"],["father_name","Father name"],["guardian_name","Parent/guardian"],["surname","Surname"],["phone","Phone"],["email","Email"],["student_id","Student ID"],["date_of_birth","Date of birth"],["gender","Gender"],["nationality","Nationality"],["class_name","Class"],["grade","Grade"]];
  const editForm='<h3>Edit student information</h3><form id="editStudentForm" class="form-grid">'+editFields.map(([k,label])=>'<label>'+label+'<input name="'+k+'" type="'+(k==="date_of_birth"?"date":"text")+'" value="'+esc(u[k]||"")+'"></label>').join("")+'<button class="primary" type="submit">Save student details</button></form>';
  const resetForm='<h3>Reset student password</h3><form id="resetStudentForm" class="form-grid"><label>New password<input name="password" type="password" minlength="10" required></label><label>Confirm new password<input name="confirm" type="password" minlength="10" required></label><button class="primary" type="submit">Reset password</button></form>';
  $("studentOverview").innerHTML=profile+editForm+resetForm+'<h3>Activity history</h3>'+history+'<p class="admin-security-note">This history contains recorded events only. Passwords and password hashes are never displayed.</p>';
  $("editStudentForm").addEventListener("submit",async e=>{e.preventDefault();try{const data=Object.fromEntries(new FormData(e.target).entries());await api("/api/admin/students/"+id+"/edit",data);showNotice("Student information saved.","success");await refreshStudents();await openStudentPage(id);}catch(err){showNotice(err.message,"error");}});
  $("resetStudentForm").addEventListener("submit",async e=>{e.preventDefault();try{const data=Object.fromEntries(new FormData(e.target).entries());await api("/api/admin/students/"+id+"/reset-password",data);e.target.reset();showNotice("Student password reset successfully.","success");await openStudentPage(id);}catch(err){showNotice(err.message,"error");}});
  toggle("studentPage",true);
  $("studentPage").scrollIntoView({behavior:"smooth",block:"start"});
}
$("closeStudentPage").addEventListener("click",()=>toggle("studentPage",false));
async function showUser(u){toggle("auth",false);toggle("setup",false);toggle("dashboard",true);renderProfile(u);const admin=u.role==="admin";toggle("adminPanel",admin);if(admin){await refreshStudents();await loadAdminReportCards();}}
async function boot(){try{await loadCsrf();const sr=await fetch("/api/setup-status");const sd=await sr.json();const r=await fetch("/api/me");if(r.ok){const d=await r.json();await showUser(d.user);}else if(!sd.database_ready){throw new Error("The student database is not ready. Please contact the website administrator.");}else if(sd.setup_needed){toggle("auth",false);toggle("setup",true);}else{toggle("setup",false);toggle("auth",true);}}catch(e){toggle("setup",false);toggle("auth",true);showNotice("Portal setup is not complete yet. "+e.message,"error");}}
$("setupForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/setup-admin",{setup_key:$("setupKey").value,full_name:$("setupName").value,email:$("setupEmail").value,password:$("setupPassword").value});e.target.reset();toggle("setup",false);await showUser(d.user);showNotice("First administrator account created successfully.","success");}catch(err){showNotice(err.message,"error");}});
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/login",{role:$("loginRole").value,login:$("loginEmail").value,password:$("loginPassword").value});await showUser(d.user);showNotice("Signed in successfully.","success");}catch(err){showNotice(err.message,"error");}});
$("registerForm").addEventListener("submit",async e=>{e.preventDefault();try{const selectedRole=$("registerRole").value;const photo=await imageToDataUrl($("regPhoto").files[0]);if($("regPassword").value!==$("regPasswordConfirm").value)throw new Error("Passwords do not match.");const d=await api("/api/register",{role:selectedRole,full_name:$("regName").value,father_name:$("regFather").value,guardian_name:$("regGuardian").value,surname:$("regSurname").value,date_of_birth:$("regDob").value,phone:$("regPhone").value,class_name:$("regClass").value,gender:$("regGender").value,nationality:$("regNationality").value,password:$("regPassword").value,password_confirm:$("regPasswordConfirm").value,profile_image:photo});e.target.reset();toggle("photoPreview",false);toggle("auth",false);toggle("registrationSuccess",true);window.scrollTo({top:0,behavior:"smooth"});}catch(err){showNotice(err.message,"error");}});
$("backToSignIn").addEventListener("click",()=>{toggle("registrationSuccess",false);toggle("auth",true);window.scrollTo({top:0,behavior:"smooth"});});
$("logout").addEventListener("click",async()=>{try{await api("/api/logout",{});location.reload();}catch(e){showNotice(e.message,"error");}});
$("createStudent").addEventListener("submit",async e=>{e.preventDefault();try{await api("/api/admin/create-student",{full_name:$("newName").value,father_name:$("newFather").value,surname:$("newSurname").value,arabic_name:$("newArabic").value,phone:$("newPhone").value,email:$("newEmail").value,student_id:$("newId").value,class_name:$("newClass").value,grade:$("newGrade").value,password:$("newPassword").value});e.target.reset();showNotice("Student account created and approved.","success");await refreshStudents();}catch(err){showNotice(err.message,"error");}});
const countryNames=["Afghanistan","Albania","Algeria","Andorra","Angola","Antigua and Barbuda","Argentina","Armenia","Australia","Austria","Azerbaijan","Bahamas","Bahrain","Bangladesh","Barbados","Belarus","Belgium","Belize","Benin","Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","Brunei","Bulgaria","Burkina Faso","Burundi","Cabo Verde","Cambodia","Cameroon","Canada","Central African Republic","Chad","Chile","China","Colombia","Comoros","Congo","Costa Rica","Côte d’Ivoire","Croatia","Cuba","Cyprus","Czechia","Democratic Republic of the Congo","Denmark","Djibouti","Dominica","Dominican Republic","Ecuador","Egypt","El Salvador","Equatorial Guinea","Eritrea","Estonia","Eswatini","Ethiopia","Fiji","Finland","France","Gabon","Gambia","Georgia","Germany","Ghana","Greece","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana","Haiti","Honduras","Hungary","Iceland","India","Indonesia","Iran","Iraq","Ireland","Israel","Italy","Jamaica","Japan","Jordan","Kazakhstan","Kenya","Kiribati","Kuwait","Kyrgyzstan","Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein","Lithuania","Luxembourg","Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands","Mauritania","Mauritius","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Morocco","Mozambique","Myanmar","Namibia","Nauru","Nepal","Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Korea","North Macedonia","Norway","Oman","Pakistan","Palau","Palestine","Panama","Papua New Guinea","Paraguay","Peru","Philippines","Poland","Portugal","Qatar","Romania","Russia","Rwanda","Saint Kitts and Nevis","Saint Lucia","Saint Vincent and the Grenadines","Samoa","San Marino","Sao Tome and Principe","Saudi Arabia","Senegal","Serbia","Seychelles","Sierra Leone","Singapore","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Korea","South Sudan","Spain","Sri Lanka","Sudan","Suriname","Sweden","Switzerland","Syria","Taiwan","Tajikistan","Tanzania","Thailand","Timor-Leste","Togo","Tonga","Trinidad and Tobago","Tunisia","Türkiye","Turkmenistan","Tuvalu","Uganda","Ukraine","United Arab Emirates","United Kingdom","United States","Uruguay","Uzbekistan","Vanuatu","Vatican City","Venezuela","Vietnam","Yemen","Zambia","Zimbabwe"];
countryNames.forEach(name=>{const option=document.createElement("option");option.value=name;option.textContent=name;if(name==="Gambia")option.selected=true;$("regNationality").appendChild(option);});
boot();
applyLanguage();
</script></body></html>'''

@app.get("/")
def index():
    if not app.secret_key or not DATABASE_URL:
        return render_template_string(PAGE), 200
    return render_template_string(PAGE)

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Request is too large."}), 413

@app.errorhandler(500)
def server_error(_):
    app.logger.exception("Unhandled student portal error")
    return jsonify({"error": "A server error occurred. Please try again later."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))