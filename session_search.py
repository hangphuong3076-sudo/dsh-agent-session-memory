"""Search the existing message FTS and keep one result per session."""
from collections import Counter, defaultdict
from contextlib import closing
from difflib import get_close_matches
from math import log1p
from pathlib import Path
import re
import sqlite3
import unicodedata
import minilm

TOPICS = (
    ('玻尔', 'bohrium'), ('周赛', 'weekly challenge', 'weekly competition', 'weekly contest'),
    ('ppt', 'pptx', 'powerpoint', 'presentation', 'presentations', 'slide deck', 'slides', '汇报', '幻灯片', '演示文稿'),
    ('skill', 'skills', '技能'), ('优化', '改进', '提升', '优化器', 'optimize', 'optimise', 'optimization', 'improve', 'improvement'),
    ('版式','排版','版面','layout','typesetting'), ('论文','学术论文','research paper','paper','manuscript'),
    ('比赛','赛题','竞赛','比赛题','competition','contest','challenge'), ('产品', 'product'), ('离线', 'offline'), ('索引', 'index', 'indexing'),
)
ALIASES = {word: group for group in TOPICS for word in group}
STOP = {'上次','那个','后来','之前','当时','的','有关','关于','中','和','了','请','我','进行','the','of','a','for','in','and','to'}
HAN = r'[\u3400-\u9fff]'


def concepts(db, query, tokenize):
    groups = {}
    dictionary = Path(__file__).with_name('dictionary.sqlite')
    with closing(sqlite3.connect(dictionary.as_uri()+'?mode=ro&immutable=1',uri=True)) as lex:
        def expand(word):
            if word in ('比赛','竞赛','比赛题','competition','contest'):return (*ALIASES[word],'周赛','weekly challenge')
            if word in ALIASES:
                return ALIASES[word]
            return [r[0] for r in lex.execute('SELECT translation FROM lex WHERE term=? ORDER BY length(translation),translation LIMIT 8',(word,))]

        text = unicodedata.normalize('NFKC',query).casefold()
        words = re.findall(HAN+'+|[a-z0-9_]+',text)
        while words and len(groups)<24:
            word = words.pop(0)
            if re.fullmatch(HAN+'+',word):
                while word and len(groups)<24:
                    for size in range(min(8,len(word)),1,-1):
                        key = word[:size]
                        translations = expand(key)
                        if translations or key in STOP:
                            break
                    else:
                        key = word[:2]
                        translations = []
                        # Unknown Chinese spans overlap by one character for partial matches.
                        if len(key)==2 and len(word)>2:
                            groups.setdefault(key,(key,))
                            word=word[1:]
                            continue
                    word = word[len(key):]
                    if key not in STOP and (len(key)>1 or len(text)==1):
                        groups.setdefault(key,tuple(dict.fromkeys([key,*translations])))
            elif word not in STOP:
                for size in range(min(2,len(words)),0,-1):
                    phrase=' '.join([word,*words[:size]])
                    if expand(phrase):
                        word=phrase
                        del words[:size]
                        break
                translated=expand(word)
                if not translated and len(word)>=4 and word.isalpha():
                    known=db.execute('SELECT 1 FROM idx WHERE idx MATCH ? LIMIT 1',('"'+word+'"',)).fetchone()
                    if not known:
                        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS temp.search_vocab USING fts5vocab(main,idx,row)')
                        prefix=word[:2]
                        vocab=[r[0] for r in db.execute('SELECT term FROM search_vocab WHERE term>=? AND term<? AND length(term) BETWEEN ? AND ? ORDER BY doc DESC LIMIT 1000',(prefix,prefix+'{',len(word)-2,len(word)+2))]
                        corrected=get_close_matches(word,[*ALIASES,*vocab],n=1,cutoff=.78)
                        if corrected:
                            translated=[corrected[0],*expand(corrected[0])]
                groups.setdefault(word,tuple(dict.fromkeys([word,*translated])))
    # In conversational Chinese, untranslated overlapping bigrams can straddle two words.
    known={k:v for k,v in groups.items() if len(v)>1 or k.isascii()}
    if len(groups)>6 and len(known)>=3:return known
    return groups


def search_terms(db,query,tokenize):
    # Numbered task names are identifiers. Matching their two halves separately mixes projects.
    if re.fullmatch(HAN+r'+[0-9]+',query):
        return {query:(query,)},query
    return concepts(db,query,tokenize),''


def fts_expression(variants,tokenize):
    atoms=[]
    for v in variants:
        parts=tokenize(v)
        if parts:
            prefix=len(parts)==1 and v.isascii() and len(v)>=4
            atoms.append('"'+ ' '.join(parts)+'"' + ('*' if prefix else ''))
    return ' OR '.join(dict.fromkeys(atoms))


def location_pattern(groups):
    words=sorted({v for variants in groups.values() for v in variants},key=lambda v:(-len(v),v))
    patterns=[]
    for word in words:
        if word.isascii():
            parts=re.findall(r'[a-z0-9]+',word,re.I)
            if not parts:continue
            pattern=r'[\W_]+'.join(map(re.escape,parts))
            tail=r'[a-z0-9]*' if len(parts)==1 and len(word)>=4 else r'(?![a-z0-9])'
            patterns.append(r'(?<![a-z0-9])'+pattern+tail)
        else:
            patterns.append(re.escape(word)+(r'(?![0-9])' if word[-1].isdigit() else ''))
    return re.compile('|'.join(patterns) or '(?!)',re.I)


def locations(db,sid,query,offset,tokenize):
    if type(offset) is not int or offset<0 or not query.strip():
        raise ValueError('请输入关键词和有效的分页位置')
    source=db.execute('SELECT path,title,cwd FROM catalog_v5 WHERE sid=?',(sid,)).fetchone()
    if not source:raise ValueError('该会话已移出索引，请重新搜索')
    groups,_=search_terms(db,query.strip(),tokenize)
    pattern=location_pattern(groups)
    hits=[]
    total=0
    def collect(body,**where):
        nonlocal total
        previous,line=0,1
        for match in pattern.finditer(body):
            line+=body.count('\n',previous,match.start())
            previous=match.start()
            if offset<=total<offset+12:
                start,end=match.span()
                hits.append(dict(**where,line=line,offset=start,quote=match.group(),before=body[max(0,start-45):start],after=body[end:end+65]))
            total+=1
    rows=db.execute("SELECT ref,role,body,occurred FROM messages WHERE path=? AND role IN ('assistant','user','document') ORDER BY id",(source['path'],))
    for number,row in enumerate(rows,1):
        collect(row['body'],field='message',number=number,role=row['role'],time=row['occurred'],reference=row['ref'])
    for field in ('title','cwd'):
        collect(source[field] or '',field=field)
    return dict(hits=hits,total=total)


def ranked(db,chat,query,limit,labels,tokenize,sort='relevance',offset=0,grouped=False):
    if sort not in ('relevance','newest','oldest') or type(offset) is not int or offset<0:
        raise ValueError('排序或分页位置无效')
    rows={r['path']:r for r in db.execute('SELECT path,sid,cwd,title,updated,framework FROM catalog_v5 WHERE sid<>?',(chat,))}
    groups,literal=search_terms(db,query,tokenize) if query else ({},'')
    pattern=location_pattern(groups)
    scores=Counter()
    evidence=defaultdict(Counter)
    matched=defaultdict(list)
    title_scores=Counter()
    title_terms=Counter()
    for key,variants in groups.items():
        expr=fts_expression(variants,tokenize)
        if not expr:continue
        docs=defaultdict(list)
        sql='SELECT m.id,m.path,m.role FROM idx JOIN messages m ON m.id=idx.rowid WHERE idx MATCH ?'
        args=[expr]
        if literal:
            sql+=' AND (m.body GLOB ? OR m.body GLOB ?)'
            args.extend(('*'+literal+'[^0-9]*','*'+literal))
        for mid,path,role in db.execute(sql,args):
            if path in rows:docs[path].append((mid,role))
        weight=1+log1p(len(rows)/(1+len(docs)))
        for path,hits in docs.items():
            roles=Counter(role for _,role in hits)
            focus=min(3,roles['user'])+.25*min(4,roles['assistant']+roles['document'])
            title=(rows[path]['title'] or '')[:120].casefold()
            title_hit=any(v in title for v in variants)
            if title_hit:
                title_scores[path]+=weight
                title_terms[path]+=1
            scores[path]+=weight*(1+1.2*title_hit+.2*log1p(focus)+.3*bool(roles['metadata']))
            matched[path].append(key)
            for mid,role in hits:
                if role!='metadata':
                    evidence[path][mid]+=weight*(1.15 if role=='user' else 1)
    def order(path):
        row=rows[path]
        if not query or sort!='relevance':
            t=row['updated'] or 0
            return (not t,t if sort=='oldest' else -t,-scores[path],row['sid'])
        title=(row['title'] or '').casefold()
        same_message=max(evidence[path].values(),default=0)
        return (-len(matched[path]),-(scores[path]+.6*same_message+2*(query.casefold() in title)), -(row['updated'] or 0),row['sid'])
    if query:
        # Multi-topic requests should not return thousands of chats mentioning just one generic word.
        minimum=min((len(groups)+1)//2,max(map(len,matched.values()),default=0))
        eligible=[path for path in scores if len(matched[path])>=minimum]
    else:
        eligible=rows
    dense={}
    reason=''
    if query and not literal and not re.fullmatch(r'(?:[A-Za-z_-]*\d+[\w.-]*|[\w-]+\.[A-Za-z0-9]{1,8})',query):
        dense,reason=minilm.optional(minilm.retrieve,db,query,chat)
        dense={path:hit for path,hit in dense.items() if path in rows}
    if dense and sort=='relevance':
        # Fuse ranks rather than compare cosine and lexical scores on incompatible scales.
        lexical=sorted(eligible,key=order)
        fusion=Counter({p:1/(12+n) for n,p in enumerate(lexical,1)})
        for n,path in enumerate(dense,1):fusion[path]+=1/(12+n)
        # Titles often name the actual task while long prompts share the same boilerplate.
        named=sorted((p for p in title_scores if p in fusion or title_terms[p]>=2),key=lambda p:(-title_scores[p],order(p)))
        for n,path in enumerate(named,1):fusion[path]+=1.25/(12+n)
        available=sorted(fusion,key=lambda p:(-fusion[p],order(p)))
    else:
        named=[p for p in title_scores if title_terms[p]>=2] if dense else []
        available=sorted(dict.fromkeys([*eligible,*dense,*named]),key=order)
    buckets={}
    seen=set()
    for path in available:
        row=rows[path]
        identity=(row['framework'],row['sid'])
        if identity in seen:continue
        seen.add(identity)
        key=identity
        if grouped and row['cwd'] and row['title']:
            key=(row['framework'],row['cwd'],row['title'][:120])
        buckets.setdefault(key,[]).append(path)

    def candidate(path):
        r=rows[path]
        result=dict(session=r['sid'],framework=labels.get(r['framework'],r['framework']),project=r['cwd'],title=(r['title'] or '')[:120],updated=r['updated'],matched=matched[path])
        if path in dense:result['semantic']=dense[path]
        return result

    result=[]
    for i,members in enumerate(list(buckets.values())[offset:offset+limit],offset+1):
        path=members[0]
        entry=dict(candidate(path),number=i)
        if grouped:
            entry['others']=[candidate(p) for p in members[1:]]
        if evidence[path]:
            mid=max(evidence[path],key=evidence[path].get)
            role,body,ref=db.execute('SELECT role,body,ref FROM messages WHERE id=?',(mid,)).fetchone()
            match=pattern.search(body)
            if match:
                pos=max(0,match.start()-30)
                entry['hit']=dict(role=role,quote=body[pos:pos+170],reference=ref,offset=pos)
        result.append(entry)
    return dict(status='choose' if result else 'no_matches',candidates=result,semantic_error=reason,total=len(buckets),sessions=len(seen),order=sort if query else 'recent')
