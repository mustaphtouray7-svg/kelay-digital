import os
import secrets
from datetime import datetime, timezone
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from flask import Flask, request, session, jsonify, render_template_string, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=600 * 1024,
)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SCHOOL_NAME = "Alh. Lalo Kanteh Islamic Institute"
SETUP_KEY = os.environ.get("PORTAL_SETUP_KEY", "")
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
                surname VARCHAR(120) NOT NULL DEFAULT '',
                arabic_name VARCHAR(200) NOT NULL DEFAULT '',
                phone VARCHAR(40) NOT NULL DEFAULT '',
                email VARCHAR(254) NOT NULL UNIQUE,
                student_id VARCHAR(40) UNIQUE,
                password_hash TEXT NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'student' CHECK (role IN ('student','admin')),
                status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
                class_name VARCHAR(80) NOT NULL DEFAULT '',
                grade VARCHAR(80) NOT NULL DEFAULT '',
                date_of_birth DATE,
                profile_image TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                approved_at TIMESTAMPTZ
            )
        """)
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS profile_image TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS father_name VARCHAR(120) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS surname VARCHAR(120) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS arabic_name VARCHAR(200) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS phone VARCHAR(40) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS grade VARCHAR(80) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS gender VARCHAR(20) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS nationality VARCHAR(100) NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS date_of_birth DATE")
        conn.execute("CREATE INDEX IF NOT EXISTS portal_users_status_idx ON portal_users(status)")
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

def user_public(row):
    return {k: row.get(k) for k in ("id", "full_name", "father_name", "surname", "arabic_name", "phone", "email", "student_id", "role", "status", "class_name", "grade", "date_of_birth", "profile_image", "gender", "nationality", "created_at")}

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
    name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or "@" not in email or len(password) < 12:
        return jsonify({"error": "Enter a name, valid email, and password of at least 12 characters."}), 400
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

def valid_profile_image(value):
    if not isinstance(value, str) or not value:
        return False
    if not (value.startswith("data:image/jpeg;base64,") or value.startswith("data:image/png;base64,")):
        return False
    return len(value) <= 400_000

@app.post("/api/register")
def register():
    if DEMO_MODE or not REGISTRATION_OPEN:
        return jsonify({"error": "This is a demonstration portal. Student registration will open only after the school officially approves the website."}), 403
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    name = str(data.get("full_name", "")).strip()
    father_name = str(data.get("father_name", "")).strip()
    surname = str(data.get("surname", "")).strip()
    phone = str(data.get("phone", "")).strip()
    date_of_birth = str(data.get("date_of_birth", "")).strip()
    class_name = str(data.get("class_name", "")).strip()
    gender = str(data.get("gender", "")).strip()
    nationality = str(data.get("nationality", "")).strip()
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    profile_image = str(data.get("profile_image", ""))
    if not valid_profile_image(profile_image):
        return jsonify({"error": "Upload a profile picture (JPEG or PNG)."}), 400
    if not all([name, father_name, surname, phone, date_of_birth, class_name, gender, nationality]):
        return jsonify({"error": "Complete your name, father's name, surname, date of birth, class, and phone number."}), 400
    if len(name) > 120 or len(father_name) > 120 or len(surname) > 120 or len(phone) > 40 or len(class_name) > 80:
        return jsonify({"error": "One or more fields are too long."}), 400
    if password != password_confirm:
        return jsonify({"error": "Passwords do not match."}), 400
    if len(password) < 12:
        return jsonify({"error": "Use a password with at least 12 characters."}), 400
    try:
        dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        if dob >= datetime.now().date():
            return jsonify({"error": "Enter a valid date of birth."}), 400
    except ValueError:
        return jsonify({"error": "Enter a valid date of birth."}), 400
    email = "student-" + "".join(ch for ch in phone if ch.isdigit()) + "@students.lalokanteh.local"
    try:
        with db() as conn:
            duplicate = conn.execute("SELECT id FROM portal_users WHERE phone=%s AND role='student' LIMIT 1", (phone,)).fetchone()
            if duplicate:
                return jsonify({"error": "This phone number already has a student account. Contact the school."}), 409
            row = conn.execute(
                "INSERT INTO portal_users(full_name,father_name,surname,phone,email,password_hash,status,class_name,date_of_birth,profile_image,gender,nationality) VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s) RETURNING id",
                (name, father_name, surname, phone, email, generate_password_hash(password), class_name, dob, profile_image, gender, nationality)
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
    login_value = str(data.get("login", data.get("email", ""))).strip()
    password = str(data.get("password", ""))
    with db() as conn:
        row = conn.execute("SELECT * FROM portal_users WHERE lower(email)=lower(%s) OR phone=%s ORDER BY CASE WHEN phone=%s THEN 0 ELSE 1 END LIMIT 1", (login_value, login_value, login_value)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Phone number or password is incorrect."}), 401
    if row["status"] != "approved":
        return jsonify({"error": "Your account is " + row["status"] + ". Please contact the school if you need help."}), 403
    session.clear()
    session["user_id"], session["role"], session["full_name"] = row["id"], row["role"], row["full_name"]
    session.permanent = True
    csrf_token()
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
    if len(password) < 12:
        return jsonify({"error": "Temporary password must be at least 12 characters."}), 400
    try:
        with db() as conn:
            row = conn.execute(
                "INSERT INTO portal_users(full_name,father_name,surname,arabic_name,phone,email,student_id,password_hash,status,class_name,grade,approved_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,%s,NOW()) RETURNING *",
                (name, father_name, surname, arabic_name, phone, email, student_id, generate_password_hash(password), class_name, grade)
            ).fetchone()
            conn.commit()
        return jsonify({"student": user_public(row)}), 201
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "That email or student ID is already in use."}), 409

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
.eyebrow{font-size:12px;letter-spacing:.16em;font-weight:700;color:#e8d5bd}.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.12;margin:12px 0}.hero p{max-width:650px;color:#f4e9dd}
.layout{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:18px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 8px 28px #5a3d2b0b}
h2{margin:0 0 8px;font-size:23px}h3{margin:0 0 12px}label{display:block;font-weight:700;font-size:13px;margin:12px 0 5px}
input,select{width:100%;padding:12px;border:1px solid #d8c7b2;border-radius:9px;font:inherit;background:#fff}button,.button{border:0;border-radius:10px;background:var(--brown);color:white;padding:12px 16px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;margin-top:14px}
button.secondary{background:var(--sand);color:var(--brown)}button:disabled{opacity:.5;cursor:wait}.muted{color:var(--muted);font-size:14px}.notice{padding:12px 14px;border-radius:10px;background:var(--sand);margin:12px 0}.error{background:#fff0ed;color:#7d2619}.success{background:#edf7ed;color:#23572b}
.hidden{display:none!important}.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.student{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.pill{font-size:12px;font-weight:700;background:var(--sand);color:var(--brown);padding:4px 8px;border-radius:999px}.tiny{font-size:12px;color:var(--muted)}
footer{text-align:center;padding:24px;color:var(--muted);border-top:1px solid var(--line)}a{color:var(--brown)}
</style></head><body>
<header><a class="brand" href="/">ALH. LALO KANTEH ISLAMIC INSTITUTE<small>TABOKOTO · THE GAMBIA</small></a><div class="header-actions"><a href="https://kelay-digital.onrender.com/school-demo/" class="tiny" data-i18n="School website ↗">School website ↗</a><button type="button" id="languageToggle" class="secondary language-toggle" aria-label="Switch language">العربية</button></div></header>
<main><section class="hero"><div class="eyebrow">STUDENT AREA</div><h1>Student Portal</h1><p>Access your student account, or request registration. Student accounts created by self-registration must be approved by the school.</p></section>
<div id="notice" class="notice hidden" role="status"></div>
<section id="setup" class="card hidden" style="margin-bottom:18px"><h2>First-time administrator setup</h2><p class="muted">Use this one-time setup only when the school is ready to appoint its first portal administrator. You need the private setup key configured by the site owner.</p><form id="setupForm"><label for="setupName">Administrator full name</label><input id="setupName" required maxlength="120" autocomplete="name"><label for="setupEmail">Administrator email</label><input id="setupEmail" type="email" required maxlength="254" autocomplete="email"><label for="setupPassword">Strong password (at least 12 characters)</label><input id="setupPassword" type="password" required minlength="12" autocomplete="new-password"><label for="setupKey">One-time setup key</label><input id="setupKey" type="password" required autocomplete="off"><button type="submit">Create first administrator</button></form><p class="tiny">Do not share the setup key. Once the first administrator exists, this setup endpoint cannot create another first administrator.</p></section>
<section id="auth" class="layout">
<div class="card"><h2>Sign in</h2><p class="muted">Use your approved school account.</p>
<form id="loginForm"><label for="loginEmail">Phone number or administrator email</label><input id="loginEmail" autocomplete="username" required maxlength="254"><label for="loginPassword">Password</label><input id="loginPassword" type="password" autocomplete="current-password" required><button type="submit">Sign in</button></form></div>
<div class="card"><h2>Student registration</h2><p class="muted">Register using your school details. The school must approve your account before you can sign in.</p><form id="registerForm"><label for="regName">First name</label><input id="regName" required maxlength="120"><label for="regFather">Father's name</label><input id="regFather" required maxlength="120"><label for="regSurname">Surname</label><input id="regSurname" required maxlength="120"><label for="regDob">Date of birth</label><input id="regDob" type="date" required><label for="regClass">Current class</label><select id="regClass" required><option value="">Select class</option><option>Nursery 1</option><option>Nursery 2</option><option>Grade 1</option><option>Grade 2</option><option>Grade 3</option><option>Grade 4</option><option>Grade 5</option><option>Grade 6</option><option>Grade 7</option><option>Grade 8</option><option>Grade 9</option><option>Grade 10</option><option>Grade 11</option><option>Grade 12</option></select>
<label for="regGender">Gender</label><select id="regGender" required><option value="">Select gender</option><option value="Male">Male</option><option value="Female">Female</option></select>
<label for="regNationality">Nationality</label><select id="regNationality" required><option value="">Select nationality</option></select><label for="regPhone">Phone number</label><input id="regPhone" type="tel" required maxlength="40" autocomplete="tel"><label for="regPhoto">Profile picture (required)</label><input id="regPhoto" type="file" accept="image/*" required><p class="tiny">JPEG or PNG, up to 5 MB before automatic resizing.</p><img id="photoPreview" class="hidden" alt="Profile picture preview" style="width:96px;height:96px;object-fit:cover;border-radius:50%;margin-top:8px;border:2px solid var(--line)"><label for="regPassword">Create password (12 characters minimum)</label><input id="regPassword" type="password" minlength="12" autocomplete="new-password" required><label for="regPasswordConfirm">Confirm password</label><input id="regPasswordConfirm" type="password" minlength="12" autocomplete="new-password" required><button type="submit">Submit registration</button></form></div>
</section>
<section id="dashboard" class="hidden"><div class="card"><div class="bar"><div><p class="eyebrow" style="color:var(--brown)">YOUR ACCOUNT</p><h2 id="welcome">Welcome</h2></div><button class="secondary" id="logout">Sign out</button></div><div id="profile"></div></div>
<div id="adminPanel" class="hidden">
<div class="card" style="margin-top:18px"><h2>Pending and approved students</h2><p class="muted">Approve self-registrations or reject accounts. Only approved students can sign in.</p><div id="studentList">Loading student records…</div></div>
<div class="card" style="margin-top:18px"><h2>Create a student account</h2><form id="createStudent"><label for="newName">First name</label><input id="newName" required maxlength="120"><label for="newFather">Father name</label><input id="newFather" required maxlength="120"><label for="newSurname">Surname</label><input id="newSurname" required maxlength="120"><label for="newArabic">Full name in Arabic</label><input id="newArabic" required maxlength="200" dir="rtl"><label for="newPhone">Phone number</label><input id="newPhone" type="tel" required maxlength="40"><label for="newEmail">Email</label><input id="newEmail" type="email" required maxlength="254"><label for="newId">Student ID</label><input id="newId" maxlength="40"><label for="newClass">Class</label><input id="newClass" required maxlength="80"><label for="newGrade">Grade</label><input id="newGrade" required maxlength="80"><label for="newPassword">Temporary password (12 characters minimum)</label><input id="newPassword" type="password" minlength="12" required><button type="submit">Create approved account</button></form></div></div>
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
"Student registration":"تسجيل الطلاب","Register using your school details. The school must approve your account before you can sign in.":"سجّل باستخدام بياناتك المدرسية. يجب أن توافق المدرسة على حسابك قبل تسجيل الدخول.",
"First name":"الاسم الأول","Father's name":"اسم الأب","Father name":"اسم الأب","Surname":"اسم العائلة","Date of birth":"تاريخ الميلاد","Current class":"الفصل الحالي","Gender":"الجنس","Select gender":"اختر الجنس","Nationality":"الجنسية","Select nationality":"اختر الجنسية","Select class":"اختر الصف","Phone number":"رقم الهاتف","Profile picture (required)":"الصورة الشخصية (مطلوبة)","JPEG or PNG, up to 5 MB before automatic resizing.":"صورة JPEG أو PNG، حتى 5 ميغابايت قبل تغيير الحجم تلقائيًا.",
"Create password (12 characters minimum)":"إنشاء كلمة مرور (12 حرفًا على الأقل)","Confirm password":"تأكيد كلمة المرور","Submit registration":"إرسال طلب التسجيل",
"YOUR ACCOUNT":"حسابك","Welcome":"مرحبًا","Sign out":"تسجيل الخروج","Pending and approved students":"الطلاب قيد الانتظار والطلاب المعتمدون",
"Approve self-registrations or reject accounts. Only approved students can sign in.":"وافق على طلبات التسجيل الذاتي أو ارفض الحسابات. يمكن للطلاب المعتمدين فقط تسجيل الدخول.",
"Loading student records…":"جارٍ تحميل سجلات الطلاب…","Create a student account":"إنشاء حساب طالب","Full name in Arabic":"الاسم الكامل باللغة العربية","Email":"البريد الإلكتروني","Student ID":"رقم الطالب","Class":"الفصل","Grade":"الصف الدراسي","Temporary password (12 characters minimum)":"كلمة مرور مؤقتة (12 حرفًا على الأقل)","Create approved account":"إنشاء حساب معتمد",
"Alh. Lalo Kanteh Islamic Institute · Tabokoto, The Gambia":"معهد الحاج لالو كانتي الإسلامي · تبوكتو، غامبيا",
"Not assigned":"غير محدد","Account status:":"حالة الحساب:","Exam results and attendance can be added when the school provides verified records.":"يمكن إضافة نتائج الامتحانات والحضور عندما توفر المدرسة سجلات موثقة.",
"No student accounts yet.":"لا توجد حسابات طلاب حتى الآن.","No photo":"لا توجد صورة","No student ID":"لا يوجد رقم طالب","No class":"لا يوجد فصل","Approve":"اعتماد","Reject":"رفض",
"Sign in successfully.":"تم تسجيل الدخول بنجاح.","Student status updated.":"تم تحديث حالة الطالب.","Student account created and approved.":"تم إنشاء حساب الطالب واعتماده.",
"Passwords do not match.":"كلمتا المرور غير متطابقتين.","Choose a JPEG or PNG profile picture.":"اختر صورة شخصية بصيغة JPEG أو PNG.","Choose a picture smaller than 5 MB.":"اختر صورة أصغر من 5 ميغابايت.","Could not read that picture.":"تعذرت قراءة الصورة.","That picture could not be opened.":"تعذر فتح الصورة.",
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
function showNotice(message, kind="notice"){const n=$("notice");n.textContent=message;n.className=kind;}
async function api(path, data, method="POST"){const res=await fetch(path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:method==="GET"?undefined:JSON.stringify(data||{})});const body=await res.json().catch(()=>({error:"Unexpected server response."}));if(body.csrf_token)csrf=body.csrf_token;if(!res.ok)throw new Error(body.error||"Request failed.");return body;}
function toggle(id,on){$(id).classList.toggle("hidden",!on);}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
async function loadCsrf(){const r=await fetch("/api/csrf");const d=await r.json();if(!r.ok)throw new Error(d.error||"Portal is not configured yet.");csrf=d.csrf_token;}
async function imageToDataUrl(file){if(!file)throw new Error("Choose a profile picture first.");if(!file.type.startsWith("image/"))throw new Error("Choose an image file such as JPG, PNG, or WebP.");if(file.size>5*1024*1024)throw new Error("Choose a picture smaller than 5 MB.");const src=URL.createObjectURL(file);try{const img=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(new Error("This photo format cannot be opened. Please save it as JPG or PNG and try again."));i.src=src;});const scale=Math.min(1,320/Math.max(img.width,img.height));const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(img.width*scale));canvas.height=Math.max(1,Math.round(img.height*scale));const ctx=canvas.getContext("2d");if(!ctx)throw new Error("Photo processing is unavailable in this browser. Try Chrome or Firefox.");ctx.drawImage(img,0,0,canvas.width,canvas.height);return canvas.toDataURL("image/jpeg",0.68);}finally{URL.revokeObjectURL(src);}}
$("regPhoto").addEventListener("change",async()=>{try{if($("regPhoto").files[0]){$("photoPreview").src=await imageToDataUrl($("regPhoto").files[0]);toggle("photoPreview",true);}}catch(e){toggle("photoPreview",false);showNotice(e.message,"error");}});
function renderProfile(u){$("welcome").textContent="Welcome, "+u.full_name;$("profile").innerHTML=(u.profile_image?'<img src="'+u.profile_image+'" alt="Student profile picture" style="width:100px;height:100px;object-fit:cover;border-radius:50%;border:2px solid var(--line)">':"")+'<p><strong>Email:</strong> '+esc(u.email)+'</p><p><strong>Student ID:</strong> '+esc(u.student_id||"Not assigned")+'</p><p><strong>Class:</strong> '+esc(u.class_name||"Not assigned")+'</p><p><strong>Account status:</strong> <span class="pill">'+esc(u.status)+'</span></p><p class="muted">Exam results and attendance can be added when the school provides verified records.</p>';}
async function refreshStudents(){const d=await api("/api/admin/students",null,"GET");const list=$("studentList");if(!d.students.length){list.textContent="No student accounts yet.";return;}list.innerHTML=d.students.map(s=>'<div class="student"><div>'+(s.profile_image?'<img src="'+s.profile_image+'" alt="Student profile" style="width:58px;height:58px;object-fit:cover;border-radius:50%;vertical-align:middle;margin-right:10px">':'<span class="pill">No photo</span>')+'<strong>'+esc(s.full_name)+'</strong><div class="tiny">'+esc(s.father_name)+' '+esc(s.surname)+' · '+esc(s.arabic_name)+' · '+esc(s.phone)+' · '+esc(s.grade)+' · '+esc(s.email)+' · '+esc(s.student_id||"No student ID")+' · '+esc(s.class_name||"No class")+'</div><span class="pill">'+esc(s.status)+'</span></div><div>'+ (s.status!=="approved"?'<button data-id="'+s.id+'" data-status="approved">Approve</button> ':"")+(s.status!=="rejected"?'<button class="secondary" data-id="'+s.id+'" data-status="rejected">Reject</button>':"")+'</div></div>').join("");list.querySelectorAll("button[data-id]").forEach(b=>b.addEventListener("click",async()=>{try{await api("/api/admin/students/"+b.dataset.id+"/status",{status:b.dataset.status});showNotice("Student status updated.","success");await refreshStudents();}catch(e){showNotice(e.message,"error");}}));}
async function showUser(u){toggle("auth",false);toggle("setup",false);toggle("dashboard",true);renderProfile(u);const admin=u.role==="admin";toggle("adminPanel",admin);if(admin)await refreshStudents();}
async function boot(){try{await loadCsrf();const sr=await fetch("/api/setup-status");const sd=await sr.json();const r=await fetch("/api/me");if(r.ok){const d=await r.json();await showUser(d.user);}else if(!sd.database_ready){throw new Error("The student database is not ready. Please contact the website administrator.");}else if(sd.setup_needed){toggle("auth",false);toggle("setup",true);}else{toggle("setup",false);toggle("auth",true);}}catch(e){toggle("setup",false);toggle("auth",true);showNotice("Portal setup is not complete yet. "+e.message,"error");}}
$("setupForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/setup-admin",{setup_key:$("setupKey").value,full_name:$("setupName").value,email:$("setupEmail").value,password:$("setupPassword").value});e.target.reset();toggle("setup",false);await showUser(d.user);showNotice("First administrator account created successfully.","success");}catch(err){showNotice(err.message,"error");}});
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/login",{login:$("loginEmail").value,password:$("loginPassword").value});await showUser(d.user);showNotice("Signed in successfully.","success");}catch(err){showNotice(err.message,"error");}});
$("registerForm").addEventListener("submit",async e=>{e.preventDefault();try{const photo=await imageToDataUrl($("regPhoto").files[0]);if($("regPassword").value!==$("regPasswordConfirm").value)throw new Error("Passwords do not match.");const d=await api("/api/register",{full_name:$("regName").value,father_name:$("regFather").value,surname:$("regSurname").value,date_of_birth:$("regDob").value,phone:$("regPhone").value,class_name:$("regClass").value,gender:$("regGender").value,nationality:$("regNationality").value,password:$("regPassword").value,password_confirm:$("regPasswordConfirm").value,profile_image:photo});e.target.reset();toggle("photoPreview",false);showNotice(d.message,"success");}catch(err){showNotice(err.message,"error");}});
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
