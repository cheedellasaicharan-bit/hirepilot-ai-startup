import os, io, csv, json, re
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func
from docx import Document
from pypdf import PdfReader
from .database import Base, engine, get_db
from .models import User, Job, Candidate, Screening, ScreeningResult
from .security import hash_password, verify_password, make_token, current_user
from .screening import evaluate

Base.metadata.create_all(bind=engine)
app = FastAPI(title="HirePilot AI", version="1.0.0", description="Resume screening and applicant tracking")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
FRONTEND = Path(__file__).resolve().parent.parent / "public"

class RegisterBody(BaseModel):
    name: str
    email: EmailStr
    password: str
class LoginBody(BaseModel):
    email: EmailStr
    password: str
class JobBody(BaseModel):
    title: str
    department: str = ""
    location: str = ""
    description: str
    status: str = "Open"
class StageBody(BaseModel):
    stage: str

@app.get("/health")
def health():
    return {"status": "ok", "service": "hirepilot-ai"}

@app.post("/api/auth/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    email = str(body.email).lower().strip()
    if len(body.password) < 10:
        raise HTTPException(400, "Use a password with at least 10 characters.")
    if not body.name.strip():
        raise HTTPException(400, "Please enter your name.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(name=body.name.strip()[:120], email=email, password_hash=hash_password(body.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"token": make_token(user), "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower().strip()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"token": make_token(user), "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = db.scalar(select(func.count(Job.id)).where(Job.user_id == user.id)) or 0
    candidates = db.scalar(select(func.count(Candidate.id)).where(Candidate.user_id == user.id)) or 0
    screenings = db.scalar(select(func.count(Screening.id)).where(Screening.user_id == user.id)) or 0
    recent = db.scalars(select(Screening).options(joinedload(Screening.job)).where(Screening.user_id == user.id).order_by(Screening.created_at.desc()).limit(5)).unique().all()
    return {"stats": {"jobs": jobs, "candidates": candidates, "screenings": screenings}, "recent": [{"id":s.id,"title":s.title,"job_title":s.job.title if s.job else "Deleted job","created_at":s.created_at.isoformat()} for s in recent]}

@app.get("/api/jobs")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())).all()
    return [job_json(j) for j in rows]

@app.post("/api/jobs")
def create_job(body: JobBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "Job title and description are required.")
    job = Job(user_id=user.id, title=body.title.strip()[:180], department=body.department.strip()[:120], location=body.location.strip()[:180], description=body.description.strip(), status=body.status if body.status in ("Open","Paused","Closed") else "Open")
    db.add(job); db.commit(); db.refresh(job)
    return job_json(job)

def job_json(j):
    return {"id":j.id,"title":j.title,"department":j.department,"location":j.location,"description":j.description,"status":j.status,"created_at":j.created_at.isoformat()}

def extract_resume(filename, data):
    suffix = Path(filename or "").suffix.lower()
    try:
        if suffix == ".txt":
            return data.decode("utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(p.extract_text() or "" for p in reader.pages[:40])
        if suffix == ".docx":
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise HTTPException(400, f"Could not read {filename}: {e}")
    raise HTTPException(400, "Supported formats are PDF, DOCX, and TXT.")

@app.post("/api/candidates/upload")
async def upload_resumes(files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    created = []
    for file in files:
        data = await file.read()
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"{file.filename} exceeds the {MAX_UPLOAD_MB} MB upload limit.")
        text = extract_resume(file.filename or "", data).strip()
        if not text:
            raise HTTPException(400, f"No readable text found in {file.filename}. For scanned PDFs, OCR is not included in this MVP.")
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        name = next((line.strip() for line in text.splitlines() if 2 <= len(line.strip()) <= 90), Path(file.filename or "Candidate").stem)
        c = Candidate(user_id=user.id, name=name[:180], email=email_match.group(0) if email_match else "", filename=(file.filename or "")[:255], resume_text=text[:200000])
        db.add(c); db.flush()
        created.append({"id":c.id,"name":c.name,"email":c.email,"filename":c.filename,"stage":c.stage})
    db.commit()
    return {"uploaded":len(created),"candidates":created}

@app.get("/api/candidates")
def list_candidates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Candidate).where(Candidate.user_id == user.id).order_by(Candidate.created_at.desc())).all()
    return [{"id":c.id,"name":c.name,"email":c.email,"filename":c.filename,"stage":c.stage,"created_at":c.created_at.isoformat()} for c in rows]

@app.patch("/api/candidates/{candidate_id}/stage")
def update_stage(candidate_id: int, body: StageBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allowed = {"New","Reviewing","Shortlisted","Interview","Offer","Hired","Rejected"}
    if body.stage not in allowed:
        raise HTTPException(400, "Invalid candidate stage.")
    c = db.scalar(select(Candidate).where(Candidate.id == candidate_id, Candidate.user_id == user.id))
    if not c: raise HTTPException(404, "Candidate not found.")
    c.stage = body.stage; db.commit()
    return {"ok":True,"id":c.id,"stage":c.stage}

@app.post("/api/screenings")
def create_screening(job_id: int = Form(...), candidate_ids: str = Form(""), db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if not job: raise HTTPException(404, "Job not found.")
    ids = []
    for val in candidate_ids.split(","):
        try: ids.append(int(val))
        except ValueError: pass
    stmt = select(Candidate).where(Candidate.user_id == user.id)
    if ids: stmt = stmt.where(Candidate.id.in_(ids))
    candidates = db.scalars(stmt.order_by(Candidate.created_at.desc())).all()
    if not candidates: raise HTTPException(400, "Upload at least one resume first.")
    screening = Screening(user_id=user.id, job_id=job.id, title=f"{job.title} screening")
    db.add(screening); db.flush()
    results = []
    for c in candidates:
        ev = evaluate(job.description, c.resume_text)
        r = ScreeningResult(screening_id=screening.id,candidate_id=c.id,score=ev["score"],matched=json.dumps(ev["matched"]),missing=json.dumps(ev["missing"]),explanation=ev["explanation"])
        db.add(r)
        results.append({"candidate_id":c.id,"name":c.name,"email":c.email,"filename":c.filename,"stage":c.stage,**ev})
    db.commit()
    results.sort(key=lambda x:x["score"], reverse=True)
    return {"id":screening.id,"title":screening.title,"job":job_json(job),"created_at":screening.created_at.isoformat(),"results":results}

@app.get("/api/screenings")
def list_screenings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Screening).options(joinedload(Screening.job)).where(Screening.user_id == user.id).order_by(Screening.created_at.desc())).unique().all()
    return [{"id":s.id,"title":s.title,"job_title":s.job.title if s.job else "Deleted job","created_at":s.created_at.isoformat(),"candidate_count":len(s.results)} for s in rows]

@app.get("/api/screenings/{screening_id}")
def screening_detail(screening_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.scalar(select(Screening).options(joinedload(Screening.job),joinedload(Screening.results).joinedload(ScreeningResult.candidate)).where(Screening.id==screening_id, Screening.user_id==user.id))
    if not s: raise HTTPException(404, "Screening not found.")
    rows=[]
    for r in s.results:
        rows.append({"candidate_id":r.candidate_id,"name":r.candidate.name,"email":r.candidate.email,"filename":r.candidate.filename,"stage":r.candidate.stage,"score":r.score,"matched":json.loads(r.matched),"missing":json.loads(r.missing),"explanation":r.explanation})
    rows.sort(key=lambda x:x["score"],reverse=True)
    return {"id":s.id,"title":s.title,"job":job_json(s.job),"created_at":s.created_at.isoformat(),"results":rows}

@app.get("/api/screenings/{screening_id}/export.csv")
def export_csv(screening_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.scalar(select(Screening).options(joinedload(Screening.results).joinedload(ScreeningResult.candidate)).where(Screening.id==screening_id, Screening.user_id==user.id))
    if not s: raise HTTPException(404, "Screening not found.")
    out=io.StringIO(); w=csv.writer(out); w.writerow(["Rank","Candidate","Email","Score","Matched keywords","Missing keywords","Stage","Filename"])
    for rank,r in enumerate(sorted(s.results,key=lambda x:x.score,reverse=True),1):
        w.writerow([rank,r.candidate.name,r.candidate.email,r.score,", ".join(json.loads(r.matched)),", ".join(json.loads(r.missing)),r.candidate.stage,r.candidate.filename])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="hirepilot-screening-{screening_id}.csv"'})

@app.get("/api/health")
def api_health():
    return {"status":"ok"}

@app.get("/")
def home():
    return FileResponse(FRONTEND / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
