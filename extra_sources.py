"""Local exports, small desktop stores, and source coverage."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def shell_folders(home):
    if os.getenv('AGENT_MEMORY_USER_DIR') or os.name!='nt':
        return home/'Downloads',home/'Documents',home/'Desktop'
    import winreg
    folders=[]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
        for k,fallback in [('{374DE290-123F-4565-9164-39C4925E467B}','Downloads'),('Personal','Documents'),('Desktop','Desktop')]:
            try: folders.append(Path(os.path.expandvars(winreg.QueryValueEx(key,k)[0])))
            except OSError: folders.append(home/fallback)
    return folders


def chatgpt(home,db,store,remove):
    from origins import import_chatgpt
    files=set()
    roots=set(shell_folders(home))
    extra=os.environ.get('AGENT_MEMORY_CHATGPT_EXPORTS')
    if extra:roots.add(Path(extra))
    for base in roots:
        for folder in (base,base/'ChatGPT'):
            if not folder.is_dir():continue
            for pattern in ('chatgpt-export*.md','conversations*.json'):
                files.update(f for f in folder.glob(pattern) if f.is_file() and
                             (f.suffix.lower()=='.md' or re.fullmatch(r'conversations(?:[-_]\d+)?\.json',f.name,re.I)))
    db.execute('CREATE TABLE IF NOT EXISTS chatgpt_files(path TEXT PRIMARY KEY, stamp TEXT)')
    known=dict(db.execute('SELECT path,stamp FROM chatgpt_files'))
    failures=0
    for f in sorted(files,key=lambda f:f.stat().st_mtime):
        try:
            st=f.stat();stamp=f'{st.st_size}:{st.st_mtime_ns}'
            if known.get(str(f))==stamp:continue
            txt=f.read_text(encoding='utf-8-sig')
            if f.suffix.lower()=='.md':
                # The exporter uses blockquotes both for prompts and quoted material inside replies.
                sid='md-'+hashlib.sha256(str(f).casefold().encode()).hexdigest()[:24]
                heading=next((line[2:].strip() for line in txt.splitlines()[:4] if line.startswith('# ')),f.stem)
                store(db,'chatgpt://'+sid,stamp,'chatgpt:'+sid,'',heading,int(st.st_mtime*1000),[('file','document',txt)] if txt.strip() else [])
            else:
                import_chatgpt(db,json.loads(txt),store)
            with db:db.execute('INSERT OR REPLACE INTO chatgpt_files VALUES(?,?)',(str(f),stamp))
        except (OSError,ValueError,TypeError):
            failures+=1
    note=f'本机发现 {len(files)} 份导出；支持从侧栏补充导入 JSON'
    return note+(f'；{failures} 份读取失败' if failures else '')


def chatlab(home,db,store,remove):
    path=home/'.chatlab/ai/conversations.db'
    if not path.is_file():return '未发现本地会话库'
    known=dict(db.execute("SELECT path,stamp FROM sources WHERE path LIKE 'chatlab://%'"))
    live=set()
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as src:
        src.execute('BEGIN')
        for sid,title,updated in src.execute('SELECT id,title,updated_at FROM ai_conversation'):
            key='chatlab://'+str(sid);live.add(key)
            from native_sources import timestamp
            rows=[(str(i),r,b,timestamp(t)) for i,r,b,t in src.execute("SELECT id,role,content,timestamp FROM ai_message WHERE conversation_id=? ORDER BY timestamp,id",(sid,)) if r in ('user','assistant') and isinstance(b,str) and b.strip()]
            stamp=hashlib.sha256(json.dumps([title,updated,rows],ensure_ascii=False).encode()).hexdigest()
            if known.get(key)!=stamp:
                store(db,key,stamp,'chatlab:'+str(sid),'',title or '未命名会话',timestamp(updated),rows)
    with db:
        for key in known.keys()-live:remove(db,key)
    return '已扫描本地会话库'


def evoscientist(home,db,store,remove):
    path=home/'.config/evoscientist/sessions.db'
    if not path.is_file():return '未发现本地会话库'
    import msgpack
    # Decode only message data. Never instantiate serialized Python classes.
    def extension(code,data):
        if code not in (2,5):return None
        value=msgpack.unpackb(data,raw=False,ext_hook=extension,strict_map_key=False)
        if isinstance(value,list) and len(value)>=3 and isinstance(value[2],dict) and value[1] in ('AIMessage','HumanMessage'):
            return {**value[2],'role':'assistant' if value[1]=='AIMessage' else 'user'}
        return None
    from native_sources import plain
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as src:
        src.execute('BEGIN')
        known=dict(db.execute("SELECT path,stamp FROM sources WHERE path LIKE 'evoscientist://%'"))
        live=set()
        for sid,count,last in src.execute("""SELECT thread_id,count(*),max(rowid) FROM writes
                WHERE channel='messages' AND checkpoint_ns='' GROUP BY thread_id"""):
            key='evoscientist://'+sid;live.add(key)
            stamp=f'{count}:{last}'
            if known.get(key)==stamp:continue
            rows=[];seen=set();updated=0
            for row,blob,checkpoint in src.execute("""SELECT rowid,value,checkpoint_id FROM writes WHERE thread_id=?
                  AND channel='messages' AND type='msgpack' AND checkpoint_ns='' ORDER BY rowid""",(sid,)):
                unpacked=msgpack.unpackb(blob,raw=False,ext_hook=extension,strict_map_key=False)
                from uuid import UUID
                try: u=UUID(checkpoint)
                except (ValueError,TypeError,AttributeError): u=None
                when=(int(u.hex[:12]+u.hex[13:16],16)-0x01b21dd213814000)//10000 if u is not None and u.version==6 else 0
                updated=max(updated,when)
                for n,m in enumerate(unpacked if isinstance(unpacked,list) else [unpacked]):
                    if not isinstance(m,dict) or m.get('role') not in ('user','assistant'):continue
                    body=plain(m.get('content'));ident=m.get('id') or f'{row}.{n}'
                    if body.strip() and ident not in seen:
                        seen.add(ident);rows.append((ident,m['role'],body,when))
            store(db,key,stamp,'evoscientist:'+sid,'',next((b[:100] for _,r,b,_ in rows if r=='user'),'未命名会话'),updated,rows)
        with db:
            for key in known.keys()-live:remove(db,key)
    return '已扫描本地会话库'


# These directories identify installed clients. They do not establish that chat text is available.
DETECTED={
 'trae':('Trae CN','AppData/Roaming/Trae CN/ModularData','已发现客户端；当前未接入其会话数据库'),
 'kimi-desktop':('Kimi 桌面版','AppData/Roaming/kimi-desktop','已发现独立客户端；未接入其云端会话'),
 'chatbox':('Chatbox','AppData/Roaming/xyz.chatboxapp.app','已发现客户端；当前未接入其聊天存储'),
 'antigravity':('Antigravity','.gemini/antigravity','已发现客户端；当前未接入其会话存储'),
 'alma':('Alma','AppData/Roaming/alma','已发现客户端；当前未接入其聊天存储'),
 'hive':('Hive','AppData/Roaming/hive','已发现协作运行库；工作者间消息单独保存在 Hive'),
 'doubao':('豆包','AppData/Roaming/Doubao','已发现客户端；未接入账号聊天历史'),
 'devin':('Devin','AppData/Roaming/Devin','已发现客户端；当前未接入其聊天存储'),
 'mira':('Mira Science','AppData/Roaming/mirascience','已发现客户端；未发现可确认的本地全文入口'),
 'multica':('Multica','AppData/Roaming/Multica','已发现客户端；当前未接入其聊天存储'),
 'cline':('Cline','.cline/data','已发现客户端；当前未接入其聊天存储'),
 'gemini':('Gemini','.gemini','已发现配置；当前未接入其会话存储'),
 'qwen':('Qwen Code','.qwen','已发现配置；当前未接入其会话存储'),
 'stepfun':('阶跃桌面版','AppData/Roaming/stepfun-desktop','已发现客户端；当前未接入其聊天存储'),
}

