"""Read-only ZCode desktop database and local ChatGPT export ingestion."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from native_sources import NAMES, timestamp

FRAMEWORKS = {**NAMES, 'dsh': 'DeepSeek Harness', 'zcode': 'ZCode', 'chatgpt': 'ChatGPT'}


def zcode_path():
    return Path(os.environ.get('AGENT_MEMORY_ZCODE_DB') or Path.home()/'.zcode/cli/db/db.sqlite')


def sync_zcode(db, store, remove):
    path = zcode_path()
    if not path.is_file():
        return '未发现本地数据库'
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as src:
            src.row_factory = sqlite3.Row
            src.execute('BEGIN')
            sessions = src.execute("""SELECT id,title,directory,time_updated FROM session
                WHERE parent_id IS NULL AND time_deleted IS NULL""").fetchall()
            # WAL-backed databases can change without changing the main file's mtime.
            stamps = dict(src.execute("""SELECT session_id, printf('%d:%d:%d',count(*),max(time_updated),
                max(rowid)) FROM part GROUP BY session_id"""))
            known = dict(db.execute("SELECT path,stamp FROM sources WHERE path LIKE 'zcode://%'"))
            live = set()
            for session in sessions:
                sid = session['id']
                key = 'zcode://'+sid
                live.add(key)
                stamp = str(session['time_updated'])+':'+str(stamps.get(sid))
                if known.get(key) == stamp:
                    continue
                parts = src.execute("""SELECT p.id, json_extract(m.data,'$.role') AS role,
                    json_extract(p.data,'$.text') AS body, p.time_created AS time
                    FROM message m JOIN part p ON p.message_id=m.id AND p.session_id=m.session_id
                    WHERE m.session_id=? AND json_extract(p.data,'$.type')='text'
                    AND coalesce(json_extract(p.data,'$.synthetic'),0)=0
                    AND coalesce(json_extract(p.data,'$.ignored'),0)=0
                    ORDER BY m.sequence,m.time_created,m.id,p.sequence,p.time_created,p.id""",(sid,))
                rows = [(p['id'],p['role'],p['body'],timestamp(p['time'])) for p in parts
                        if p['role'] in ('user','assistant') and isinstance(p['body'],str) and p['body'].strip()]
                store(db,key,stamp,'zcode:'+sid,session['directory'] or '',session['title'] or '',
                      session['time_updated'] or 0,rows)
            with db:
                for key in known.keys()-live:
                    remove(db,key)
        return '已连接'
    except (sqlite3.Error,OSError,ValueError) as exc:
        return '读取失败：'+str(exc)


def import_chatgpt(db, payload, store):
    if isinstance(payload,dict) and 'mapping' in payload:
        payload=[payload]
    if not isinstance(payload,list) or not payload:
        raise ValueError('请选择含会话列表的 conversations.json 或分卷 JSON')
    updated=unchanged=0
    for item in payload:
        if not isinstance(item,dict) or not isinstance(item.get('mapping'),dict):
            raise ValueError('文件缺少 ChatGPT mapping 会话结构')
        ident=item.get('conversation_id') or item.get('id')
        if not isinstance(ident,str) or not ident:
            raise ValueError('ChatGPT 会话缺少 ID')
        mapping=item['mapping']
        node=item.get('current_node')
        if mapping and node not in mapping:
            leaves=[k for k,v in mapping.items() if not v.get('children')]
            if len(leaves)!=1:
                raise ValueError('无法确定当前会话分支，请使用含 current_node 的导出')
            node=leaves[0]
        chain=[]
        seen=set()
        while node:
            if node not in mapping or node in seen:
                raise ValueError('ChatGPT 消息链不完整')
            seen.add(node)
            data=mapping[node]
            msg=data.get('message') or {}
            role=(msg.get('author') or {}).get('role')
            content=msg.get('content') or {}
            text='\n'.join(p for p in content.get('parts',[]) if isinstance(p,str))
            if role in ('user','assistant') and text.strip() and not (msg.get('metadata') or {}).get('is_visually_hidden_from_conversation'):
                chain.append((node,role,text,timestamp(msg.get('create_time'))))
            node=data.get('parent')
        rows=list(reversed(chain))
        key='chatgpt://'+ident
        title=item.get('title') or '未命名会话'
        ts=int((item.get('update_time') or item.get('create_time') or 0)*1000)
        stamp=hashlib.sha256(json.dumps([title,ts,rows],ensure_ascii=False).encode()).hexdigest()
        previous=db.execute('SELECT stamp FROM sources WHERE path=?',(key,)).fetchone()
        if previous and previous[0]==stamp:
            unchanged+=1
        else:
            store(db,key,stamp,'chatgpt:'+ident,'',title,ts,rows)
            updated+=1
    return dict(updated=updated,unchanged=unchanged)

