"""Incrementally index the local transcripts of supported desktop agents."""
from extra_sources import DETECTED, chatgpt, chatlab, evoscientist
from contextlib import closing
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sqlite3

import zstandard


NAMES = {'codex':'Codex', 'kimi':'Kimi Code', 'workbuddy':'WorkBuddy', 'claude':'Claude Code',
         'bohrium':'玻尔 Bohrium', 'pi':'Pi', 'openclaw':'OpenClaw', 'chatlab':'ChatLab', 'evoscientist':'EvoScientist'}

# Each glob targets the main transcript and omits tool artifacts and delegated logs.
LAYOUTS = {
    'codex':('.codex',('sessions/*/*/*/rollout-*.jsonl*','archived_sessions/rollout-*.jsonl*')),
    'kimi':('.kimi-code/sessions',('*/*/agents/main/wire.jsonl',)),
    'workbuddy':('.workbuddy/projects',('*/*.jsonl',)),
    'claude':('.claude/projects',('*/*.jsonl',)),
    'pi':('.pi/agent/sessions',('*/*.jsonl',)),
    'openclaw':('.openclaw/agents',('*/sessions/*.jsonl',)),
}


def plain(content):
    if isinstance(content,str):
        return content
    return '\n'.join(p['text'] for p in content or [] if isinstance(p,dict)
                     and str(p.get('type','')).lower() in ('text','input_text','output_text') and isinstance(p.get('text'),str))


def metadata(path, sql):
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        return {r['id']:dict(r) for r in db.execute(sql)}


def timestamp(value):
    if isinstance(value,(int,float)):
        return int(value if value>1e11 else value*1000)
    if value:
        try:
            return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)
        except ValueError:
            pass
    return 0


def lines(path):
    with path.open('rb') as raw:
        stream=zstandard.ZstdDecompressor().stream_reader(raw) if path.suffix=='.zst' else raw
        with io.TextIOWrapper(stream,encoding='utf-8') as reader:
            for i,line in enumerate(reader,1):
                if not line.strip():
                    continue
                yield i,line


def parse_file(source,path,info):
    rows=[]
    title=info.get('title') or ''
    cwd=info.get('cwd') or ''
    updated=0
    for i,line in lines(path):
        # Skip large Codex tool responses before JSON decoding.
        if source=='codex' and not any(key in line[:220] for key in ('"session_meta"','"event_msg"')):
            continue
        o=json.loads(line)
        t=o.get('type')
        role=None
        body=''
        ident=o.get('uuid') or o.get('id') or str(i)
        if source=='codex':
            m=o.get('payload') or {}
            if t=='session_meta':
                if isinstance(m.get('source'),dict) and 'subagent' in m['source']:
                    return [],cwd,title,0
                cwd=cwd or m.get('cwd','')
            if t=='event_msg':
                role={'user_message':'user','agent_message':'assistant'}.get(m.get('type'))
                body=m.get('message')
                if m.get('type')=='item_completed':
                    item=m.get('item') or {}
                    role={'UserMessage':'user','AgentMessage':'assistant'}.get(item.get('type'))
                    if role:
                        ident=item.get('id') or ident
                        body=plain(item.get('content'))
        elif source=='kimi':
            if t=='agent.message.appended':
                entry=o.get('message') or {}
                m=entry.get('message') or {}
                role=m.get('role')
                meta=entry.get('meta') or {}
                if role=='user' and meta.get('source')!='input':
                    continue
                body=plain(m.get('content'))
        elif source=='workbuddy':
            cwd=cwd or o.get('cwd','')
            if t=='ai-title' and not info.get('title'):
                title=o.get('aiTitle') or title
            if t=='message':
                role=o.get('role')
                body=plain(o.get('content'))
        else:
            if o.get('isSidechain') or o.get('isMeta'):
                continue
            cwd=cwd or o.get('cwd','')
            if t=='session_info':
                title=o.get('name') or title
            if t in ('message','user','assistant'):
                m=o.get('message') or {}
                role=m.get('role')
                body=plain(m.get('content'))
        if role in ('user','assistant') and isinstance(body,str) and body.strip():
            occurred=timestamp(o.get('timestamp') or o.get('time'))
            rows.append((ident,role,body,occurred))
            updated=max(updated,occurred)
    return rows,cwd,title,updated


def file_index(source,home,db,store,remove):
    folder,patterns=LAYOUTS[source]
    root=home/folder
    if not root.is_dir():
        return '未发现会话目录'
    index={}
    if source=='codex':
        index=metadata(home/'.codex/state_5.sqlite','SELECT id,cwd,title,source FROM threads')
    elif source=='workbuddy':
        index=metadata(home/'.workbuddy/workbuddy.db','SELECT id,cwd,coalesce(nullif(custom_title,\'\'),title) AS title,deleted_at FROM sessions')
    known=dict(db.execute('SELECT path,stamp FROM sources WHERE path LIKE ?',(source+'://%',)))
    live=set()
    failed=0
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.suffix not in ('.zst','.jsonl'):continue
            ident=path.stem
            side=None
            if source=='codex':
                ident=path.name.split('.jsonl')[0][-36:]
            elif source=='kimi':
                side=path.parents[2]/'state.json'
                ident=path.parents[2].name.removeprefix('session_')
            elif source=='pi':
                ident=path.stem.rsplit('_',1)[-1]
            info=index.get(ident,{})
            if info.get('deleted_at') is not None or 'subagent' in str(info.get('source','')):
                continue
            key=source+'://'+ident
            live.add(key)
            try:
                stat=path.stat()
                stamp=f"2:{stat.st_mtime_ns}:{stat.st_size}:{info.get('title','')}"
                if side is not None and side.is_file():
                    stamp+=':'+str(side.stat().st_mtime_ns)
                if known.get(key)==stamp:continue
                if side is not None and side.is_file():
                    info=json.loads(side.read_text(encoding='utf-8-sig'))
                rows,cwd,title,updated=parse_file(source,path,info)
                title=title or next((b[:100] for _,r,b,_ in rows if r=='user'),'未命名会话')
                store(db,key,stamp,source+':'+ident,cwd or '',title,updated or int(stat.st_mtime*1000),rows)
            except (OSError,UnicodeError,ValueError,zstandard.ZstdError):
                failed+=1
    with db:
        for key in known.keys()-live:
            remove(db,key)
    return f'已扫描；{failed} 个文件读取失败' if failed else '已扫描本地会话'


def bohrium(home,db,store,remove):
    path=home/'.bohrium/brain.db'
    if not path.is_file():return '未发现本地会话库'
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as src:
        src.row_factory=sqlite3.Row
        src.execute('BEGIN')
        known=dict(db.execute("SELECT path,stamp FROM sources WHERE path LIKE 'bohrium://%'"))
        live=set()
        for s in src.execute("""SELECT s.id,s.updated_at,s.workspace_path,(SELECT max(seq) FROM events WHERE session_id=s.id) last_seq
                              FROM sessions s WHERE s.parent_session_id IS NULL"""):
            key='bohrium://'+s['id']
            live.add(key)
            stamp=f"{s['updated_at']}:{s['last_seq']}"
            if known.get(key)==stamp:continue
            rows=[];title=''
            for e in src.execute("""SELECT seq,type,data FROM events WHERE session_id=? AND type IN
                       ('user/message','assistant/message','session/title') ORDER BY seq""",(s['id'],)):
                event=json.loads(e['data'])
                data=event.get('data') or {}
                if e['type']=='session/title':
                    title=data.get('title') or title
                    continue
                role=e['type'].split('/')[0]
                if role=='user' and (data.get('source') or {}).get('kind')!='user':continue
                body=plain((data.get('message') or data).get('content'))
                if body.strip():rows.append((str(e['seq']),role,body,timestamp(event.get('time'))))
            store(db,key,stamp,'bohrium:'+s['id'],s['workspace_path'] or '',title or next((r[2][:100] for r in rows if r[1]=='user'),'未命名会话'),timestamp(s['updated_at']),rows)
        with db:
            for key in known.keys()-live:remove(db,key)
    return '已扫描本地会话库'


def sync_native(db,store,remove):
    home=Path(os.environ.get('AGENT_MEMORY_USER_DIR') or Path.home())
    coverage={}
    readers={'bohrium':bohrium,'chatlab':chatlab,'evoscientist':evoscientist,'chatgpt':chatgpt}
    for source in [*NAMES,'chatgpt']:
        try:
            if source in readers:
                coverage[source]=readers[source](home,db,store,remove)
            else:
                coverage[source]=file_index(source,home,db,store,remove)
        except (sqlite3.Error,OSError,ValueError,ImportError) as exc:
            coverage[source]='读取失败：'+str(exc)
    for source,(_,folder,note) in DETECTED.items():
        if (home/folder).is_dir():
            coverage[source]=note
    return coverage
