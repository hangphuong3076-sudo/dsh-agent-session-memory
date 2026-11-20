"""Local DeepSeek Harness desktop session retrieval. Payload and replies are UTF-8 JSON."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from datetime import datetime, timedelta
from session_search import ranked, concepts, locations
import minilm
import zstandard
from nightly import BEIJING, ensure_schema, run_due, list_reports, read_report, vector_search, read_evidence
from comparison import compare
from archives import names, register, sync_folders
from extra_sources import DETECTED
from native_sources import sync_native
from origins import FRAMEWORKS, sync_zcode, import_chatgpt


def terms(text):
    result = []
    for word in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.casefold()):
        if "\u3400" <= word[0] <= "\u9fff" and len(word) > 1:
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            result.append(word)
    return result


def short(text, size, offset=0):
    start = max(0, min(offset - size // 4, len(text) - size))
    return text[start:start + size]


def blocks(content):
    if isinstance(content, str):
        return [(0, content)]
    return [(i, part["text"]) for i, part in enumerate(content or [])
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")]


def ref(seq, block, value):
    return f"{seq}.{block}.{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def read_session(path):
    meta, rows, operations = {}, [], []
    calls = {}
    with contextlib.ExitStack() as stack:
        binary = stack.enter_context(path.open("rb"))
        if path.suffix == ".zstd":
            binary = stack.enter_context(zstandard.ZstdDecompressor().stream_reader(binary))
        reader = stack.enter_context(io.TextIOWrapper(binary, encoding="utf-8"))
        for line_no, line in enumerate(reader, 1):
            if not line.strip():
                continue
            # DSH runtime and reasoning events can be very large.
            if not any(f'"{typ}"' in line[:240] for typ in
                       ("session", "session/title", "user/message", "assistant/message",
                        "tool/call", "tool/result")):
                continue
            event = json.loads(line)
            kind, data = event.get("type"), event.get("data") or {}
            seq, when = event.get("seq", line_no), event.get("time", 0)
            if kind == "session":
                meta = {**data, **{k: v for k, v in event.items() if k != "data"}}
                if meta.get("delegationDepth", 0) > 0:
                    return {}, [], []
            elif kind == "session/title":
                meta["title"] = data.get("title") or ""
            elif kind in ("user/message", "assistant/message"):
                role = kind.split("/")[0]
                if role == "user" and (data.get("source") or {}).get("kind") != "user":
                    continue
                content = data.get("content") if role == "user" else (data.get("message") or {}).get("content")
                for idx, value in blocks(content):
                    rows.append(dict(reference=ref(seq, idx, value), role=role, text=value, time=when))
            elif kind == "tool/call":
                args = data.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                target = next((args.get(k) for k in ("path", "file_path", "filePath", "command")
                               if isinstance(args, dict) and isinstance(args.get(k), str)), "")
                calls[data.get("callId")] = (data.get("name"), target[:240])
            elif kind == "tool/result":
                msg = data.get("message") or {}
                tool, target = calls.get(msg.get("toolCallId") or data.get("callId"), (None, ""))
                if tool and not tool.startswith("memory_"):
                    operations.append(dict(tool=tool, target=target, time=when,
                                           reported_error=bool(data.get("error") or msg.get("isError"))))
    return meta, rows, operations


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=120)
    db.row_factory = sqlite3.Row
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='summary_snapshot'").fetchone():
        return db
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY,stamp TEXT,sid TEXT,cwd TEXT,title TEXT,updated INTEGER);
    CREATE INDEX IF NOT EXISTS src_id ON sources(sid);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,path TEXT,ref TEXT,role TEXT,body TEXT);
    CREATE INDEX IF NOT EXISTS msg_path ON messages(path);
    CREATE VIRTUAL TABLE IF NOT EXISTS idx USING fts5(words);
    CREATE TABLE IF NOT EXISTS categories(framework TEXT, project_key TEXT,label TEXT,PRIMARY KEY(framework,project_key));
    CREATE TABLE IF NOT EXISTS archive_folders(folder TEXT PRIMARY KEY COLLATE NOCASE,source TEXT,label TEXT);
    CREATE VIEW IF NOT EXISTS catalog_v5 AS SELECT *,
        CASE WHEN instr(path,'+md://')>0 THEN substr(path,1,instr(path,'+md://')-1) WHEN instr(path,'://')>0 THEN substr(path,1,instr(path,'://')-1) ELSE 'dsh' END AS framework,
        CASE WHEN cwd IS NULL OR cwd='' THEN sid ELSE cwd END AS project_key
        FROM sources WHERE sid IS NOT NULL AND EXISTS(SELECT 1 FROM messages WHERE path=sources.path AND role!='metadata');
    CREATE TABLE IF NOT EXISTS latest_comparison(slot INTEGER PRIMARY KEY, a TEXT,b TEXT,query TEXT);
    CREATE TABLE IF NOT EXISTS choices(chat TEXT PRIMARY KEY, ids TEXT, selected TEXT, query TEXT);
    """)
    ensure_schema(db)
    db.execute("CREATE TABLE IF NOT EXISTS summary_snapshot(id INTEGER PRIMARY KEY,payload TEXT,night TEXT)")
    return db


def files(root):
    selected = {}
    for path in root.glob("*/*/session*.jsonl*"):
        match = re.fullmatch(r"session(?:\.v(\d+))?\.jsonl(\.zstd)?", path.name)
        if match:
            rank = (int(match[1] or 0), bool(match[2]))
            prev = selected.get(path.parent)
            if not prev or rank > prev[0]:
                selected[path.parent] = (rank, path)
    return {str(path) for _, path in selected.values()}


def clear_source(db, path):
    db.execute("DELETE FROM idx WHERE rowid IN (SELECT id FROM messages WHERE path=?)", (path,))
    db.execute("DELETE FROM messages WHERE path=?", (path,))
    db.execute("DELETE FROM sources WHERE path=?", (path,))


def refresh(db, root):
    known = dict(db.execute("SELECT path,stamp FROM sources WHERE instr(path,'://')=0"))
    paths = files(root)
    failed = 0
    with db:
        for path in (known.keys() - paths if root.is_dir() else ()):
            clear_source(db, path)
    for name in sorted(paths):
        path = Path(name)
        try:
            stat = path.stat()
            stamp = f"{stat.st_mtime_ns}:{stat.st_size}"
            if known.get(name) == stamp:
                continue
            meta, rows, _ = read_session(path)
            if not meta.get("id") and rows:
                raise ValueError("missing session header")
            title = meta.get("title") or next((r["text"][:100] for r in rows if r["role"] == "user"), "")
            cwd = str(meta.get("cwd") or "")
            with db:
                clear_source(db, name)
                db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                           (name, stamp, meta.get("id"), cwd, title, max((r["time"] or 0 for r in rows), default=0)))
                for r in rows:
                    rowid = db.execute("INSERT INTO messages(path,ref,role,body,occurred) VALUES(?,?,?,?,?)",
                                       (name,r["reference"],r["role"],r["text"],r["time"] or None)).lastrowid
                    db.execute("INSERT INTO idx(rowid,words) VALUES(?,?)", (rowid," ".join(terms(r["text"]))))
                if rows:
                    rowid = db.execute("INSERT INTO messages(path,ref,role,body) VALUES(?,?,?,?)",
                                       (name,"","metadata",title+" "+cwd)).lastrowid
                    db.execute("INSERT INTO idx(rowid,words) VALUES(?,?)",(rowid," ".join(terms(title+" "+cwd))))
        except (OSError, ValueError, UnicodeError, zstandard.ZstdError):
            failed += 1
    coverage={"files": len(paths), "unreadable_files": failed,
            "dsh": "已连接" if root.is_dir() else "未发现本地目录",
            "zcode": sync_zcode(db,store_external,clear_source),
            **sync_native(db,store_external,clear_source)}
    sync_folders(db,coverage,store_external)
    return coverage


def ranked_sessions(db, chat, q, limit=5, sort='relevance', offset=0):
    return ranked(db,chat,q,limit,names(db),terms,sort,offset)


def search(db, chat, q, limit=5, sort="relevance"):
    result=ranked_sessions(db,chat,q,limit,sort)
    ids=[c["session"] for c in result["candidates"]]
    with db:
        db.execute("INSERT OR REPLACE INTO choices VALUES(?,?,NULL,?)",(chat,json.dumps(ids),q))
        if minilm.indexed(db):
            hits={c['session']:c['semantic'] for c in result['candidates'] if c.get('semantic',{}).get('reference')}
            db.execute('INSERT OR REPLACE INTO minilm_choices VALUES(?,?)',(chat,json.dumps(hits,ensure_ascii=False)))
    return result


def compare_choices(db,chat,first,second):
    state=db.execute('SELECT ids,query FROM choices WHERE chat=?',(chat,)).fetchone()
    if not state:raise ValueError('请先按关键词列出候选会话')
    ids=json.loads(state['ids'])
    if any(type(n) is not int or not 1<=n<=len(ids) for n in (first,second)) or first==second:
        raise ValueError('请选择本次候选中的两个不同序号')
    a,b=ids[first-1],ids[second-1]
    result=compare(db,a,b,state['query'],terms,project_root_finder())
    with db:
        db.execute('INSERT OR REPLACE INTO latest_comparison VALUES(1,?,?,?)',(a,b,state['query']))
    return result


def selection(db, chat, args):
    state = db.execute("SELECT * FROM choices WHERE chat=?", (chat,)).fetchone()
    if not state:
        raise ValueError("请先在本聊天中搜索，再按候选序号选择。")
    ids = json.loads(state["ids"])
    if args["op"] == "select":
        n = args["number"]
        if type(n) is not int or not 1 <= n <= len(ids):
            raise ValueError("请选择本次结果中的序号。")
        sid = ids[n-1]
    else:
        sid = state["selected"]
        if not sid:
            raise ValueError("请先选择一个会话。")
    source = db.execute("SELECT * FROM catalog_v5 WHERE sid=?", (sid,)).fetchone()
    if not source:
        raise ValueError("选中会话已不可用，请重新搜索。")
    if source["framework"] != "dsh":
        rows=[dict(reference=r["ref"],role=r["role"],text=r["body"]) for r in db.execute(
            "SELECT ref,role,body FROM messages WHERE path=? AND role!='metadata' ORDER BY id",(source["path"],))]
        meta,operations={"id":sid},[]
    else:
        meta, rows, operations = read_session(Path(source["path"]))
    if meta.get("id") != sid:
        raise ValueError("来源已经变化，请重新搜索。")
    if args["op"] == "quote":
        index = next((i for i,r in enumerate(rows) if r["reference"]==args["reference"]),None)
        if index is None:
            raise ValueError("未在选中会话找到一致的原话；原消息可能已变更。")
        target = rows[index]
        offset = args.get("offset",0)
        if type(offset) is not int or not 0 <= offset <= len(target["text"]):
            raise ValueError("原文偏移无效。")
        return dict(session=sid,framework=names(db)[source["framework"]],project=source["cwd"],role=target["role"],reference=target["reference"],
                    quote=target["text"][offset:offset+3000],offset=offset,total_chars=len(target["text"]),
                    nearby=[dict(role=r["role"],reference=r["reference"],quote=r["text"][:350])
                            for r in rows[max(0,index-1):index]+rows[index+1:index+2]])
    with db:
        db.execute("UPDATE choices SET selected=? WHERE chat=?", (sid,chat))
    words = set(terms(state["query"]))
    matched = sorted(range(len(rows)),key=lambda i:len(words.intersection(terms(rows[i]["text"]))),reverse=True)[:3]
    keep = sorted(set(matched + list(range(max(0,len(rows)-5),len(rows))) + ([0] if rows else [])))
    evidence = []
    for i in keep:
        row = rows[i]
        pos = next((row["text"].casefold().find(w) for w in terms(state["query"]) if w in row["text"].casefold()),0)
        evidence.append(dict(role=row["role"],reference=row["reference"],quote=short(row["text"],650,pos)))
    if minilm.indexed(db):
        saved=db.execute('SELECT hits FROM minilm_choices WHERE chat=?',(chat,)).fetchone()
        hit=json.loads(saved[0]).get(sid) if saved else None
        if hit and any(r['reference']==hit['reference'] and r['text'].startswith(hit['quote'],hit['offset']) for r in rows):
            evidence.insert(0,dict(hit,kind='语义相关原段'))
    return dict(session=sid,framework=names(db)[source["framework"]],project=source["cwd"],title=source["title"],evidence=evidence,
                recent_operations=operations[-8:],guidance=("在选中项目下核对现有文件与未完成事项，然后按用户要求继续开发。" if source["cwd"] else "来源未提供工作目录。继续开发前请用户指定项目路径。"))


def store_external(db,path,stamp,sid,cwd,title,updated,rows):
    with db:
        clear_source(db,path)
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",(path,stamp,sid,cwd,title,updated))
        messages=[(ref(row[0],0,row[2]),row[1],row[2],(row[3] or None) if len(row)>3 else (updated if row[1]=='document' else None)) for row in rows]
        if rows:
            messages.append(('', 'metadata', title+' '+cwd,None))
        for reference,role,body,occurred in messages:
            mid=db.execute("INSERT INTO messages(path,ref,role,body,occurred) VALUES(?,?,?,?,?)",
                           (path,reference,role,body,occurred)).lastrowid
            db.execute("INSERT INTO idx(rowid,words) VALUES(?,?)",(mid,' '.join(terms(body))))


def project_root_finder():
    # Cache shared parent directories for this overview. Re-evaluate markers on refresh.
    from functools import lru_cache
    @lru_cache(None)
    def find(folder):
        if folder.parent==folder or str(folder).startswith('\\\\'):
            return ''
        if any((folder/m).exists() for m in ('.git','pyproject.toml','package.json','Cargo.toml')):
            return folder
        return find(folder.parent)
    return lambda cwd: find(Path(cwd)) if cwd and Path(cwd).is_absolute() else ''


def overview(db, coverage, find_roots=True):
    rows=db.execute("""SELECT framework, project_key, cwd, max(title) AS title, count(*) AS sessions,
        max(updated) AS updated FROM catalog_v5 GROUP BY framework,project_key ORDER BY updated DESC,project_key""")
    projects=[]
    labels={(r[0],r[1]):r[2] for r in db.execute("SELECT framework,project_key,label FROM categories")}
    infer=project_root_finder()
    for row in rows:
        project=dict(row)
        key=(row['framework'],row['project_key'])
        label=labels.get(key)
        project['method']='手动归类' if label else '目录归类'
        if label is None:
            repo=infer(row['cwd']) if find_roots else None
            label=repo.name if repo else ''
            if not label and row['cwd'] and Path(row['cwd']).is_absolute():
                label=Path(row['cwd']).name
                project['method']='工作目录归类'
        project['category']=label
        if not label:
            project['method']='未归类'
        projects.append(project)
    return dict(projects=projects,sessions=sum(p['sessions'] for p in projects),coverage=coverage,
                frameworks={**FRAMEWORKS,**dict(db.execute('SELECT source,label FROM archive_folders'))}, detected={key:name for key,(name,_,_) in DETECTED.items() if key in coverage})


def project_sessions(db, project, offset, framework='dsh'):
    if type(offset) is not int or offset<0:
        raise ValueError("无效的分页位置")
    rows=db.execute("""SELECT sid,title,updated,
        (SELECT substr(body,1,360) FROM messages WHERE path=s.path AND role='user' ORDER BY id DESC LIMIT 1) AS request,
        (SELECT substr(body,1,360) FROM messages WHERE path=s.path AND role='assistant' ORDER BY id DESC LIMIT 1) AS reply
        FROM catalog_v5 s WHERE project_key=? AND framework=?
        ORDER BY updated DESC,sid LIMIT 13 OFFSET ?""",(project,framework,offset))
    sessions=[dict(row) for row in rows]
    return dict(sessions=sessions[:12],more=len(sessions)>12)


def set_category(db,args):
    key=(args['framework'],args['project'])
    if not db.execute("SELECT 1 FROM catalog_v5 WHERE framework=? AND project_key=? LIMIT 1",key).fetchone():
        raise ValueError('项目不存在，请刷新')
    label=args['label']
    if not isinstance(label,str) or len(label.strip())>80:
        raise ValueError('请使用 80 字以内的分类名称')
    with db:
        db.execute("INSERT OR REPLACE INTO categories VALUES(?,?,?)",(*key,label.strip()))
        row=db.execute('SELECT payload FROM summary_snapshot WHERE id=1').fetchone()
        if row:
            snapshot=json.loads(row[0])
            for p in snapshot['projects']:
                if (p['framework'],p['project_key'])==key:
                    p.update(category=label.strip(),method='手动归类' if label.strip() else '未归类')
            db.execute('UPDATE summary_snapshot SET payload=? WHERE id=1',(json.dumps(snapshot,ensure_ascii=False),))
    return {'saved':True}


def transcript(db,sid,offset):
    from markdown_it import MarkdownIt
    if type(offset) is not int or offset<0:
        raise ValueError('无效页码')
    source=db.execute("SELECT * FROM catalog_v5 WHERE sid=?",(sid,)).fetchone()
    if not source:
        raise ValueError('会话已移除，请返回列表刷新')
    md=MarkdownIt('commonmark',{'html':False,'linkify':False}).enable('table').disable('image')
    rows=db.execute("""SELECT role,body,ref FROM messages WHERE path=? AND role IN ('assistant','user','document')
        ORDER BY id LIMIT 21 OFFSET ?""",(source['path'],offset)).fetchall()
    return dict(title=source['title'],framework=source['framework'],cwd=source['cwd'],
                more=len(rows)>20,turns=[dict(role=r['role'],markdown=r['body'],reference=r['ref'],
                                        html=md.render(r['body'])) for r in rows[:20]])



def cached_overview(db):
    row=db.execute('SELECT payload FROM summary_snapshot WHERE id=1').fetchone()
    return json.loads(row[0]) if row else overview(db,{},False)


def summarize(db,root,hour,manual=False):
    started=datetime.now(BEIJING)
    period=(started.date() if started.hour>=hour else started.date()-timedelta(days=1)).isoformat()
    previous=db.execute('SELECT night FROM summary_snapshot WHERE id=1').fetchone()
    if not manual and previous and previous[0]==period:
        return dict(skipped=True)
    coverage=refresh(db,root)
    result=run_due(db,root,lambda *_:coverage,project_root_finder(),terms,started,hour=0 if manual else hour)
    snapshot=overview(db,coverage)
    snapshot['cutoff']=started.isoformat()
    snapshot['partial']=result['partial']
    snapshot['undated']=db.execute("SELECT count(*) FROM messages WHERE occurred IS NULL AND role!='metadata'").fetchone()[0]
    night=period if not manual and not result['partial'] else previous[0] if previous else None
    with db:
        db.execute('INSERT OR REPLACE INTO summary_snapshot VALUES(1,?,?)',(json.dumps(snapshot,ensure_ascii=False),night))
    return result


def dispatch(args, db, root):
    if args['op']=='segments':
        return minilm.segments(db,args['session'],args.get('offset',0),args.get('query',''))
    if args['op']=='locations':
        return locations(db,args['session'],args['query'],args.get('offset',0),terms)
    if args["op"] == "pair_search":
        query=args["query"].strip()
        if not terms(query):raise ValueError("请输入可检索的关键词")
        return ranked(db,"",query,15,names(db),terms,args.get("sort","relevance"),args.get("offset",0),args.get("grouped") is True)
    if args["op"] == "pair_compare":
        return compare(db,args["a"],args["b"],args.get("query",""),terms,project_root_finder())
    if args["op"] == "latest_pair":
        row=db.execute('SELECT a,b,query FROM latest_comparison WHERE slot=1').fetchone()
        return dict(row) if row else {}
    if args["op"] in ("nightly","manual_refresh"):
        return summarize(db,root,args.get("hour",23),args["op"]=="manual_refresh")
    if args["op"]=="minilm_index":
        return minilm.optional(minilm.build,db)
    if args["op"] == "reports":
        return dict(list_reports(db),frameworks=names(db),minilm=minilm.coverage(db))
    if args["op"] == "report":
        return read_report(db,args["day"])
    if args["op"] == "vectors":
        return vector_search(db,args["query"],terms,args.get("day"),concepts(db,args["query"],terms),args.get("sort","relevance"))
    if args["op"] == "evidence":
        return read_evidence(db,args["session"],args["reference"])
    if args["op"] == "register_archive":
        return register(db,args)
    if args["op"] == "classify":
        return set_category(db,args)
    if args["op"] == "import_chatgpt":
        return import_chatgpt(db,args["payload"],store_external)
    if args["op"] == "transcript":
        return transcript(db,args["session"],args.get("offset",0))
    if args["op"] == "overview":
        return cached_overview(db)
    if args["op"] == "project":
        return project_sessions(db,args["project"],args.get("offset",0),args.get("framework","dsh"))
    chat = args.get("chat")
    if args["op"] == "index":
        return refresh(db,root)
    if not chat:
        raise ValueError("当前宿主未传入会话标识。")
    if args["op"] == "compare_choices":
        return compare_choices(db,chat,args.get("first"),args.get("second"))
    if args["op"] == "search":
        return search(db,chat,args["query"].strip(),sort=args.get("sort","relevance"))
    if args["op"] in ("select","quote"):
        return selection(db,chat,args)
    raise ValueError("未知操作。")


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    home = Path(os.getenv("DSH_HOME") or Path.home()/".dsh")
    location = Path(os.getenv("AGENT_MEMORY_DIR") or Path(os.environ.get("LOCALAPPDATA",Path.home()))/"AgentSessionMemory")
    def execute(args):
        with contextlib.closing(connect(location/"history-v1.sqlite")) as db:
            return dispatch(args, db,home/"sessions")
    if '--search-worker' in sys.argv:
        for line in sys.stdin:
            packet=json.loads(line)
            try:
                reply=dict(id=packet['id'],result=execute(packet['args']))
            except Exception as exc:
                reply=dict(id=packet['id'],error=str(exc))
            print(json.dumps(reply,ensure_ascii=False),flush=True)
    else:
        print(json.dumps(execute(json.load(sys.stdin)),ensure_ascii=False))
