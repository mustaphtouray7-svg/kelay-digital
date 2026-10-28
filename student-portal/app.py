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
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SCHOOL_NAME = "Alh. Lalo Kanteh Islamic Institute"
SETUP_KEY = os.environ.get("PORTAL_SETUP_KEY", "")

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
                email VARCHAR(254) NOT NULL UNIQUE,
                student_id VARCHAR(40) UNIQUE,
                password_hash TEXT NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'student' CHECK (role IN ('student','admin')),
                status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
                class_name VARCHAR(80) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                approved_at TIMESTAMPTZ
            )
        """)
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
    return {k: row.get(k) for k in ("id", "full_name", "email", "student_id", "role", "status", "class_name", "created_at")}

@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return jsonify({"status": "ok"})
    except Exception:
        return jsonify({"status": "database_not_ready"}), 503

@app.get("/api/setup-status")
def setup_status():
    try:
        with db() as conn:
            exists = conn.execute("SELECT id FROM portal_users WHERE role='admin' LIMIT 1").fetchone()
        return jsonify({"setup_needed": not bool(exists)})
    except Exception:
        return jsonify({"setup_needed": True, "database_ready": False})

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

@app.post("/api/register")
def register():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    student_id = str(data.get("student_id", "")).strip() or None
    if len(name) < 2 or len(name) > 120 or "@" not in email or len(email) > 254:
        return jsonify({"error": "Enter your full name and a valid email address."}), 400
    if len(password) < 12:
        return jsonify({"error": "Use a password with at least 12 characters."}), 400
    try:
        with db() as conn:
            row = conn.execute(
                "INSERT INTO portal_users(full_name,email,student_id,password_hash,status) VALUES (%s,%s,%s,%s,'pending') RETURNING id",
                (name, email, student_id, generate_password_hash(password))
            ).fetchone()
            conn.commit()
        return jsonify({"message": "Registration submitted. The school must approve your account before you can sign in.", "id": row["id"]}), 201
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "That email or student ID is already registered. Contact the school if you need help."}), 409

@app.post("/api/login")
def login():
    if not verify_csrf():
        return jsonify({"error": "Refresh the page and try again."}), 400
    data = request.json or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with db() as conn:
        row = conn.execute("SELECT * FROM portal_users WHERE email=%s", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 401
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
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    student_id = str(data.get("student_id", "")).strip() or None
    class_name = str(data.get("class_name", "")).strip()
    if len(name) < 2 or "@" not in email:
        return jsonify({"error": "Enter a full name and valid email."}), 400
    if len(password) < 12:
        return jsonify({"error": "Temporary password must be at least 12 characters."}), 400
    try:
        with db() as conn:
            row = conn.execute(
                "INSERT INTO portal_users(full_name,email,student_id,password_hash,status,class_name,approved_at) VALUES (%s,%s,%s,%s,'approved',%s,NOW()) RETURNING *",
                (name, email, student_id, generate_password_hash(password), class_name)
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
header{background:#fff;border-bottom:1px solid var(--line);padding:16px 5%;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{font-weight:800;color:var(--brown);text-decoration:none;letter-spacing:.02em}.brand small{display:block;color:var(--muted);font-size:11px;letter-spacing:.1em}
main{max-width:1100px;margin:0 auto;padding:36px 18px 60px}.hero{background:var(--brown);color:white;border-radius:22px;padding:clamp(24px,5vw,52px);margin-bottom:24px}
.eyebrow{font-size:12px;letter-spacing:.16em;font-weight:700;color:#e8d5bd}.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.12;margin:12px 0}.hero p{max-width:650px;color:#f4e9dd}
.layout{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:18px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 8px 28px #5a3d2b0b}
h2{margin:0 0 8px;font-size:23px}h3{margin:0 0 12px}label{display:block;font-weight:700;font-size:13px;margin:12px 0 5px}
input,select{width:100%;padding:12px;border:1px solid #d8c7b2;border-radius:9px;font:inherit;background:#fff}button,.button{border:0;border-radius:10px;background:var(--brown);color:white;padding:12px 16px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;margin-top:14px}
button.secondary{background:var(--sand);color:var(--brown)}button:disabled{opacity:.5;cursor:wait}.muted{color:var(--muted);font-size:14px}.notice{padding:12px 14px;border-radius:10px;background:var(--sand);margin:12px 0}.error{background:#fff0ed;color:#7d2619}.success{background:#edf7ed;color:#23572b}
.hidden{display:none!important}.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.student{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.pill{font-size:12px;font-weight:700;background:var(--sand);color:var(--brown);padding:4px 8px;border-radius:999px}.tiny{font-size:12px;color:var(--muted)}
footer{text-align:center;padding:24px;color:var(--muted);border-top:1px solid var(--line)}a{color:var(--brown)}
</style></head><body>
<header><a class="brand" href="/">ALH. LALO KANTEH ISLAMIC INSTITUTE<small>TABOKOTO · THE GAMBIA</small></a><a href="https://kelay-digital.onrender.com/school-demo/" class="tiny">School website ↗</a></header>
<main><section class="hero"><div class="eyebrow">STUDENT AREA</div><h1>Student Portal</h1><p>Access your student account, or request registration. Student accounts created by self-registration must be approved by the school.</p></section>
<div id="notice" class="notice hidden" role="status"></div>
<section id="auth" class="layout">
<div class="card"><h2>Sign in</h2><p class="muted">Use your approved school account.</p>
<form id="loginForm"><label for="loginEmail">Email</label><input id="loginEmail" type="email" autocomplete="username" required maxlength="254"><label for="loginPassword">Password</label><input id="loginPassword" type="password" autocomplete="current-password" required><button type="submit">Sign in</button></form></div>
<div class="card"><h2>Request an account</h2><p class="muted">The school must approve your registration before you can sign in.</p>
<form id="registerForm"><label for="regName">Full name</label><input id="regName" required maxlength="120"><label for="regEmail">Email</label><input id="regEmail" type="email" required maxlength="254"><label for="regStudentId">Student ID (if known)</label><input id="regStudentId" maxlength="40"><label for="regPassword">Password (12 characters minimum)</label><input id="regPassword" type="password" minlength="12" autocomplete="new-password" required><button type="submit">Submit registration</button></form></div>
</section>
<section id="dashboard" class="hidden"><div class="card"><div class="bar"><div><p class="eyebrow" style="color:var(--brown)">YOUR ACCOUNT</p><h2 id="welcome">Welcome</h2></div><button class="secondary" id="logout">Sign out</button></div><div id="profile"></div></div>
<div id="adminPanel" class="hidden">
<div class="card" style="margin-top:18px"><h2>Pending and approved students</h2><p class="muted">Approve self-registrations or reject accounts. Only approved students can sign in.</p><div id="studentList">Loading student records…</div></div>
<div class="card" style="margin-top:18px"><h2>Create a student account</h2><form id="createStudent"><label for="newName">Full name</label><input id="newName" required maxlength="120"><label for="newEmail">Email</label><input id="newEmail" type="email" required maxlength="254"><label for="newId">Student ID</label><input id="newId" maxlength="40"><label for="newClass">Class</label><input id="newClass" maxlength="80"><label for="newPassword">Temporary password (12 characters minimum)</label><input id="newPassword" type="password" minlength="12" required><button type="submit">Create approved account</button></form></div></div>
</section>
<section id="setup" class="card hidden" style="margin-top:18px"><h2>First-time administrator setup</h2><p class="muted">Use the one-time setup key provided by the school website administrator. Create a strong password and keep it private.</p>
<form id="setupForm"><label for="setupKey">Setup key</label><input id="setupKey" type="password" required autocomplete="off"><label for="adminName">Administrator full name</label><input id="adminName" required maxlength="120"><label for="adminEmail">Administrator email</label><input id="adminEmail" type="email" required maxlength="254"><label for="adminPassword">Password (12 characters minimum)</label><input id="adminPassword" type="password" minlength="12" required autocomplete="new-password"><button type="submit">Create administrator account</button></form></section>
</main><footer>Alh. Lalo Kanteh Islamic Institute · Tabokoto, The Gambia</footer>
<script>
let csrf = "";
const $ = id => document.getElementById(id);
function showNotice(message, kind="notice"){const n=$("notice");n.textContent=message;n.className=kind;}
async function api(path, data, method="POST"){const res=await fetch(path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:method==="GET"?undefined:JSON.stringify(data||{})});const body=await res.json().catch(()=>({error:"Unexpected server response."}));if(body.csrf_token)csrf=body.csrf_token;if(!res.ok)throw new Error(body.error||"Request failed.");return body;}
function toggle(id,on){$(id).classList.toggle("hidden",!on);}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
async function loadCsrf(){const r=await fetch("/api/csrf");const d=await r.json();if(!r.ok)throw new Error(d.error||"Portal is not configured yet.");csrf=d.csrf_token;}
function renderProfile(u){$("welcome").textContent="Welcome, "+u.full_name;$("profile").innerHTML='<p><strong>Email:</strong> '+esc(u.email)+'</p><p><strong>Student ID:</strong> '+esc(u.student_id||"Not assigned")+'</p><p><strong>Class:</strong> '+esc(u.class_name||"Not assigned")+'</p><p><strong>Account status:</strong> <span class="pill">'+esc(u.status)+'</span></p><p class="muted">Exam results and attendance can be added when the school provides verified records.</p>';}
async function refreshStudents(){const d=await api("/api/admin/students",null,"GET");const list=$("studentList");if(!d.students.length){list.textContent="No student accounts yet.";return;}list.innerHTML=d.students.map(s=>'<div class="student"><div><strong>'+esc(s.full_name)+'</strong><div class="tiny">'+esc(s.email)+' · '+esc(s.student_id||"No student ID")+' · '+esc(s.class_name||"No class")+'</div><span class="pill">'+esc(s.status)+'</span></div><div>'+ (s.status!=="approved"?'<button data-id="'+s.id+'" data-status="approved">Approve</button> ':"")+(s.status!=="rejected"?'<button class="secondary" data-id="'+s.id+'" data-status="rejected">Reject</button>':"")+'</div></div>').join("");list.querySelectorAll("button[data-id]").forEach(b=>b.addEventListener("click",async()=>{try{await api("/api/admin/students/"+b.dataset.id+"/status",{status:b.dataset.status});showNotice("Student status updated.","success");await refreshStudents();}catch(e){showNotice(e.message,"error");}}));}
async function showUser(u){toggle("auth",false);toggle("setup",false);toggle("dashboard",true);renderProfile(u);const admin=u.role==="admin";toggle("adminPanel",admin);if(admin)await refreshStudents();}
async function boot(){try{await loadCsrf();const sr=await fetch("/api/setup-status");const sd=await sr.json();if(sd.setup_needed){toggle("setup",true);}const r=await fetch("/api/me");if(r.ok){const d=await r.json();await showUser(d.user);}else{toggle("auth",true);}}catch(e){toggle("auth",true);showNotice("Portal setup is not complete yet. Please contact the website administrator. "+e.message,"error");}}
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/login",{email:$("loginEmail").value,password:$("loginPassword").value});await showUser(d.user);showNotice("Signed in successfully.","success");}catch(err){showNotice(err.message,"error");}});
$("registerForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/register",{full_name:$("regName").value,email:$("regEmail").value,student_id:$("regStudentId").value,password:$("regPassword").value});e.target.reset();showNotice(d.message,"success");}catch(err){showNotice(err.message,"error");}});
$("logout").addEventListener("click",async()=>{try{await api("/api/logout",{});location.reload();}catch(e){showNotice(e.message,"error");}});
$("createStudent").addEventListener("submit",async e=>{e.preventDefault();try{await api("/api/admin/create-student",{full_name:$("newName").value,email:$("newEmail").value,student_id:$("newId").value,class_name:$("newClass").value,password:$("newPassword").value});e.target.reset();showNotice("Student account created and approved.","success");await refreshStudents();}catch(err){showNotice(err.message,"error");}});
$("setupForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await api("/api/setup-admin",{setup_key:$("setupKey").value,full_name:$("adminName").value,email:$("adminEmail").value,password:$("adminPassword").value});await showUser(d.user);showNotice("Administrator account created. Save your login details securely.","success");}catch(err){showNotice(err.message,"error");}});
boot();
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
