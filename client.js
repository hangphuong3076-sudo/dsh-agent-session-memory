window.__ModuleLoader__.load({
  id: 'dsh-agent-session-memory',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const panelId = 'agent-session-memory'

    function Icon() {
      return h('span', { 'aria-hidden': true, style: { fontSize: 17 } }, '▤')
    }

    function useLocalData(url, revision) {
      const [state, setState] = React.useState({})
      React.useEffect(() => {
        if (!url) return
        const controller = new AbortController()

        ;(async () => {
          try {
            const response = await fetch(url, { signal: controller.signal, cache: 'no-store' })
            const data = await response.json()
            if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status))
            if (!controller.signal.aborted) setState({ url, revision, data, completed:revision, finishedAt:Date.now() })
          } catch (err) {
            if (!controller.signal.aborted) setState(prev => ({ ...(prev.url===url ? prev : {}), url, revision, error:err.message }))
          }
        })()
        return () => controller.abort()
      }, [url, revision])
      const current = state.url===url ? state : {}
      return { ...current, pending:current.revision!==revision }
    }
    const stamp = n => new Date(n).toLocaleString('zh-CN', { hour12: false })
    const api = 'api/session-memory.overview'
    const style = `
      .asm {height:100%;overflow:auto;box-sizing:border-box;padding:22px clamp(16px,4vw,52px);color:inherit}
      .asm section,.asm header,.asm footer {margin-bottom:16px}
      .asm .row {display:flex;gap:8px;align-items:center;flex-wrap:wrap}
      .asm h1 {font-size:23px;margin:8px 0}.asm h2 {font-size:18px;margin:12px 0}
      .asm button,.asm input,.asm select {font:inherit;color:inherit;background:transparent;border:1px solid #8886;border-radius:6px;padding:5px 9px}
      .asm select option {color:CanvasText;background:Canvas}
      .asm button,.asm summary {cursor:pointer}.asm button:disabled {opacity:.45;cursor:default}
      .asm button[aria-pressed=true] {background:#5989b026;border-color:#6287a8}
      .asm input[type=search] {width:min(100%,320px)} .asm input[type=file] {max-width:100%;box-sizing:border-box}
      .asm article {padding:12px 0;border-bottom:1px solid #8884;overflow-wrap:anywhere}
      .asm .title {font-weight:600;text-align:left;border:0;padding:0;text-decoration:underline;text-underline-offset:3px}
      .asm small {opacity:.8}.asm p {margin:6px 0}.asm footer {margin-top:12px}
      .asm pre {white-space:pre-wrap;overflow-wrap:anywhere;background:#8881;padding:10px;border-radius:6px}
      .asm .markdown {line-height:1.6}.asm .markdown ul,.asm .markdown ol {padding-inline-start:2em;list-style:revert}
      .asm .cmp-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;overflow-wrap:anywhere}
      .asm .cmp-cite {padding:8px 0}.asm .cmp-cite p {white-space:pre-wrap}
      @media(max-width:650px){.asm .cmp-grid {grid-template-columns:1fr;gap:4px}}
      .asm .markdown table {border-collapse:collapse}.asm .markdown td,.asm .markdown th {border:1px solid #8885;padding:3px 8px}
      .asm .markdown blockquote {border-inline-start:3px solid #8885;padding-inline-start:12px}
      .asm .markdown h1,.asm .markdown h2,.asm .markdown h3 {font-weight:600}

      .asm {--ink:CanvasText;--accent:light-dark(#176355,#81cfb7);--line:color-mix(in srgb,CanvasText 17%,Canvas);background:color-mix(in srgb,Canvas 96%,#799b94);color:var(--ink);font:14px/1.55 system-ui,sans-serif;padding:24px clamp(14px,3vw,44px) 48px}
      .asm>*:not(style){max-width:1080px;margin-inline:auto}
      .asm .banner{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:20px 24px;border-radius:16px;background:#163e39;color:#f4faf7}
      .asm .banner h1{font-size:clamp(24px,3vw,34px);letter-spacing:.02em;margin:0;font-weight:720}
      .asm .banner p,.asm .banner small{color:#cce6df}.asm .actions{display:grid;gap:5px;justify-items:start}
      .asm .actions button,.asm button[type=submit]{background:#176355;color:white;border-color:#176355;font-weight:650}
      .asm .actions button{background:#d8f4e8;color:#163e39}
      .asm nav{padding:4px 0 12px;border-bottom:1px solid var(--line)}
      .asm nav button{border:0;padding:7px 16px;font-weight:650}
      .asm button[aria-pressed=true]{background:color-mix(in srgb,var(--accent) 14%,Canvas);color:var(--accent);border-color:var(--accent)}
      .asm button:not(:disabled):hover{border-color:var(--accent);text-decoration:underline;text-underline-offset:3px}
      .asm :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
      .asm h2{font-size:19px;font-weight:700;margin:12px 0 8px}
      .asm .finder,.asm article,.asm .digest{box-sizing:border-box;background:Canvas;border:1px solid var(--line);border-radius:12px;padding:14px 17px;margin-block:9px}
      .asm .finder{margin-block:16px;padding:15px 20px}.asm .finder h2{margin-top:0}
      .asm .finder input[type=search]{width:min(100%,440px);flex:1 1 240px}
      .asm input,.asm select,.asm button{padding:6px 11px}
      .asm .metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0 10px}
      .asm .metrics div{padding:12px 16px;background:Canvas;border:1px solid var(--line);border-radius:12px}
      .asm .metrics strong{display:block;font-size:clamp(20px,2vw,28px);color:var(--accent);font-variant-numeric:tabular-nums}
      .asm .metrics span,.asm small{font-size:12px}.asm .cutoff,.asm .match{color:var(--accent)}
      .asm .digest summary{overflow-wrap:anywhere}.asm .digest summary small{margin-left:12px}.asm .digest summary p{font-weight:400;margin:5px 0 0;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
      .asm details{margin-block:8px}.asm .title{text-decoration:none;color:var(--accent)}
      .asm .finder .match{display:block;margin-top:4px}.asm .locations{margin-top:7px}.asm .passage,.asm .member{border-inline-start:3px solid var(--line);padding:7px 12px;margin:9px 0;overflow-wrap:anywhere}
      .asm .passage mark{background:#ffdf8d;color:#392800;border-radius:2px}
      @media(max-width:520px){.asm .banner{padding:16px;gap:10px}.asm .metrics{gap:5px}.asm .metrics div{padding:8px}}
    `
    const F = React.Fragment
    const button = (label, action, props={}) => h('button', {type:'button',onClick:action,...props},label)
    const titleOf = p => p.cwd ? p.cwd.split(/[\\/]/).filter(Boolean).pop() || p.cwd : p.title || '未命名会话'
    const route = args => api + '?' + new URLSearchParams(args)
    function pages(offset, step, set, more) {
      if (!offset && !more) return null
      return h('footer',{className:'row'},button('上一页',()=>set(offset-step),{disabled:!offset}),
        h('small',null,'第 '+(offset/step+1)+' 页'),button('下一页',()=>set(offset+step),{disabled:!more}))
    }
    function loading(state) {
      return state.error ? h('p',{role:'alert'},state.error) : h('p',{role:'status'},'正在读取本地索引…')
    }
    async function post(body) {
      const response=await fetch(api,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      const result=await response.json()
      if (!response.ok) throw new Error(result.error || ('HTTP '+response.status))
      return result
    }
    function Reader({sid,back,frameworkNames,revision,backText='返回项目会话'}) {
      const [offset,setOffset]=React.useState(0)
      const [raw,setRaw]=React.useState(false)
      const state=useLocalData(route({session:sid,offset}),revision)
      const data=state.data
      return h(F,null,button(backText,back),!data ? loading(state) : h(F,null,
        h('header',null,h('h1',null,data.title || '未命名会话'),h('small',null,frameworkNames[data.framework]+' · '+(data.cwd || '无工作目录'))),
        h(SessionSegments,{sid,title:data.title,revision,frameworkNames}),
        button(raw?'阅读 Markdown':'查看 Markdown 源文',()=>setRaw(!raw),{'aria-pressed':raw}),
        ...data.turns.map((t,i)=>h('article',{key:t.reference},h('h2',null,(offset+i+1)+' · '+({user:'用户',assistant:'Agent',document:'导出原文（未标注逐条角色）'}[t.role] || t.role)),
          raw ? h('pre',null,t.markdown) : h('div',{className:'markdown',dangerouslySetInnerHTML:{__html:t.html}}))),
        pages(offset,20,setOffset,data.more)))
    }
    function Project({project:p,back,categories,onSave,frameworkNames,revision}) {
      const [sid,setSid]=React.useState(null)
      const [offset,setOffset]=React.useState(0)
      const [label,setLabel]=React.useState(p.category)
      const [busy,setBusy]=React.useState(false)
      const [message,setMessage]=React.useState('')
      const state=useLocalData(route({framework:p.framework,project:p.project_key,offset}),revision)
      async function save() {
        setBusy(true); setMessage('')
        try {
          await post({op:'classify',framework:p.framework,project:p.project_key,label:label.trim()})
          onSave(label.trim()); setMessage('已保存')
        } catch(e) {setMessage('保存失败：'+e.message)} finally {setBusy(false)}
      }
      if (sid) return h(Reader,{sid,frameworkNames,revision,back:()=>setSid(null)})
      return h(F,null,button('返回项目列表',back),h('header',null,h('h1',null,titleOf(p)),h('small',null,frameworkNames[p.framework]+' · '+(p.cwd || '无工作目录')+' · '+p.sessions+' 个会话')),
        h('section',null,h('p',null,p.category ? '已归类 · '+p.category+'（'+p.method+'）':'未归类'),
          h('div',{className:'row'},h('input',{'aria-label':'分类名称',placeholder:'填写分类名称，清空可移回未归类',list:'asm-labels',maxLength:80,value:label,onChange:e=>setLabel(e.target.value)}),
          h('datalist',{id:'asm-labels'},categories.map(c=>h('option',{key:c,value:c}))),button('保存分类',save,{disabled:busy}),h('small',{role:'status'},message))),
        !state.data ? loading(state) : h(F,null,...state.data.sessions.map(s=>h('article',{key:s.sid},
          button(s.title || '未命名会话',()=>setSid(s.sid),{className:'title',title:'打开 Markdown 对话全文'}),
          h('p',null,h('small',null,stamp(s.updated))),s.request && h('p',null,h('strong',null,'最近的用户原话　'),s.request),
          s.reply && h('p',null,h('strong',null,'最近的 Agent 回复　'),s.reply))),pages(offset,12,setOffset,state.data.more)))
    }
    function ArchiveFolder({options,added}) {
      const [name,setName]=React.useState('')
      const [folder,setFolder]=React.useState('')
      const [msg,setMsg]=React.useState('')
      async function save(e) {
        e.preventDefault()
        try {
          const result=await post({op:'register_archive',name,folder})
          setMsg('已关联，刷新时会补读这个目录。');added(result.source)
        } catch(err) {setMsg(err.message)}
      }
      return h('details',null,h('summary',null,'添加其他客户端的 Markdown 导出目录'),
        h('form',{onSubmit:save},h('p',null,'选择专门存放会话导出的目录。每个 Markdown 文件作为一篇会话原文，包含子目录。'),
        h('div',{className:'row'},h('input',{value:name,onChange:e=>setName(e.target.value),placeholder:'客户端名称',required:true,list:'asm-sources'}),
        h('datalist',{id:'asm-sources'},options.map(n=>h('option',{key:n,value:n}))),
        h('input',{value:folder,onChange:e=>setFolder(e.target.value),placeholder:'本机导出目录的完整路径',required:true}),
        h('button',{type:'submit'},'关联目录')),msg && h('small',{role:'status'},msg)))
    }
    const sortOptions=[['relevance','相关度'],['newest','时间从新到旧'],['oldest','时间从旧到新']]
    function sortSelect(value,change,disabled=false) {
      return h('label',null,'排序 ',h('select',{value,disabled,onChange:e=>change(e.target.value)},sortOptions.map(([key,label])=>h('option',{key,value:key},label))))
    }
    const beijing=n=>new Date(n).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})
    const roles={user:'用户',assistant:'助手',document:'导出原文'}
    function EvidenceDetail({item,revision,frameworkNames,back,backText}) {
      const state=useLocalData(route({evidence:item.reference,session:item.session}),revision)
      const e=state.data
      const mark=React.useRef(null)
      // Backend offsets count Unicode characters; JavaScript indexes UTF-16 code units.
      const start=e && !e.missing && item.offset ? Array.from(e.text).slice(0,item.offset).join('').length : 0
      const index=e && !e.missing ? e.text.indexOf(item.quote,start) : -1
      React.useEffect(()=>{if(index>=0) mark.current?.scrollIntoView({block:'center'})},[e,index])
      return h('section',null,button(backText,back),h('h2',null,item.title || '会话原话'),
        state.error || !e ? loading(state) : e.missing ? h('p',{role:'alert'},'原消息已变化或移除。当时摘录：'+item.quote) :
        h(F,null,h('small',null,[frameworkNames[e.framework] || e.framework,roles[e.role],e.time?new Date(e.time).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）':'时间未记录'].join(' · ')),
          e.previous && h('details',null,h('summary',null,'上一条发言 · '+roles[e.previous.role]),h('pre',null,e.previous.text)),
          h('pre',null,index<0 ? e.text : h(F,null,e.text.slice(0,index),h('mark',{ref:mark},item.quote),e.text.slice(index+item.quote.length))),
          e.following && h('details',null,h('summary',null,'下一条发言 · '+roles[e.following.role]),h('pre',null,e.following.text))))
    }
    function DailyReports({revision,frameworkNames,state}) {
      const [sort,setSort]=React.useState("relevance")
      const [selected,setSelected]=React.useState('')
      const [filter,setFilter]=React.useState('')
      const [input,setInput]=React.useState('')
      const [query,setQuery]=React.useState('')
      const [item,open]=React.useState(null)
      const list=state.data
      const day=selected || list?.days[0]?.day
      const info=list?.days.find(d=>d.day===day)
      const report=useLocalData(day ? route({report:day}) : null,info?.built)
      const vector=useLocalData(query ? route({vectors:query,sort}) : null,list?.days[0]?.built)
      function citation(f,i) {
        const name=frameworkNames[f.framework] || f.framework
        return h('article',{key:i},h('small',null,[f.day,f.kind,roles[f.role],name,f.title].filter(Boolean).join(' · ')),
          h('p',null,f.quote),button('查看原话',()=>open(f)))
      }
      if (item) return h(EvidenceDetail,{item,revision,frameworkNames,back:()=>open(null),backText:'返回晚间汇总'})
      if (!list || state.error) return loading(state)
      const groups=report.data?.reports.filter(g=>g.project.toLocaleLowerCase().includes(filter.toLocaleLowerCase())) || []
      return h('section',null,h('h2',null,'晚间汇总'),
        
        list.schedule.running && h('p',{role:'status'},'后台正在整理会话与向量…'),
        list.schedule.error && h('p',{role:'alert'},'上次运行失败，将自动重试：'+list.schedule.error),
        h('details',null,h('summary',null,'检索晚间摘录'),h('form',{className:'row',onSubmit:e=>{e.preventDefault();setQuery(input.trim())}},h('input',{type:'search',value:input,
          onChange:e=>{setInput(e.target.value);if (!e.target.value) setQuery('')},placeholder:'跨日报搜索项目讨论或结论'}),h('button',{type:'submit'},'查找摘录'),sortSelect(sort,setSort),
          query && button('返回日报',()=>{setInput('');setQuery('')}))),
        query ? (vector.error || !vector.data ? loading(vector) : h(F,null,h('p',null,'相关原文 · '+vector.data.hits.length+' 条'),...vector.data.hits.map(citation))) :
        !day ? h('article',null,h('strong',null,'还没有已保存的日报'),h('p',null,'可手动刷新生成第一份，也可以等今晚自动汇总。')) :
        h(F,null,h('div',{className:'row'},h('label',null,'日报日期 ',h('select',{value:day,onChange:e=>setSelected(e.target.value)},
          list.days.map(d=>h('option',{key:d.day,value:d.day},d.day)))),
          h('input',{type:'search',value:filter,onChange:e=>setFilter(e.target.value),placeholder:'筛选日报项目'})),
          h('div',{className:'metrics'},[[info.projects,'个项目'],[info.messages,'条原话'],[info.vectors,'个索引片段']].map(([value,label])=>h('div',{key:label},h('strong',null,Number(value).toLocaleString()),h('span',null,label)))),
          h('p',{className:'cutoff'},'本日报内容截止 '+beijing(Math.min(Date.parse(info.built),Date.parse(day+'T23:59:59.999+08:00')))+'（北京时间）'),
          info.partial===1 && h('p',{role:'alert'},'部分来源读取失败，后台会重试。'),
          report.data && h('details',null,h('summary',null,'扫描范围与时间依据'),
            h('p',null,'按消息发生时间分日，整篇 Markdown 按文件更新时间列出。'+(list.undated==null?'':'另有 '+list.undated+' 条原文缺少时间。')),
            ...Object.entries(report.data.coverage).filter(([,v])=>typeof v==='string').map(([k,v])=>h('p',{key:k},(frameworkNames[k] || k)+' · '+v))),
          report.error || !report.data ? loading(report) : !groups.length ? h('p',null,filter?'没有匹配的项目。':'当天没有可归入此日期的会话原文。') :
          groups.map(g=>h('details',{className:'digest',key:g.project+'-'+(g.findings[0]?.session || '')},h('summary',null,h('strong',null,g.project),h('small',null,g.sessions+' 个会话 · '+g.messages+' 条原文'),g.findings[0] && h('p',null,g.findings[0].kind+' · '+g.findings[0].quote)),
            h('small',null,g.sources.map(k=>frameworkNames[k] || k).join('、')),
            g.findings.length ? g.findings.map(citation) : h('p',null,'没有可摘录的正文句子。')))))
    }


    function SessionSegments({sid,title,query='',revision,frameworkNames}) {
      const [expanded,expand]=React.useState(false)
      const [byTopic,rank]=React.useState(Boolean(query))
      const [offset,page]=React.useState(0)
      const [item,open]=React.useState(null)
      const [chosen,setChosen]=React.useState([])
      const [notice,setNotice]=React.useState('')
      const [copyText,setCopyText]=React.useState('')
      function toggle(hit) {
        setChosen(old=>old.some(x=>x.slot===hit.slot)?old.filter(x=>x.slot!==hit.slot):[...old,hit])
        setNotice('');setCopyText('')
      }
      async function copy() {
        const ordered=[...chosen].sort((a,b)=>a.slot-b.slot)
        const blocks=ordered.map(hit=>{
          const where=hit.reference?'第 '+hit.turn+' 条发言 · '+roles[hit.role]:'会话标题'
          const ref=hit.reference?' · '+hit.reference+' · 字符偏移 '+hit.offset:''
          return '第 '+(hit.slot+1)+' 段 · '+where+ref+'\n\n'+hit.quote.split('\n').map(line=>'> '+line).join('\n')
        })
        const text=['# '+(title || sid),'会话 '+sid,...blocks].join('\n\n')
        try {await navigator.clipboard.writeText(text);setNotice('已复制 '+ordered.length+' 段原话');setCopyText('')}
        catch {setCopyText(text);setNotice('请在下方文本框中复制选段')}
      }
      const state=useLocalData(expanded?route({segments:sid,q:byTopic?query:'',offset}):null,revision)
      if (item) return h(EvidenceDetail,{item,revision,frameworkNames,back:()=>open(null),backText:'返回会话分段'})
      return h('div',{className:'locations'},button(expanded?'收起全部分段':'浏览全部分段',()=>expand(!expanded),{'aria-expanded':expanded}),
        expanded && (state.error || !state.data ? loading(state) : h(F,null,
          h('div',{className:'row'},h('strong',null,'共 '+state.data.total+' 段'),
            query && h('select',{'aria-label':'分段排序',value:byTopic?'topic':'original',onChange:e=>{rank(e.target.value==='topic');page(0)}},
              h('option',{value:'topic'},'语义相关度'),h('option',{value:'original'},'原文顺序'))),
          chosen.length>0 && h('div',{className:'row'},button('复制所选原话（'+chosen.length+'）',copy),
            button('清空选择',()=>{setChosen([]);setCopyText('');setNotice('')})),
          notice && h('small',{role:'status'},notice),copyText && h('textarea',{readOnly:true,value:copyText,'aria-label':'所选原话'}),
          state.data.error && h('small',{role:'status'},state.data.error),
          !state.data.total && h('p',null,'此会话尚未完成全文分段索引。'),
          state.data.hits.map(hit=>h('div',{key:hit.slot,className:'passage'},
            h('label',null,h('input',{type:'checkbox',checked:chosen.some(x=>x.slot===hit.slot),onChange:()=>toggle(hit),'aria-label':'选择第 '+(hit.slot+1)+' 段'}),' ',
              h('strong',null,'第 '+(hit.slot+1)+' 段 · '+(hit.reference?'第 '+hit.turn+' 条发言 · '+roles[hit.role]:'会话标题'))),
            h('p',null,hit.quote),hit.reference && button('查看这段原话',()=>open({...hit,session:sid,title})))),
          pages(offset,12,page,offset+12<state.data.total))))
    }

    function HitPositions({session,query,revision,frameworkNames}) {
      const [expanded,expand]=React.useState(false)
      const [offset,setOffset]=React.useState(0)
      const [item,open]=React.useState(null)
      const state=useLocalData(expanded?route({locations:query,session:session.session,offset}):null,revision)
      if (item) return h(EvidenceDetail,{item,revision,frameworkNames,back:()=>open(null),backText:'返回命中位置'})
      return h('div',{className:'locations'},button(expanded?'收起命中位置':'展开命中位置',()=>expand(!expanded),{'aria-expanded':expanded}),
        expanded && (state.error || !state.data ? loading(state) : h(F,null,h('small',{role:'status'},' 共 '+state.data.total+' 处'),
          state.data.hits.map((hit,i)=>h('div',{className:'passage',key:i},
            h('strong',null,hit.field==='message'?'第 '+hit.number+' 条发言 · '+roles[hit.role]:hit.field==='title'?'会话标题':'工作目录'),
            h('small',null,' · 第 '+hit.line+' 行'+(hit.time?' · '+stamp(hit.time):'')),
            h('p',null,hit.before,h('mark',null,hit.quote),hit.after),
            hit.reference && button('定位这处原话',()=>open({...hit,session:session.session,title:session.title})))),
          pages(offset,12,setOffset,offset+12<state.data.total))))
    }

    function SessionFinder({frameworkNames,revision,compare=false,children}) {
      const [input,setInput]=React.useState('')
      const [query,setQuery]=React.useState('')
      const [hits,setHits]=React.useState(null)
      const [sort,setSort]=React.useState('relevance')
      const [offset,setOffset]=React.useState(0)
      const [sid,setSid]=React.useState(null)
      const [picked,setPicked]=React.useState([])
      const [report,setReport]=React.useState(null)
      const [item,open]=React.useState(null)
      const [busy,setBusy]=React.useState(false)
      const [error,setError]=React.useState('')
      async function request(action) {
        setBusy(true);setError('')
        try {await action()} catch(err){setError(err.message)} finally{setBusy(false)}
      }
      function search(key=input.trim(),order=sort,pos=0) {
        if (!key) return
        request(async()=>{
          const result=await post({op:'pair_search',query:key,sort:order,offset:pos,grouped:true})
          setHits(result);setQuery(key);setSort(order);setOffset(pos)
        })
      }
      function toggle(row) {
        setPicked(old=>old.some(c=>c.session===row.session) ? old.filter(c=>c.session!==row.session) : [...old,row].slice(0,2))
      }
      async function loadPair(a,b,key) {
        setReport(await post({op:'pair_compare',a,b,query:key}));open(null)
      }
      function latest() {
        request(async()=>{
          const pair=await post({op:'latest_pair'})
          if (!pair.a) throw new Error('还没有在聊天中完成的双会话比较。')
          await loadPair(pair.a,pair.b,pair.query)
        })
      }
      function citation(c,label) {
        if (!c) return h('small',null,'缺少可对齐的原话')
        return h('div',{className:'cmp-cite'},h('small',null,[label || c.side,roles[c.role],c.time?stamp(c.time):'时间未记录'].join(' · ')),
          h('p',null,c.quote,c.clipped?'…':''),button('查看 '+c.side+' 原话',()=>open(c)))
      }
      if (sid) return h(Reader,{sid,back:()=>setSid(null),frameworkNames,revision,backText:'返回检索结果'})
      if (item) return h(EvidenceDetail,{item,revision,frameworkNames,back:()=>open(null),backText:compare?'返回方案比较':'返回检索结果'})
      if (report) return h('section',null,button('返回选择会话',()=>setReport(null)),h('h2',null,'两段会话的比较'),
        h('div',{className:'cmp-grid'},report.sessions.map(s=>h('div',{key:s.side},h('strong',null,s.side+' · '+(s.title || '未命名会话')),
          h('p',null,s.framework+' · '+(s.project || '工作目录未知'))))),
        h('h2',null,'用户是否调整了条件'),
        report.change_count>report.changes.length && h('small',null,'共识别 '+report.change_count+' 条调整线索，本页选列 '+report.changes.length+' 条。'),
        report.changes.length ? report.changes.map((change,i)=>h('article',{key:i},h('strong',null,change.status),change.values?.length>0 && h('p',null,change.values.join(' · ')),
          h('div',{className:'cmp-grid'},citation(change.before,'此前相关原话 · '+(change.before?.side || '')),citation(change.after,'后续原话 · '+change.after.side)))) :
          h('p',null,'这两段记录中未识别到明确的用户调整。缺时间或只有助手转述时，请结合原话判断。'),
        report.sections.filter(section=>section.rows.length || !['未标注角色的材料','其他相关原话'].includes(section.name)).map(section=>
          h('section',{key:section.name},h('h2',null,section.name),
            section.name==='理由与验证记录' && h('small',null,'这里列出会话中陈述的理由、日志或测试结果，保留发言人。'),
            section.rows.length ? section.rows.map((row,i)=>h('article',{key:i},h('strong',null,row.topic+' · '+row.status),
              h('div',{className:'cmp-grid'},citation(row.a),citation(row.b)))) : h('p',null,'两侧均缺少可识别的相关原话。'))))
      function member(c,grouped=false) {
        const label=grouped?(c.updated?stamp(c.updated):'时间未知')+' · '+c.session.slice(-8):(c.title || c.session)
        const has=picked.some(x=>x.session===c.session)
        return h('div',{key:c.session,className:grouped?'member':undefined},
          compare ? h('label',null,h('input',{type:'checkbox',checked:has,disabled:busy || (!has && picked.length===2),onChange:()=>toggle(c)}),' '+label) :
            button(label,()=>setSid(c.session),{className:'title',title:'打开此会话全文'}),
          !grouped && h('p',null,h('small',null,[c.framework,c.updated?stamp(c.updated):'时间未知',c.project].filter(Boolean).join(' · '))),
          c.matched.length>0 && h('small',{className:'match'},'匹配主题 · '+c.matched.join('、')),
          c.hit && h('p',null,c.hit.quote),
          c.hit && button('查看命中原话',()=>open({...c.hit,session:c.session,title:c.title})),
          c.semantic && h('div',{className:'passage'},h('strong',null,'语义相关 · '+(roles[c.semantic.role] || '标题')),h('p',null,c.semantic.quote),
            c.semantic.reference ? button('查看相关原段',()=>open({...c.semantic,session:c.session,title:c.title})) : button('打开会话全文',()=>setSid(c.session))),
          h(SessionSegments,{key:JSON.stringify(['segments',c.session,query]),sid:c.session,title:c.title,query,revision,frameworkNames}),
          c.matched.length>0 && h(HitPositions,{key:JSON.stringify([c.session,query]),session:c,query,revision,frameworkNames}))
      }
      return h(F,null,h('section',{className:'finder'},h('h2',null,compare?'比较方案':'检索全部会话'),
        h('form',{className:'row',onSubmit:e=>{e.preventDefault();search()}},h('input',{type:'search',value:input,disabled:busy,onChange:e=>setInput(e.target.value),
          placeholder:'例如：玻尔产品周赛 优化 PPT skill','aria-label':'会话全文关键词'}),h('button',{type:'submit',disabled:busy || !input.trim()},compare?'搜索候选':'搜索会话'),
          sortSelect(sort,v=>hits?search(query,v):setSort(v),busy),
          hits && button('清除检索',()=>{setInput('');setQuery('');setHits(null)},{disabled:busy})),
        compare && h('div',{className:'row'},button('比较所选会话',()=>request(()=>loadPair(picked[0].session,picked[1].session,query)),{disabled:busy || picked.length!==2}),
          button('打开最近一次聊天比较',latest,{disabled:busy}),h('small',null,'已选 '+picked.length+' / 2')),
        ...picked.map((c,i)=>h('div',{key:c.session},button((i?'B':'A')+' · '+(c.title || c.session)+' ×',()=>toggle(c),{disabled:busy,title:'移除此会话'}))),
        busy && h('p',{role:'status'},'正在检索本地索引…'),error && h('p',{role:'alert'},error),
        hits?.semantic_error && h('small',{role:'status'},'使用关键词检索 · '+hits.semantic_error),
        hits && h('p',{role:'status'},'「'+query+'」 · '+hits.total+' 个条目 · '+hits.sessions+' 个会话'),
        ...(hits?.candidates || []).map(c=>h('article',{key:c.session},c.others?.length ? h(F,null,
          h('strong',null,c.title),h('p',null,h('small',null,[c.framework,c.project].join(' · '))),
          member(c,true),h('details',null,h('summary',null,'同目录、标题显示相同的其他会话（'+c.others.length+'）'),c.others.map(row=>member(row,true)))) : member(c))),
        hits && !busy && pages(offset,15,n=>search(query,sort,n),offset+15<hits.total)),!hits && children)
    }

    function Panel() {
      const [view,setView]=React.useState('daily')
      const [revision,refresh]=React.useReducer(n=>n+1,0)
      const reports=useLocalData(route({reports:1}),revision)
      const overview=useLocalData(view==='sessions'?api:null,revision)
      const [selected,select]=React.useState(null)
      const [source,setSource]=React.useState('')
      const [status,setStatus]=React.useState('')
      const [category,setCategory]=React.useState('')
      const [query,setQuery]=React.useState('')
      const [offset,setOffset]=React.useState(0)
      const [busy,setBusy]=React.useState(false)
      const [message,setMessage]=React.useState('')
      async function scan() {
        setBusy(true);setMessage('正在扫描本地来源，当前仍显示上次汇总。')
        try {
          const result=await post({op:'manual_refresh'})
          setMessage(result.minilm?.error?'日报已保存，语义索引待更新：'+result.minilm.error:result.partial?'汇总已保存，部分来源读取失败。':'已保存最新汇总。');refresh()
        } catch(e){setMessage('刷新失败：'+e.message)} finally {setBusy(false)}
      }
      const frameworkNames=overview.data?.frameworks || reports.data?.frameworks || {}
      const projects=overview.data?.projects || []
      const categories=Array.from(new Set(projects.map(p=>p.category).filter(Boolean))).sort((a,b)=>a.localeCompare(b,'zh-CN'))
      const scoped=projects.filter(p=>!source || p.framework===source)
      const classified=scoped.filter(p=>p.category).length
      const keyword=query.trim().toLocaleLowerCase()
      const found=scoped.filter(p=>(!status || (status==='done')===!!p.category) && (!category || category===p.category) &&
        [p.cwd,p.title,p.category,p.project_key].some(v=>(v || '').toLocaleLowerCase().includes(keyword)))
      function field(set,value) {set(value);setOffset(0)}
      function update() {refresh()}
      async function importFiles(e) {
        const files=Array.from(e.target.files);e.target.value=''
        if (!files.length) return
        let updated=0,unchanged=0
        setBusy(true);setMessage('正在导入…')
        try {
          for (const file of files) {
            const data=JSON.parse((await file.text()).replace(/^\uFEFF/,''))
            const chats=Array.isArray(data)?data:[data]
            if (!chats.length) throw new Error('文件中没有会话')
            for (const chat of chats) {
              const result=await post({op:'import_chatgpt',payload:chat})
              updated+=result.updated;unchanged+=result.unchanged
            }
          }
          setSource('chatgpt');setStatus('');setCategory('');setQuery('')
          setMessage('导入完成，新增或更新 '+updated+' 个会话，已有 '+unchanged+' 个。')
        } catch(err) {setMessage('导入中断，已更新 '+updated+' 个，已有 '+unchanged+' 个。'+err.message)} finally {setBusy(false);if(updated || unchanged) await scan()}
      }
      const pos=Math.min(offset,Math.max(0,Math.floor((found.length-1)/20)*20))
      const active=selected && projects.find(p=>p.framework===selected.framework && p.project_key===selected.project_key)
      return h('main',{className:'asm'},h('style',null,style),
        h('header',{className:'banner'},h('div',null,h('h1',null,'会话汇总'),
          h('p',null,reports.data?.days.length?'最新日报内容截止 '+beijing(Math.min(Date.parse(reports.data.days[0].built),Date.parse(reports.data.days[0].day+'T23:59:59.999+08:00')))+'（北京时间）':reports.pending?'正在读取已保存的日报…':'尚无已保存的日报')),
          h('div',{className:'actions'},button(busy?'正在处理…':'手动刷新',scan,{disabled:busy}),
            h('small',null,'每日 '+String(reports.data?.schedule.hour ?? 23).padStart(2,'0')+':00 北京时间自动汇总'))),
        reports.data?.minilm && h('small',null,'MiniLM 全文分段 · '+reports.data.minilm.indexed+' / '+reports.data.minilm.total+' 个会话 · '+reports.data.minilm.segments.toLocaleString()+' 段'),
        message && h('p',{role:'status'},message),
        overview.error && overview.data && h('p',{role:'alert'},'读取失败：'+overview.error),
        h('nav',{className:'row','aria-label':'汇总视图'},[['daily','晚间汇总'],['sessions','项目分类'],['compare','比较方案']].map(([key,label])=>
          button(label,()=>setView(key),{key,'aria-pressed':view===key}))),
        view!=='sessions' ? h(SessionFinder,{key:view,revision,frameworkNames,compare:view==='compare'},
          view==='daily' && h(DailyReports,{revision,frameworkNames,state:reports})) : selected ? (active ? h(Project,{project:active,frameworkNames,revision:overview.completed,back:()=>select(null),categories,onSave:update}) :
          h(F,null,button('返回项目列表',()=>select(null)),h('p',null,'此项目已从当前索引移除。'))) :
        h(F,null,
          h('details',null,h('summary',null,'导入 ChatGPT 会话'),h('p',null,'选择从 ChatGPT 导出并解压的 conversations.json 或会话分卷。文件仅在本机处理。'),
            h('input',{type:'file',accept:'.json',multiple:true,disabled:busy,onChange:importFiles,'aria-label':'选择 ChatGPT 导出文件'})),
          h(ArchiveFolder,{options:[...new Set(Object.values({...frameworkNames,...overview.data?.detected}))],added:id=>{setSource(id);setStatus('');setCategory('');setQuery('');scan()}}),

          !overview.data ? loading(overview) : h(F,null,
            h('h2',null,'来源'),h('section',{className:'row'},['',...Object.keys(frameworkNames)].map(f=>
              button((frameworkNames[f] || '全部来源')+' · '+projects.filter(p=>!f || p.framework===f).reduce((sum,p)=>sum+p.sessions,0)+' 个会话',
                ()=>{field(setSource,f);setCategory('')},{key:f,'aria-pressed':f===source}))),
            h('details',null,h('summary',null,'来源读取状态与待接入客户端'),Object.entries({...frameworkNames,...overview.data.detected}).map(([id,name])=>h('p',{key:id},name+' · '+(overview.data.coverage[id] || '待下次汇总更新')))),
            source && h('p',null,frameworkNames[source]+' · '+(overview.data.coverage[source] || '待下次汇总更新')),
            overview.data.coverage.unreadable_files ? h('p',null,'有 '+overview.data.coverage.unreadable_files+' 个 Harness 日志暂时无法读取。') : null,
            h('h2',null,'项目分类'),h('section',{className:'row'},[['','全部',scoped.length],['done','已归类',classified],['open','未归类',scoped.length-classified]].map(([v,l,n])=>
              button(l+' '+n,()=>{field(setStatus,v);setCategory('')},{key:v,'aria-pressed':status===v})),
              status!=='open' && h('select',{'aria-label':'按分类筛选',value:category,onChange:e=>field(setCategory,e.target.value)},h('option',{value:''},'所有分类名称'),
                [...new Set(scoped.map(p=>p.category).filter(Boolean))].sort().map(c=>h('option',{key:c},c)))),
            h('div',{className:'row'},h('input',{type:'search',placeholder:'搜索项目名、目录或分类',value:query,onChange:e=>field(setQuery,e.target.value)}),
              h('small',{role:'status'},found.length+' 个项目 · '+found.reduce((a,p)=>a+p.sessions,0)+' 个会话')),
            ...found.slice(pos,pos+20).map(p=>h('article',{key:JSON.stringify([p.framework,p.project_key])},
              button(titleOf(p),()=>select(p),{className:'title'}),h('p',null,frameworkNames[p.framework]+' · '+(p.category?'已归类 / '+p.category:'未归类')+' · '+p.sessions+' 个会话'),
              h('small',null,(p.cwd || '无工作目录')+' · '+stamp(p.updated)))),
            !found.length && h('p',null,source==='chatgpt' && !scoped.length ? '选择上方“导入 ChatGPT 会话”可添加本地记录。' : '没有符合当前筛选条件的项目。'),
            pages(pos,20,setOffset,pos+20<found.length))))
    }

    function apply(ctx) {
      ctx.slots.inject('main', () => ctx.slots.register({ name:'main',key:panelId }, Panel))
      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name:'sidebar.panellist',id:panelId,order:20,label:'会话汇总'
      }, Icon))
    }
    return { inject:['slots'], apply }
  }
})


