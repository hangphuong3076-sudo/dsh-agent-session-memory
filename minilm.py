"""Offline MiniLM retrieval; model assets are provisioned separately."""
from functools import lru_cache
import os
from pathlib import Path
import re

from fetch_minilm import FILES, checksum


def store():
    return Path(os.getenv('AGENT_MEMORY_DIR') or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AgentSessionMemory')


def model_folder():
    return Path(os.getenv('AGENT_MEMORY_MODEL_DIR') or Path.home()/'.dsh/storages/agent-session-memory/models/minilm-l12-q8')


@lru_cache(maxsize=1)
def encoder(folder):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    for name,expected in FILES.items():
        if checksum(folder/Path(name).name)!=expected:
            raise ValueError('模型文件校验失败，请重新运行 install-minilm.ps1')
    tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
    tokenizer.enable_truncation(max_length=128)
    padding=tokenizer.padding or {}
    pad=padding.get('pad_token') or ('[PAD]' if tokenizer.token_to_id('[PAD]') is not None else '<pad>')
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id(pad),pad_token=pad)
    options=ort.SessionOptions()
    options.intra_op_num_threads=min(4,os.cpu_count() or 1)
    options.inter_op_num_threads=1
    session=ort.InferenceSession(str(folder/'model_quantized.onnx'),options,providers=['CPUExecutionProvider'])
    return tokenizer,session


def embed(texts):
    import numpy as np
    tokenizer,session=encoder(model_folder())
    tokens=tokenizer.encode_batch(texts)
    mask=np.asarray([t.attention_mask for t in tokens],dtype=np.int64)
    inputs={'input_ids':np.asarray([t.ids for t in tokens],dtype=np.int64),'attention_mask':mask}
    if any(i.name=='token_type_ids' for i in session.get_inputs()):
        inputs['token_type_ids']=np.asarray([t.type_ids for t in tokens],dtype=np.int64)
    hidden=session.run(None,inputs)[0]
    pooled=(hidden*mask[:,:,None].astype('float32')).sum(axis=1)/mask.sum(axis=1)[:,None]
    normal=pooled/np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12)
    if normal.shape!=(len(texts),384) or not np.isfinite(normal).all():
        raise ValueError('MiniLM 输出维度或数值异常')
    return normal.astype('<f4')


@lru_cache(maxsize=1)
def splitter(folder):
    from tokenizers import Tokenizer
    tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    return tokenizer


def chunks(text):
    # Use original character offsets, not decoded tokens: punctuation, emoji and repeated quotes must round-trip.
    tokenizer=splitter(model_folder())
    tokens=tokenizer.encode(text,add_special_tokens=False).offsets
    if not tokens:
        if text.strip():yield 0,text
        return
    i=0
    while i<len(tokens):
        end=min(i+120,len(tokens))
        if end<len(tokens):
            for j in range(end,i+72,-1):
                if re.search(r'[。！？.!?;；\n]',text[tokens[j-1][0]:tokens[j][0]]):
                    end=j
                    break
        start=tokens[i][0] if i else 0
        stop=tokens[end][0] if end<len(tokens) else len(text)
        quote=text[start:stop]
        # Starting mid-word can change tokenization. Ensure each independently encoded slice fits.
        while len(tokenizer.encode(quote,add_special_tokens=False).ids)>126:
            end-=1
            stop=tokens[end][0]
            quote=text[start:stop]
        if quote.strip():yield start,quote
        if end==len(tokens):break
        i=max(i+1,end-16)


def passages(db,source):
    title=(source['title'] or '').strip()[:180]
    if title:
        for pos,quote in chunks(title):yield '', 'title',0,pos,quote
    rows=db.execute("SELECT ref,role,body FROM messages WHERE path=? AND role IN ('user','assistant','document') ORDER BY id",(source['path'],))
    for turn,(ref,role,body) in enumerate(rows,1):
        if body and body.strip():
            for pos,quote in chunks(body):yield ref,role,turn,pos,quote


def schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS full_sources(path TEXT PRIMARY KEY,stamp TEXT,segments INTEGER);
        CREATE TABLE IF NOT EXISTS full_passages(path TEXT,slot INTEGER,ref TEXT,role TEXT,turn INTEGER,pos INTEGER,vid INTEGER,PRIMARY KEY(path,slot));
        CREATE INDEX IF NOT EXISTS full_by_vector ON full_passages(vid);
        CREATE TABLE IF NOT EXISTS full_vectors(id INTEGER PRIMARY KEY,quote TEXT UNIQUE NOT NULL,vector BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS minilm_choices(chat TEXT PRIMARY KEY,hits TEXT);
    """)


def indexed(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='full_sources'").fetchone()


def coverage(db):
    count,segments=db.execute('SELECT count(*),coalesce(sum(i.segments),0) FROM full_sources i JOIN sources s ON i.path=s.path AND i.stamp=s.stamp').fetchone() if indexed(db) else (0,0)
    return dict(indexed=count,segments=segments,total=db.execute('SELECT count(*) FROM catalog_v5').fetchone()[0])


def build(db):
    if not (model_folder()/'model_quantized.onnx').is_file():
        return {'error':'未部署本地模型'}
    schema(db)
    sources=db.execute("""SELECT s.path,s.title,s.stamp FROM catalog_v5 s LEFT JOIN full_sources i USING(path)
        WHERE i.stamp IS NOT s.stamp OR i.path IS NULL ORDER BY s.updated DESC""").fetchall()
    encoded=0
    for source in sources:
        parts=list(passages(db,source))
        quotes=dict.fromkeys(p[-1] for p in parts)
        fresh=[]
        for q in quotes:
            row=db.execute('SELECT id FROM full_vectors WHERE quote=?',(q,)).fetchone()
            if row:quotes[q]=row[0]
            else:fresh.append(q)
        for i in range(0,len(fresh),16):
            batch=fresh[i:i+16]
            vectors=embed(batch)
            with db:
                for q,v in zip(batch,vectors):
                    db.execute('INSERT OR IGNORE INTO full_vectors(quote,vector) VALUES(?,?)',(q,v.tobytes()))
                    quotes[q]=db.execute('SELECT id FROM full_vectors WHERE quote=?',(q,)).fetchone()[0]
            encoded+=len(batch)
        with db:
            db.execute('DELETE FROM full_passages WHERE path=?',(source['path'],))
            db.executemany('INSERT INTO full_passages VALUES(?,?,?,?,?,?,?)',
                           ((source['path'],slot,ref,role,turn,pos,quotes[q]) for slot,(ref,role,turn,pos,q) in enumerate(parts)))
            db.execute('INSERT OR REPLACE INTO full_sources VALUES(?,?,?)',(source['path'],source['stamp'],len(parts)))
    with db:
        db.execute('DELETE FROM full_sources WHERE path NOT IN (SELECT path FROM sources)')
        db.execute('DELETE FROM full_passages WHERE path NOT IN (SELECT path FROM full_sources)')
        db.execute('DELETE FROM full_vectors WHERE NOT EXISTS (SELECT 1 FROM full_passages WHERE vid=full_vectors.id)')
    return dict(coverage(db),updated=len(sources),encoded=encoded)


def segments(db,sid,offset,query=''):
    if type(offset) is not int or offset<0:raise ValueError('无效的分段位置')
    if not indexed(db):return dict(total=0,hits=[])
    source=db.execute('SELECT i.path,i.segments FROM full_sources i JOIN sources s ON s.path=i.path AND s.stamp=i.stamp WHERE s.sid=?',(sid,)).fetchone()
    if not source:return dict(total=0,hits=[])
    fields='p.slot,p.ref AS reference,p.role,p.turn,p.pos AS offset,v.quote'
    sql=f'SELECT {fields} FROM full_passages p JOIN full_vectors v ON v.id=p.vid WHERE p.path=?'
    args=(source[0],offset)
    error=''
    if query:
        try:
            import numpy as np
            vec=embed([query])[0]
            db.create_function('segment_score',1,lambda blob:float(np.dot(np.frombuffer(blob,dtype='<f4'),vec)))
        except Exception as exc:
            query=''
            error=f'模型不可用，按原文顺序展示：{exc}'
    if query:sql+=' ORDER BY segment_score(v.vector) DESC,p.slot LIMIT 12 OFFSET ?'
    else:sql+=' AND p.slot>=? ORDER BY p.slot LIMIT 12'
    return dict(total=source[1],hits=[dict(r) for r in db.execute(sql,args)],error=error)


def retrieve(db,query,chat):
    if not indexed(db):return {},'尚未建立全文分段索引'
    if not (model_folder()/'model_quantized.onnx').is_file():return {},'未找到本地模型'
    import numpy as np
    query_vec=embed([query])[0]
    ids=[];values=[]
    rows=db.execute('SELECT id,vector FROM full_vectors ORDER BY id')
    while batch:=rows.fetchmany(1024):
        matrix=np.frombuffer(b''.join(r[1] for r in batch),dtype='<f4').reshape(-1,384)
        ids.extend(r[0] for r in batch)
        values.append(np.einsum('ij,j->i',matrix,query_vec))
    if not values:return {},'尚无已编码片段'
    scores=np.concatenate(values)
    best={}
    floor=.35
    for n in np.argsort(-scores,kind='stable'):
        score=float(scores[n])
        if score<floor:break
        rows=db.execute("""SELECT p.path,p.slot,p.ref,p.role,p.turn,p.pos,v.quote FROM full_passages p
            JOIN full_vectors v ON v.id=p.vid JOIN full_sources i ON i.path=p.path
            JOIN sources s ON s.path=i.path AND s.stamp=i.stamp WHERE p.vid=? AND s.sid<>?
            ORDER BY (p.ref=''),p.slot""",(ids[n],chat))
        for path,slot,ref,role,turn,pos,quote in rows:
            if path not in best:
                best[path]=dict(score=score,reference=ref,role=role,turn=turn,slot=slot,offset=pos,quote=quote)
                floor=max(floor,score-.16)
            if len(best)>=60:return best,''
    return best,''


def optional(action,*args):
    try:return action(*args)
    except Exception as exc:
        # Embedding is optional; surface its failure without breaking keyword search or reports.
        reason=f'{type(exc).__name__}: {exc}'[:200]
        return ({},reason) if action is retrieve else {'error':reason}




