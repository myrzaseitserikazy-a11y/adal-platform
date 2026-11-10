import os, csv, io, random, hashlib, secrets, hmac
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from jose import jwt, JWTError

DB_URL=os.getenv('DATABASE_URL','sqlite:///./adal.db')
if DB_URL.startswith('postgresql://'): DB_URL=DB_URL.replace('postgresql://','postgresql+psycopg://',1)
engine=create_engine(DB_URL,connect_args={'check_same_thread':False} if DB_URL.startswith('sqlite') else {})
SessionLocal=sessionmaker(bind=engine,autoflush=False)
SECRET=os.getenv('ADAL_SECRET','development-only-change-this-secret')
def hash_password(value:str)->str:
    salt=secrets.token_bytes(16); digest=hashlib.scrypt(value.encode(),salt=salt,n=2**14,r=8,p=1)
    return salt.hex()+'$'+digest.hex()
def verify_password(value:str,stored:str)->bool:
    try:
        salt_hex,digest_hex=stored.split('$',1); digest=hashlib.scrypt(value.encode(),salt=bytes.fromhex(salt_hex),n=2**14,r=8,p=1)
        return hmac.compare_digest(digest.hex(),digest_hex)
    except (ValueError,TypeError): return False
app=FastAPI(title='ADAL API',description='Оқушы білімін әділ бағалау платформасы')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
SYSTEM_EMAIL='adal.system@localhost'

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(100)); email:Mapped[str]=mapped_column(String(250),unique=True,index=True); password:Mapped[str]=mapped_column(String(255)); role:Mapped[str]=mapped_column(String(20)); created:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Assignment(Base):
    __tablename__='assignments'; id:Mapped[int]=mapped_column(primary_key=True); teacher_id:Mapped[int]=mapped_column(ForeignKey('users.id')); title:Mapped[str]=mapped_column(String(200)); description:Mapped[str]=mapped_column(Text); language:Mapped[str]=mapped_column(String(30)); due:Mapped[Optional[str]]=mapped_column(String(40),nullable=True); created:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Submission(Base):
    __tablename__='submissions'; id:Mapped[int]=mapped_column(primary_key=True); assignment_id:Mapped[int]=mapped_column(ForeignKey('assignments.id')); student_id:Mapped[int]=mapped_column(ForeignKey('users.id')); code:Mapped[str]=mapped_column(Text,default=''); answers:Mapped[str]=mapped_column(Text,default=''); updated:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); status:Mapped[str]=mapped_column(String(20),default='draft')
class Version(Base):
    __tablename__='versions'; id:Mapped[int]=mapped_column(primary_key=True); submission_id:Mapped[int]=mapped_column(ForeignKey('submissions.id')); code:Mapped[str]=mapped_column(Text); created:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Grade(Base):
    __tablename__='grades'; id:Mapped[int]=mapped_column(primary_key=True); submission_id:Mapped[int]=mapped_column(ForeignKey('submissions.id'),unique=True); functionality:Mapped[int]=mapped_column(Integer,default=0); explain:Mapped[int]=mapped_column(Integer,default=0); change:Mapped[int]=mapped_column(Integer,default=0); algorithm:Mapped[int]=mapped_column(Integer,default=0); process:Mapped[int]=mapped_column(Integer,default=0); feedback:Mapped[str]=mapped_column(Text,default=''); updated:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
Base.metadata.create_all(engine)
DEFAULT_TASKS=[
    {'title':'Python · Қауіпсіз калькулятор','language':'Python','description':'Екі сан мен амал таңбасын қабылдайтын калькулятор жазыңыз. Қосу, азайту, көбейту және бөлу амалдарын қолдаңыз. Нөлге бөлу мен қате амал таңбасын түсінікті хабарламамен өңдеңіз.\n\nТексеру мысалы: 12, 3, * → 36. Шешіміңізді код астындағы сұрақтарға жауап беріп түсіндіріңіз.'},
    {'title':'Python · Сөздерді санау','language':'Python','description':'Пайдаланушы енгізген сөйлемдегі сөз санын және ең ұзын сөзді табыңыз. Артық бос орындарды дұрыс өңдеңіз. Сөйлем бос болса, қате жібермей хабарлаңыз.\n\nТексеру мысалы: «Мен код жазамын» → 3 сөз. Бос орындары әртүрлі сөйлеммен де тексеріңіз.'},
    {'title':'C++ · Үш санның үлкені','language':'C++','description':'Бүтін үш сан берілген. Ең үлкенін табатын бағдарлама жазыңыз. Сандардың кейбірі тең болуы мүмкін екенін ескеріңіз.\n\nТексеру мысалы: 8, 13, 5 → 13; 7, 7, 2 → 7. Шешімде шарттарды қалай таңдағаныңызды түсіндіріңіз.'},
    {'title':'C++ · Жұп сандар қосындысы','language':'C++','description':'N бүтін сан оқып, массивтегі жұп сандардың қосындысын есептеңіз. Жұп сан болмаса, 0 шығарыңыз.\n\nТексеру мысалы: 5 сан: 2, 7, 4, 1, 6 → 12. Цикл мен қалдық операторын түсіндіріңіз.'},
    {'title':'Java · Баға санаты','language':'Java','description':'0–100 аралығындағы ұпайды қабылдап, санатын шығарыңыз: 90–100 — «Өте жақсы», 70–89 — «Жақсы», 50–69 — «Қанағаттанарлық», 0–49 — «Қайталау қажет». Аралықтан тыс ұпайға қате хабарын көрсетіңіз.\n\nТексеру мысалы: 86 → «Жақсы». Шекаралық мәндерді (49, 50, 89, 90) тексеріңіз.'},
    {'title':'Java · Қайталаусыз элементтер','language':'Java','description':'Бүтін сандар тізімінен қайталанбайтын мәндерді бастапқы ретімен шығарыңыз. Қайталанған элемент тек бір рет көрсетілсін.\n\nТексеру мысалы: 4, 2, 4, 7, 2 → 4, 2, 7. Қолданған коллекцияны және реттілікті неге сақтайтынын түсіндіріңіз.'},
]
def ensure_default_tasks(s:Session):
    system=s.query(User).filter_by(email=SYSTEM_EMAIL).first()
    if not system:
        system=User(name='ADAL тапсырмалар жинағы',email=SYSTEM_EMAIL,password=hash_password(secrets.token_urlsafe(32)),role='teacher');s.add(system);s.flush()
    existing={x[0] for x in s.query(Assignment.title).filter_by(teacher_id=system.id).all()}
    for task in DEFAULT_TASKS:
        if task['title'] not in existing:s.add(Assignment(teacher_id=system.id,title=task['title'],description=task['description'],language=task['language']))
    s.commit()
@app.on_event('startup')
def startup_seed():
    with SessionLocal() as s: ensure_default_tasks(s)
def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()
class Register(BaseModel): name:str=Field(min_length=2,max_length=100); email:EmailStr; password:str=Field(min_length=8); role:str; teacher_code:Optional[str]=None
class Login(BaseModel): email:EmailStr; password:str
class AssignIn(BaseModel): title:str; description:str; language:str; due:Optional[str]=None
class SubmitIn(BaseModel): code:str; answers:list[str]=[]; submit:bool=False
class GradeIn(BaseModel): functionality:int=Field(ge=0,le=30); explain:int=Field(ge=0,le=25); change:int=Field(ge=0,le=20); algorithm:int=Field(ge=0,le=15); process:int=Field(ge=0,le=10); feedback:str=''
def token(u): return jwt.encode({'sub':str(u.id),'exp':datetime.now(timezone.utc)+timedelta(days=7)},SECRET,algorithm='HS256')
def current(authorization:str=Header(default=''),s:Session=Depends(db)):
    try:
        data=jwt.decode(authorization.removeprefix('Bearer ').strip(),SECRET,algorithms=['HS256']); u=s.get(User,int(data['sub']))
        if not u: raise ValueError()
        return u
    except (JWTError,ValueError,KeyError): raise HTTPException(401,'Кіру мерзімі аяқталды')
def role(u,expected):
    if u.role!=expected: raise HTTPException(403,'Бұл бөлімге рұқсат жоқ')
def total(g): return g.functionality+g.explain+g.change+g.algorithm+g.process
def grade_dict(g): return {'functionality':g.functionality,'explain':g.explain,'change':g.change,'algorithm':g.algorithm,'process':g.process,'total':total(g),'feedback':g.feedback}
@app.get('/api/health')
def health(): return {'status':'ok','execution':'disabled_safe_by_default'}
@app.post('/api/register')
def register(x:Register,s:Session=Depends(db)):
    if x.role not in ('student','teacher'): raise HTTPException(400,'Рөл дұрыс емес')
    if x.role=='teacher':
        expected=os.getenv('ADAL_TEACHER_CODE','')
        if not expected or not hmac.compare_digest(x.teacher_code or '',expected): raise HTTPException(403,'Мұғалім тіркелу коды қате немесе бапталмаған')
    if s.query(User).filter_by(email=x.email.lower()).first(): raise HTTPException(409,'Бұл email тіркелген')
    u=User(name=x.name,email=x.email.lower(),password=hash_password(x.password),role=x.role); s.add(u); s.commit(); s.refresh(u)
    return {'token':token(u),'user':{'id':u.id,'name':u.name,'email':u.email,'role':u.role}}
@app.post('/api/login')
def login(x:Login,s:Session=Depends(db)):
    u=s.query(User).filter_by(email=x.email.lower()).first()
    if not u or not verify_password(x.password,u.password): raise HTTPException(401,'Email немесе құпиясөз қате')
    return {'token':token(u),'user':{'id':u.id,'name':u.name,'email':u.email,'role':u.role}}
@app.get('/api/me')
def me(u:User=Depends(current)): return {'id':u.id,'name':u.name,'email':u.email,'role':u.role}
@app.get('/api/assignments')
def assignments(s:Session=Depends(db),u:User=Depends(current)):
    rows=s.query(Assignment).order_by(Assignment.created.desc()).all()
    out=[]
    for a in rows:
        if u.role=='teacher' and a.teacher_id not in (u.id,(s.query(User.id).filter_by(email=SYSTEM_EMAIL).scalar())): continue
        if u.role=='student' and not s.get(User,a.teacher_id): continue
        sub=s.query(Submission).filter_by(assignment_id=a.id,student_id=u.id).first() if u.role=='student' else None
        out.append({'id':a.id,'title':a.title,'description':a.description,'language':a.language,'due':a.due,'submission_id':sub.id if sub else None,'status':sub.status if sub else 'new','grade':grade_dict(s.query(Grade).filter_by(submission_id=sub.id).first()) if sub and s.query(Grade).filter_by(submission_id=sub.id).first() else None})
    return out
@app.post('/api/assignments')
def create_assignment(x:AssignIn,s:Session=Depends(db),u:User=Depends(current)):
    role(u,'teacher')
    if x.language not in ('Python','C++','Java'): raise HTTPException(400,'Тіл қолдау таппайды')
    if not x.title.strip() or not x.description.strip(): raise HTTPException(400,'Тапсырма атауы мен сипаттамасын толтырыңыз')
    a=Assignment(teacher_id=u.id,title=x.title,description=x.description,language=x.language,due=x.due);s.add(a);s.commit();s.refresh(a);return {'id':a.id}
@app.get('/api/submissions')
def submissions(s:Session=Depends(db),u:User=Depends(current)):
    role(u,'teacher'); rows=s.query(Submission).join(Assignment).filter(Assignment.teacher_id==u.id).order_by(Submission.updated.desc()).all();out=[]
    for z in rows:
        a=s.get(Assignment,z.assignment_id); st=s.get(User,z.student_id);g=s.query(Grade).filter_by(submission_id=z.id).first()
        out.append({'id':z.id,'assignment_id':a.id,'assignment':a.title,'student':st.name,'email':st.email,'code':z.code,'answers':z.answers,'status':z.status,'updated':z.updated.isoformat(),'grade':grade_dict(g) if g else None})
    return out
@app.get('/api/submissions/{aid}')
def get_submission(aid:int,s:Session=Depends(db),u:User=Depends(current)):
    if u.role!='student': raise HTTPException(403,'Оқушы аккаунты қажет')
    a=s.get(Assignment,aid)
    if not a: raise HTTPException(404,'Тапсырма табылмады')
    z=s.query(Submission).filter_by(assignment_id=aid,student_id=u.id).first()
    if not z: z=Submission(assignment_id=aid,student_id=u.id);s.add(z);s.commit();s.refresh(z)
    return {'id':z.id,'code':z.code,'answers':__import__('json').loads(z.answers or '[]'),'status':z.status,'versions':s.query(Version).filter_by(submission_id=z.id).count(),'grade':grade_dict(s.query(Grade).filter_by(submission_id=z.id).first()) if s.query(Grade).filter_by(submission_id=z.id).first() else None}
@app.put('/api/submissions/{aid}')
def save_submission(aid:int,x:SubmitIn,s:Session=Depends(db),u:User=Depends(current)):
    if u.role!='student': raise HTTPException(403,'Оқушы аккаунты қажет')
    a=s.get(Assignment,aid)
    if not a: raise HTTPException(404,'Тапсырма табылмады')
    if a.due:
        try:
            deadline=datetime.fromisoformat(a.due).date()
            if datetime.utcnow().date()>deadline: raise HTTPException(400,'Тапсырманы тапсыру мерзімі аяқталды')
        except ValueError: pass
    z=s.query(Submission).filter_by(assignment_id=aid,student_id=u.id).first()
    if not z:z=Submission(assignment_id=aid,student_id=u.id);s.add(z);s.flush()
    if z.status=='submitted' and not x.submit: raise HTTPException(400,'Жіберілген жұмысты өзгерту мүмкін емес')
    z.code=x.code;z.answers=__import__('json').dumps(x.answers,ensure_ascii=False);z.updated=datetime.utcnow();z.status='submitted' if x.submit else 'draft';s.add(Version(submission_id=z.id,code=x.code));s.commit();return {'ok':True,'status':z.status,'versions':s.query(Version).filter_by(submission_id=z.id).count()}
@app.get('/api/submissions/{sid}/history')
def history(sid:int,s:Session=Depends(db),u:User=Depends(current)):
    z=s.get(Submission,sid)
    if not z: raise HTTPException(404,'Жұмыс табылмады')
    a=s.get(Assignment,z.assignment_id)
    if u.id!=z.student_id and not (u.role=='teacher' and a.teacher_id==u.id): raise HTTPException(403,'Рұқсат жоқ')
    return [{'id':v.id,'code':v.code,'created':v.created.isoformat()} for v in s.query(Version).filter_by(submission_id=sid).order_by(Version.created.desc()).limit(30)]
@app.put('/api/submissions/{sid}/grade')
def grade_submission(sid:int,x:GradeIn,s:Session=Depends(db),u:User=Depends(current)):
    role(u,'teacher');z=s.get(Submission,sid)
    if not z or s.get(Assignment,z.assignment_id).teacher_id!=u.id:raise HTTPException(404,'Жұмыс табылмады')
    g=s.query(Grade).filter_by(submission_id=sid).first()
    if not g:g=Grade(submission_id=sid);s.add(g)
    for k,v in x.model_dump().items():setattr(g,k,v)
    g.updated=datetime.utcnow();s.commit();return grade_dict(g)
@app.get('/api/report.csv')
def report(s:Session=Depends(db),u:User=Depends(current)):
    role(u,'teacher'); out=io.StringIO();w=csv.writer(out);w.writerow(['Оқушы','Тапсырма','Мәртебе','Жұмыс','Түсіндіру','Қосымша','Алгоритм','Процесс','Барлығы'])
    for z in s.query(Submission).join(Assignment).filter(Assignment.teacher_id==u.id).all():
        a=s.get(Assignment,z.assignment_id);st=s.get(User,z.student_id);g=s.query(Grade).filter_by(submission_id=z.id).first();w.writerow([st.name,a.title,z.status,g.functionality if g else 0,g.explain if g else 0,g.change if g else 0,g.algorithm if g else 0,g.process if g else 0,total(g) if g else 0])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=adal-report.csv'})

if os.path.isdir('static'):
    app.mount('/',StaticFiles(directory='static',html=True),name='frontend')
