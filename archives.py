"""User-selected local Markdown export folders. Each file represents one exported chat."""
import hashlib
from pathlib import Path

from extra_sources import DETECTED
from origins import FRAMEWORKS


def names(db):
    labels={key:v[0] for key,v in DETECTED.items()}
    labels.update(FRAMEWORKS)
    labels.update(db.execute("SELECT source,label FROM archive_folders"))
    return labels


def register(db,args):
    label=args.get('name','').strip()
    value=args.get('folder','').strip()
    folder=Path(value).expanduser()
    if not label or len(label)>60:raise ValueError('请输入 1–60 字的客户端名称')
    if not folder.is_absolute() or str(folder).startswith('\\\\') or not folder.is_dir():
        raise ValueError('请输入本机已有的导出目录的绝对路径')
    folder=folder.resolve()
    source=next((k for k,n in names(db).items() if n.casefold()==label.casefold() or k==label.casefold()),None)
    if source is None:source='local-'+hashlib.sha256(label.casefold().encode()).hexdigest()[:16]
    else:label=names(db)[source]
    existing=db.execute('SELECT source FROM archive_folders WHERE folder=?',(str(folder),)).fetchone()
    if existing and existing[0]!=source:raise ValueError('此目录已经关联到其他来源')
    with db:db.execute('INSERT OR REPLACE INTO archive_folders VALUES(?,?,?)',(str(folder),source,label))
    return {'source':source}


def sync_folders(db,coverage,store):
    for raw,source,label in db.execute('SELECT folder,source,label FROM archive_folders').fetchall():
        folder=Path(raw)
        try:
            if not folder.is_dir():raise OSError('目录不可用')
            total=0
            for f in folder.rglob('*.md'):
                if not f.is_file():continue
                stat=f.stat();stamp=f'{stat.st_size}:{stat.st_mtime_ns}'
                ident=hashlib.sha256(str(f.resolve()).casefold().encode()).hexdigest()[:24]
                # Automatic ChatGPT Markdown discovery uses the same file identity.
                key='chatgpt://md-'+ident if source=='chatgpt' else source+'+md://'+ident
                prior=db.execute('SELECT stamp FROM sources WHERE path=?',(key,)).fetchone()
                total+=1
                if prior and prior[0]==stamp:continue
                body=f.read_text(encoding='utf-8-sig')
                title=next((l[2:].strip() for l in body.splitlines()[:4] if l.startswith('# ')),f.stem)
                store(db,key,stamp,source+':md-'+ident,'',title,int(stat.st_mtime*1000),[('file','document',body)] if body.strip() else [])
            note=f'{raw} · {total} 份 Markdown'
        except (OSError,UnicodeError,ValueError) as exc:note=f'{raw} · 读取失败：{exc}'
        coverage[source]='；'.join(filter(None,[coverage.get(source),note]))

