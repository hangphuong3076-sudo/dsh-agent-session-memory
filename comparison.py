"""Local, attributed comparisons. Quotes always point to an indexed message."""
import re

from archives import names
from nightly import group_for

# These labels align related vocabulary across clients. Other subjects use shared terms.
TOPICS = {
    '联网与部署':r'云端|云服务|云模型|远程服务|离线|本地模型|联网|cloud|offline|on.device',
    '预算与成本':r'预算|成本|费用|元以内|免费|budget|cost',
    '输出格式':r'导出|格式|\b(?:svg|png|pdf|csv|jsonl?|markdown)\b',
    '性能与资源':r'延迟|吞吐|显存|内存|耗时|性能|latency|memory usage',
    '交付与推送':r'推送|发布|交付|\b(?:push|publish|deploy)\b',
    '存储与检索':r'索引|检索|向量|数据库|sqlite|postgres|embedding',
}
REVISION = re.compile(r'改为|改成|调整为|换成|更改为|取消(?:之前|原先|原来)|不再(?:允许|需要|使用)|新增(?:要求|条件)|增加(?:一条|一个)?(?:限制|条件)|收回|instead of|switch to|change .{1,35} to ',re.I)
CONDITIONAL = re.compile(r'如果|假如|假设|是否|要不要|能否|能不能|可否|建议|有人说|助手说|之前说过|并未改|没有改|不(?:要|用|必|能)改|暂不改|没(?:有)?说(?:要)?改|维持原(?:案|条件)|[?？]|\b(?:if|should we|could we)\b',re.I)
REQUIRE = re.compile(r'需要|要求|希望|我想|我要|优先|做一个|必须|只(?:能|要|允许)|允许|可以用|可以使用|不能|不要|保留|限制|禁止|至少|最多|预算|目标|请|must|require|only|allow',re.I)
PROPOSAL = re.compile(r'方案|建议|选用|采用|使用|可以用|实现|通过.{1,35}来|推荐|设计|计划|选择|recommend|propos|implement|use\b',re.I)
REASON = re.compile(r'依据|因为|由于|为了|原因|实测|测得|日志显示|测试(?:通过|失败|结果)|验证(?:通过|失败)|耗时|基准|because|benchmark|tested|measured',re.I)
LANES=('当时的需求','提出的方案','理由与验证记录','未标注角色的材料','其他相关原话')
STOP={'需要','方案','建议','可以','使用','采用','要求','必须','这个','我们','项目','决定','支持','改为'}


def network_condition(text):
    if CONDITIONAL.search(text):
        return ''
    if re.search(r'完全离线|必须离线|只能离线|仅限离线|只(?:用|能用|允许)本地|不(?:能|得|允许)联网|禁止联网|offline.only',text,re.I):
        return '仅限本地或离线'
    if re.search(r'(?:不允许|不可以|不要|不得|禁止|不能)(?:再)?(?:使用|调用|用|接入)?云(?:端|服务|模型)',text):
        return '禁用云端'
    if re.search(r'(?:允许|可(?:以)?(?:使用|用|调用|接入)?|可以走)(?:使用|调用)?云(?:端|服务|模型)|allow cloud',text,re.I):
        return '允许使用云端'
    return ''


def quoted_or_question(text):
    return bool(CONDITIONAL.search(text) or re.search(r'[“「『"`][^”」』"`]*(?:'+REVISION.pattern+r')[^”」』"`]*[”」』"`]',text,re.I))

def constraints(text):
    facts={}
    if quoted_or_question(text) or re.search(r'助手(?:建议|认为|表示)|有人(?:建议|认为)|[“「『"].*?[”」』"]|(?:不用|不必|无需|不需要|不要求|并非)完全离线',text):
        return facts
    mode=network_condition(text)
    if mode:facts['联网与部署']=mode
    budget=re.search(r'(?:预算|成本上限|费用上限)[^。！？\d]{0,12}(\d+(?:\.\d+)?)\s*(万元|元)',text)
    if budget:
        revised=re.search(r'(?:改为|改成|调整为|上调至|下调至)\s*(\d+(?:\.\d+)?)\s*(万元|元)',text[budget.end():])
        amount=revised or budget
        facts['预算与成本']='预算 '+amount[1]+' '+amount[2]
    fmt=re.search(r'(?:格式(?:必须|仅限|为|改为)?|只(?:要|保留|允许|接受|导出)|改为|导出为)\s*(SVG|PNG|PDF|CSV|JSONL?|Markdown)(?![a-z])',text,re.I)
    if fmt:facts['输出格式']='格式 '+fmt[1].upper()
    return facts


def collect(db,source,side,tokenize,query):
    records=[]
    q=set(tokenize(query))
    messages=db.execute("SELECT id,role,body,ref,occurred FROM messages WHERE path=? AND role!='metadata' ORDER BY id",(source['path'],))
    for msg in messages:
        fenced=False
        for match in re.finditer(r'[^\n。！？!?]+[。！？!?]*',msg['body']):
            quote=match[0].strip()
            if quote.startswith(('```','~~~')):
                fenced=not fenced
                continue
            if fenced or not quote or quote.startswith('>'):continue
            role=msg['role']
            # Quoted or hypothetical changes should not become a user decision.
            changed=(role=='user' and bool(REVISION.search(quote)) and not quoted_or_question(quote))
            facts=constraints(quote) if role=='user' else {}
            lanes=[]
            if role=='document':
                lanes=[LANES[3]]
            else:
                if role=='user' and (changed or facts or REQUIRE.search(quote)):lanes.append(LANES[0])
                if PROPOSAL.search(quote) and (role=='assistant' or re.search(r'方案|建议|采用',quote)):lanes.append(LANES[1])
                if REASON.search(quote):lanes.append(LANES[2])
                if not lanes:lanes=[LANES[4]]
            tokens=set(tokenize(quote))-STOP
            topics={k for k,p in TOPICS.items() if re.search(p,quote,re.I)}
            offset=match.start()+len(match[0])-len(match[0].lstrip())
            citation=dict(side=side,session=source['sid'],title=source['title'],role=role,framework=source['framework'],
                          reference=msg['ref'],time=msg['occurred'],quote=quote[:360],clipped=len(quote)>360,offset=offset)
            if citation['clipped']:
                anchor=REVISION.search(quote) or REQUIRE.search(quote) or REASON.search(quote)
                start=max(0,anchor.start()-90) if anchor else 0
                citation.update(quote=quote[start:start+360],offset=offset+start)
                if changed and not REVISION.search(citation['quote']):changed=False
                facts=constraints(citation['quote']) if facts else {}
            records.append(dict(cite=citation,lanes=lanes,tokens=tokens,topics=topics,change=changed,order=(msg['id'],offset),
                                facts=facts,
                                rank=(len(q & tokens), bool(topics), bool(REASON.search(quote)), msg['id'])))
    return records


def affinity(a,b):
    shared=a['tokens'] & b['tokens']
    lexical=len(shared)/max(1,len(a['tokens'] | b['tokens']))
    return (0.6 if a['topics'] & b['topics'] else 0)+lexical


def comparable(a,b):
    labels=a['topics'] & b['topics']
    return next((name for name in TOPICS if name in labels),'相关表述')


def best_in_lane(records,lane):
    chosen=[];seen=set()
    for r in sorted((r for r in records if lane in r['lanes']),key=lambda r:r['rank'],reverse=True):
        if r['cite']['quote'] in seen:continue
        seen.add(r['cite']['quote']);chosen.append(r)
        if len(chosen)==5:break
    return chosen


def align(left,right,lane):
    a=best_in_lane(left,lane);b=best_in_lane(right,lane)
    pairs=sorted(((affinity(x,y),i,j) for i,x in enumerate(a) for j,y in enumerate(b)),reverse=True)
    used_a=set();used_b=set();rows=[]
    for score,i,j in pairs:
        if i in used_a or j in used_b or score<0.14:continue
        x,y=a[i],b[j]
        same=x['cite']['quote']==y['cite']['quote'] and not(x['cite']['clipped'] or y['cite']['clipped'])
        status='原句相同' if same else '表述有别'
        if not same:
            for pattern in (r'\d+(?:\.\d+)?\s*(?:万元|元|毫秒|分钟|小时|GB|MB|ms|秒)',r'(?<![A-Za-z])(?:SVG|PNG|PDF|CSV|Markdown|SQLite|PostgreSQL)(?![A-Za-z])'):
                va=list(dict.fromkeys(re.findall(pattern,x['cite']['quote'],re.I)))
                vb=list(dict.fromkeys(re.findall(pattern,y['cite']['quote'],re.I)))
                if va and vb and {v.lower() for v in va}!={v.lower() for v in vb}:
                    status='A 提及 '+'、'.join(va[:3])+'，B 提及 '+'、'.join(vb[:3])
                    break
        if lane==LANES[0]:
            for label,value in x['facts'].items():
                if label in y['facts'] and value!=y['facts'][label]:
                    status='A '+value+'，B '+y['facts'][label]
                    break
        rows.append(dict(topic=comparable(x,y),status=status,a=x['cite'],b=y['cite']))
        used_a.add(i);used_b.add(j)
    for side,items,used in [('a',a,used_a),('b',b,used_b)]:
        for i,r in enumerate(items):
            if i not in used:
                rows.append(dict(topic=next((k for k in TOPICS if k in r['topics']),lane),
                                 status='仅'+side.upper()+'侧选摘',**{side:r['cite']}))
    return rows


def changes(records,same_project):
    users=[r for r in records if r['cite']['role']=='user']
    found=[]
    for later in users:
        if not (later['change'] or later['facts']):continue
        new=later['cite'];eligible=[]
        for earlier in users:
            old=earlier['cite']
            if old['side']==new['side']:
                if earlier['order']>=later['order']:continue
            elif not (same_project and old['time'] and new['time'] and old['time']<new['time']):continue
            if LANES[0] not in earlier['lanes']:continue
            if quoted_or_question(old['quote']):continue
            if not later['change'] and not (earlier['facts'].keys() & later['facts'].keys()):continue
            score=affinity(earlier,later)
            if score>=0.2:eligible.append((earlier,score))
        # A repeated instruction is not a new change. Compare the most recent related user condition.
        local=[e for e in eligible if e[0]['cite']['side']==new['side']]
        last=max(local,key=lambda e:e[0]['order'],default=None)
        dated=[e for e in eligible if e[0]['cite']['time']]
        if dated and (not last or last[0]['cite']['time']):
            last=max(dated,key=lambda e:(e[0]['cite']['time'],e[1],e[0]['order']))
        prev=last[0] if last else None
        different=[]
        if prev:
            for label,value in later['facts'].items():
                old_value=prev['facts'].get(label)
                if old_value and value!=old_value:
                    if label=='联网与部署' and '允许使用云端' not in (value,old_value):continue
                    different.append(label+'：'+old_value+' → '+value)
        if later['change'] or different:
            found.append(dict(after=new,before=prev['cite'] if prev else None,
                              status='用户提出调整' if later['change'] else '先后约束不同，是否为同一次变更待核对',values=different))
    return found


def compare(db,left_id,right_id,query,tokenize,infer):
    if not left_id or left_id==right_id:raise ValueError('请选择两个不同的会话')
    sessions=[];records=[];groups=[];labels=names(db)
    for side,sid in [('A',left_id),('B',right_id)]:
        src=db.execute("""SELECT s.*,c.label FROM catalog_v5 s LEFT JOIN categories c
            ON c.framework=s.framework AND c.project_key=s.project_key WHERE sid=?""",(sid,)).fetchone()
        if not src:raise ValueError('选中的会话已不在索引中，请重新搜索')
        sessions.append(dict(side=side,session=sid,title=src['title'],project=src['cwd'],framework=labels[src['framework']]))
        groups.append(group_for(src,infer)[0])
        records.append(collect(db,src,side,tokenize,query))
    revisions=changes(records[0]+records[1],groups[0]==groups[1])
    return dict(sessions=sessions,changes=revisions[-12:],change_count=len(revisions),
                sections=[dict(name=lane,rows=align(*records,lane)) for lane in LANES])

