"""Offline daily reports. All day boundaries use UTC+8."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re

BEIJING=timezone(timedelta(hours=8))
VERSION='extract-v1/tfidf-lsa-v1'


def ensure_schema(db):
    if 'occurred' not in {col[1] for col in db.execute('PRAGMA table_info(messages)')}:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if 'occurred' not in {col[1] for col in db.execute('PRAGMA table_info(messages)')}:
                db.execute('ALTER TABLE messages ADD COLUMN occurred INTEGER')
                # Re-read available sources once, keeping prior quotes until their replacement succeeds.
                db.execute("UPDATE sources SET stamp='legacy:'||stamp")
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='chatgpt_files'").fetchone():
                    db.execute("UPDATE chatgpt_files SET stamp='legacy:'||stamp")
    db.executescript("""
        CREATE INDEX IF NOT EXISTS msgs_by_date ON messages(occurred) WHERE occurred IS NOT NULL;
        CREATE TABLE IF NOT EXISTS daily_runs(day TEXT PRIMARY KEY, signature TEXT, built TEXT,
            closed INTEGER, partial INTEGER, coverage TEXT, projects INTEGER, messages INTEGER, vectors INTEGER);
        CREATE TABLE IF NOT EXISTS daily_content(day TEXT PRIMARY KEY, reports TEXT, entries TEXT, matrix BLOB);
        CREATE TABLE IF NOT EXISTS daily_dirty(day TEXT PRIMARY KEY);
        CREATE TRIGGER IF NOT EXISTS daily_insert AFTER INSERT ON messages WHEN NEW.occurred IS NOT NULL BEGIN
            INSERT OR IGNORE INTO daily_dirty SELECT day FROM daily_runs
            WHERE day=date(NEW.occurred/1000,'unixepoch','+8 hours'); END;
        CREATE TRIGGER IF NOT EXISTS daily_delete AFTER DELETE ON messages WHEN OLD.occurred IS NOT NULL BEGIN
            INSERT OR IGNORE INTO daily_dirty SELECT day FROM daily_runs
            WHERE day=date(OLD.occurred/1000,'unixepoch','+8 hours'); END;
        CREATE TRIGGER IF NOT EXISTS daily_relabel AFTER INSERT ON categories BEGIN
            INSERT OR IGNORE INTO daily_dirty SELECT DISTINCT d.day FROM catalog_v5 s
            JOIN messages m ON m.path=s.path JOIN daily_runs d ON d.day=date(m.occurred/1000,'unixepoch','+8 hours')
            WHERE s.framework=NEW.framework AND s.project_key=NEW.project_key; END;
    """)


def group_for(row,infer):
    if row['label']:
        return 'label:'+row['label'], row['label']
    if row['cwd'] and row['label'] is None:
        cwd=row['cwd']
        prefix=chr(92)*2+'?'+chr(92)
        if cwd.startswith(prefix) and re.match(r'^[a-zA-Z]:',cwd[len(prefix):]):cwd=cwd[len(prefix):]
        folder=infer(cwd) or Path(cwd)
        return 'path:'+os.path.normcase(os.path.normpath(str(folder))), str(folder)
    return 'session:'+row['sid'], '项目待确认 · '+(row['title'] or row['sid'])


def salient(body,role):
    if role=='document':
        body=body.lstrip('# \n')
    best={}
    # Only prose enters a digest. Code remains available through the citation and vector index.
    fenced=False
    for line in body.splitlines():
        if line.lstrip().startswith(('```','~~~')):
            fenced=not fenced
            continue
        if fenced:continue
        for part in re.findall(r'[^。！？!?]+[。！？!?]*',line):
            text=part.strip()
            if len(text)<4:continue
            kind='讨论摘录';score=0
            if role=='document':
                kind='导出文件更新'
            elif re.search(r'待办|下一步|尚未|仍需|阻塞|卡在|待验证|失败|未解决|TODO|blocked',text,re.I):
                kind='待处理与问题';score=3
            elif role=='user':
                kind='用户要求与反馈'
                score=3 if re.search(r'决定|确认|需要|保留|采用|改为|必须|希望|同意|不要|只要',text) else 1
            elif re.search(r'验证|通过|实现|完成|修复|结果|测试|采用|已更新|passed|fixed',text,re.I):
                kind='助手报告的进展';score=3
            elif re.search(r'建议|可以|方案|推荐|考虑',text):
                kind='助手建议';score=2
            rank=(score, min(len(text),90), -max(0,len(text)-220))
            if kind not in best or rank>best[kind][0]:
                best[kind]=(rank,kind,text[:220])
    return best.values()


def compose(rows,infer):
    groups={}
    entries=[];texts=[]
    for row in rows:
        key,title=group_for(row,infer)
        group=groups.setdefault(key,dict(project=title,sources=set(),sessions=set(),messages=0,candidates=[]))
        group['sources'].add(row['framework']);group['sessions'].add(row['sid']);group['messages']+=1
        base=dict(project=title,session=row['sid'],title=row['title'],reference=row['ref'],
                  framework=row['framework'],role=row['role'],time=row['occurred'])
        body=row['body']
        for rank,kind,quote in salient(body,row['role']):
            group['candidates'].append((rank,dict(**base,kind=kind,quote=quote,offset=body.find(quote))))
        for start in range(0,len(body),600):
            chunk=body[start:start+680]
            texts.append(chunk)
            entries.append(dict(**base,kind='原文片段',quote=chunk[:180],offset=start))
            if start+680>=len(body):break
    reports=[]
    for g in groups.values():
        candidates=sorted(g.pop('candidates'),key=lambda c:(c[0],c[1]['time']),reverse=True)
        chosen=[];seen=set();buckets=defaultdict(int)
        for limit in (1,2,8):
            for _,item in candidates:
                bucket=(item['kind'],item['framework'])
                if item['quote'] in seen or buckets[bucket]>=limit:continue
                chosen.append(item);seen.add(item['quote']);buckets[bucket]+=1
                if len(chosen)>=8:break
            if len(chosen)>=8:break
        g.update(sources=sorted(g['sources']),sessions=len(g['sessions']),findings=chosen)
        for item in chosen:
            texts.append(item['quote'])
            entries.append(dict(item,kind='日报摘录'))
        reports.append(g)
    return sorted(reports,key=lambda g:-g['messages']),entries,texts


def features(texts,tokenize):
    from sklearn.feature_extraction.text import HashingVectorizer
    return HashingVectorizer(n_features=4096,analyzer=tokenize,alternate_sign=False,norm=None).transform(texts).tocsr()


def encode(texts,tokenize):
    import numpy as np
    from sklearn.preprocessing import normalize
    from sklearn.decomposition import TruncatedSVD
    from threadpoolctl import threadpool_limits
    x=features(texts,tokenize)
    idf=np.log((1+x.shape[0])/(1+np.asarray((x>0).sum(axis=0)).ravel()))+1
    x.data=1+np.log(x.data)
    x=normalize(x.multiply(idf).tocsr()).astype('float32')
    k=min(48,len(texts)-1,int((x.getnnz(axis=0)>0).sum())-1)
    basis=np.empty((0,x.shape[1]),dtype='float32')
    latent=np.empty((len(texts),0),dtype='float32')
    if k>=2:
        with threadpool_limits(limits=1):
            svd=TruncatedSVD(n_components=k,random_state=0,n_iter=4)
            latent=normalize(svd.fit_transform(x));basis=svd.components_
    out=BytesIO()
    np.savez_compressed(out,values=x.data,indices=x.indices,indptr=x.indptr,idf=idf.astype('float32'),basis=basis,latent=latent)
    return out.getvalue()


def day_data(db,day):
    start=datetime.combine(date.fromisoformat(day),datetime.min.time(),BEIJING)
    bounds=(int(start.timestamp()*1000),int((start+timedelta(days=1)).timestamp()*1000))
    return db.execute("""SELECT s.sid,s.title,s.framework,s.cwd,c.label,m.ref,m.role,m.body,m.occurred
        FROM messages m JOIN catalog_v5 s ON s.path=m.path
        LEFT JOIN categories c ON c.framework=s.framework AND c.project_key=s.project_key
        WHERE m.occurred>=? AND m.occurred<? AND m.role!='metadata'
        ORDER BY m.occurred,s.sid,m.id""",bounds).fetchall()


def build_day(db,day,now,coverage,partial,infer,tokenize):
    with db:
        db.execute('BEGIN IMMEDIATE')
        rows=day_data(db,day)
        digest=sha256(VERSION.encode())
        for row in rows:
            digest.update(json.dumps([row['framework'],row['sid'],row['role'],row['ref'],row['occurred'],row['title'],group_for(row,infer)],ensure_ascii=False).encode())
        signature=digest.hexdigest()
        old=db.execute('SELECT signature FROM daily_runs WHERE day=?',(day,)).fetchone()
        closed=day<now.date().isoformat()
        encoded_coverage=json.dumps(coverage,ensure_ascii=False)
        if old and old[0]==signature:
            db.execute('UPDATE daily_runs SET closed=?,partial=?,coverage=?,built=? WHERE day=?',
                       (closed,partial,encoded_coverage,now.isoformat(),day))
        else:
            reports,entries,texts=compose(rows,infer)
            matrix=encode(texts,tokenize) if texts else b''
            db.execute('INSERT OR REPLACE INTO daily_content VALUES(?,?,?,?)',(day,json.dumps(reports,ensure_ascii=False),
                       json.dumps(entries,ensure_ascii=False),matrix))
            db.execute('INSERT OR REPLACE INTO daily_runs VALUES(?,?,?,?,?,?,?,?,?)',(day,signature,now.isoformat(),
                       closed,partial,encoded_coverage,len(reports),len(rows),len(entries)))
        db.execute('DELETE FROM daily_dirty WHERE day=?',(day,))


def run_due(db,root,refresh,infer,tokenize,now=None,hour=23):
    now=(now or datetime.now(BEIJING)).astimezone(BEIJING)
    today=now.date();yesterday=today-timedelta(days=1)
    last=db.execute('SELECT max(day) FROM daily_runs WHERE closed=1').fetchone()[0]
    day=min(date.fromisoformat(last)+timedelta(days=1),yesterday) if last else yesterday
    days={r[0] for r in db.execute('SELECT day FROM daily_dirty UNION SELECT day FROM daily_runs WHERE partial=1 OR closed=0')}
    while day<=yesterday:
        days.add(day.isoformat());day+=timedelta(days=1)
    if now.hour>=hour:days.add(today.isoformat())
    coverage=refresh(db,root)
    days.update(r[0] for r in db.execute('SELECT day FROM daily_dirty'))
    partial=bool(coverage.get('unreadable_files') or any('失败' in str(v) for v in coverage.values()))
    for key in sorted(days):
        if key<=today.isoformat():build_day(db,key,now,coverage,partial,infer,tokenize)
    return dict(days=len(days),partial=partial)


def list_reports(db):
    days=[dict(r) for r in db.execute('SELECT day,built,closed,partial,projects,messages,vectors FROM daily_runs ORDER BY day DESC')]
    row=db.execute("SELECT json_extract(payload,'$.undated') FROM summary_snapshot WHERE id=1").fetchone()
    undated=row[0] if row else None
    return dict(days=days,undated=undated)


def read_report(db,day):
    r=db.execute('SELECT reports,coverage FROM daily_content JOIN daily_runs USING(day) WHERE day=?',(day,)).fetchone()
    if not r:raise ValueError('该日期的日报尚未生成')
    return dict(reports=json.loads(r[0]),coverage=json.loads(r[1]))


def vector_search(db,query,tokenize,day=None,groups=None,sort="relevance"):
    import numpy as np
    from scipy.sparse import csr_matrix
    from sklearn.preprocessing import normalize
    if not query.strip():return {'hits':[]}
    expanded=" ".join(word for group in (groups or {}).values() for word in group)
    q=features([query+" "+query+" "+expanded],tokenize)
    q.data=1+np.log(q.data)
    hits=[]
    for r in db.execute('SELECT day,entries,matrix FROM daily_content WHERE length(matrix)>0 AND (? IS NULL OR day=?)',(day,day)):
        entries=json.loads(r[1])
        with np.load(BytesIO(r[2]),allow_pickle=False) as z:
            query_vec=normalize(q.multiply(z['idf']).tocsr())
            x=csr_matrix((z['values'],z['indices'],z['indptr']),shape=(len(entries),len(z['idf'])))
            scores=(x @ query_vec.T).toarray().ravel()
            basis=z['basis']
            if basis.size:
                latent=(z['latent'] @ normalize(query_vec @ basis.T).T).ravel()
                scores=.6*scores+.4*latent
        seen=set()
        for i in np.argsort(-scores):
            if scores[i]<0.075:break
            if sort=='relevance' and len(seen)>=10:break
            e=entries[i];key=(e['session'],e['reference'])
            if key in seen:continue
            seen.add(key);hits.append(dict(e,day=r[0],score=round(float(scores[i]),4)))
    if sort=='relevance':hits.sort(key=lambda h:-h['score'])
    elif sort in ('newest','oldest'):hits.sort(key=lambda h:(h['time'] if sort=='oldest' else -h['time'],-h['score']))
    else:raise ValueError('无效的排序')
    return dict(hits=hits[:10])


def read_evidence(db,sid,reference):
    row=db.execute("""SELECT m.id,m.body,m.role,m.occurred,s.path,s.framework,s.title FROM messages m
        JOIN catalog_v5 s ON s.path=m.path WHERE s.sid=? AND m.ref=? AND m.role!='metadata'""",(sid,reference)).fetchone()
    if not row:return {'missing':True}
    def neighbor(previous):
        op,order=('<','DESC') if previous else ('>','ASC')
        r=db.execute(f"SELECT role,body FROM messages WHERE path=? AND role!='metadata' AND id{op}? ORDER BY id {order} LIMIT 1",
                     (row['path'],row['id'])).fetchone()
        return dict(role=r[0],text=r[1][:450]) if r else None
    return dict(text=row['body'],role=row['role'],time=row['occurred'],framework=row['framework'],title=row['title'],
                previous=neighbor(True),following=neighbor(False))

