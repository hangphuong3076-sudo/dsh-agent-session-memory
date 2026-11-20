import { homedir } from 'node:os'
import { join } from 'node:path'
import { searchWorker } from './search-worker.js'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { startNightly } from './night-schedule.js'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'dsh-agent-session-memory'
export const inject = ['connection']
const backend = fileURLToPath(new URL('./memory.py', import.meta.url))

function backendCall(request, python, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-X', 'utf8', backend], {
      windowsHide: true, signal, stdio: ['pipe', 'pipe', 'pipe']
    })
    let stdout = '', stderr = ''
    child.stdout.setEncoding('utf8').on('data', s => { stdout += s })
    child.stderr.setEncoding('utf8').on('data', s => { stderr += s })
    child.once('error', reject)
    child.stdin.on('error', reject)
    child.once('close', code => {
      if (code !== 0) return reject(new Error(stderr.trim().split('\n').pop() || '本机检索进程未完成'))
      try { resolve(JSON.parse(stdout)) } catch (error) { reject(error) }
    })
    child.stdin.end(JSON.stringify(request))
  })
}

export function apply(ctx, config = {}) {
  const python = process.env.AGENT_MEMORY_PYTHON || config.python || 'python'
  const privatePython=join(homedir(),'.dsh','storages','agent-session-memory','minilm-runtime','Scripts','python.exe')
  const modelPython=existsSync(privatePython)?privatePython:python
  const worker=searchWorker(modelPython,backend)
  async function call(args,signal) {
    if(args.op==='pair_search' || args.op==='search' || (args.op==='segments' && args.query)) {
      try {return await worker.run(args,signal)}
      catch(err) {
        if(signal?.aborted) throw err
        const result=await backendCall(args,python,signal)
        return {...result,semantic_error:result.semantic_error || String(err.message || err)}
      }
    }
    const result=await backendCall(args,python,signal)
    if(args.op==='manual_refresh' || args.op==='nightly') {
      try {result.minilm=await backendCall({op:'minilm_index'},modelPython,signal)}
      catch(err){if(signal?.aborted) throw err;result.minilm={error:String(err.message || err)}}
    }
    return result
  }
  const hour = Number(config.nightlyHour ?? 23)
  if (!Number.isInteger(hour) || hour<0 || hour>23) throw new Error('nightlyHour 需为 0 至 23 的整数')
  let manualRun
  let nightly
  ctx.effect(() => {
    nightly = startNightly(async signal => {await manualRun;return call({op:'nightly',hour},signal)}, hour)
    return () => {nightly.stop();worker.stop()}
  })
  ctx.connection.fetch.register({
    path: '/api/session-memory.overview',
    methods: ['GET', 'POST'],
    requestBody: 'buffered',
    async fetch(request) {
      const query = new URL(request.url).searchParams
      try {
        let args
        if (request.method === 'POST') {
          const body = await request.json()
          if (body.op==='manual_refresh') {
            if (nightly.state.running) throw new Error('晚间汇总正在运行，完成后可查看结果。')
            manualRun ??= call({op:'manual_refresh',hour}).finally(()=>{manualRun=null})
            return Response.json(await manualRun)
          }
          if (!['classify','import_chatgpt','register_archive','pair_search','pair_compare','latest_pair'].includes(body.op)) throw new Error('不支持此操作')
          args = body
        } else if (query.has('reports')) {
          args = {op:'reports'}
        } else if (query.has('report')) {
          args = {op:'report',day:query.get('report')}
        } else if (query.has('vectors')) {
          args = {op:'vectors',sort:query.get('sort') || 'relevance',query:query.get('vectors'),day:query.get('day') || null}
        } else if (query.has('segments')) {
          args={op:'segments',session:query.get('segments'),query:query.get('q') || '',offset:Number(query.get('offset') || 0)}
        } else if (query.has('locations')) {
          args={op:'locations',query:query.get('locations'),session:query.get('session'),offset:Number(query.get('offset') || 0)}
        } else if (query.has('evidence')) {
          args = {op:'evidence',session:query.get('session'),reference:query.get('evidence')}
        } else if (query.has('session')) {
          args = {op:'transcript',session:query.get('session'),offset:Number(query.get('offset') || 0)}
        } else if (query.has('project')) {
          args = {op:'project',project:query.get('project'),framework:query.get('framework') || 'dsh',offset:Number(query.get('offset') || 0)}
        } else {
          args = {op:'overview'}
        }
        const result = await call(args,request.signal)
        if (args.op === 'reports') result.schedule = nightly.state
        return Response.json(result,
          { headers: { 'Cache-Control': 'no-store' } })
      } catch (err) {
        return Response.json({ error: String(err.message || err) }, { status: 503 })
      }
    }
  })


  ctx.inject(['tools'], scoped => registerTools(scoped, call))
}

function registerTools(ctx, call) {
  const definitions = [
    ['memory_search_daily_reports', 'vectors',
      '用户查询晚间汇总、项目日报或按内容找以前的结论时使用本地日报与原文片段的向量索引。返回日期、来源、说话人、原文引用和相关度，可用 memory_daily_evidence 展开。',
      { query: {type:'string',required:true,description:'检索的主题或问题'},day: {type:'string',description:'可选的北京时间日期 YYYY-MM-DD'} }],
    ['memory_daily_evidence','evidence',
      '展开方案比较、日报或向量结果指定的原文引用及前后消息，保留用户与助手角色。',
      { session:{type:'string',required:true,description:'结果内会话标识'},reference:{type:'string',required:true,description:'结果内引用标识'},offset:{type:'integer',description:'原话字符偏移；可用向量命中的 offset 定位长消息'} }],
    ['memory_find_sessions', 'search',
      '用户提到“刚才的讨论”“之前的方案”、要求按关键词或相关内容找几个历史会话时调用。提取最具辨识度的关键词（例如 SVG 排版）；跨项目按相关度列出编号、来源框架、标题、项目路径和原话。接续时等用户选一个序号；比较方案时让用户选两个序号，再调用 memory_compare_sessions。',
      { sort:{type:'string',description:'relevance 按相关度，newest 从新到旧，oldest 从旧到新'},query: { type: 'string', required: true, description: '用户给出的关键词或主题描述，去掉检索指令本身；仅说刚才且无主题时传空字符串，返回最近列表' } }],
    ['memory_compare_sessions','compare_choices',
      '用户在本次关键词候选中明确选择两个不同序号后，比较两个会话的需求、方案、理由、用户调整和时间依据。按引用报告 A/B 两侧证据，区分助手陈述与验证。缺失信息留空。可在侧栏「比较方案」打开最近一次聊天比较，逐项查看原话，也可用 memory_daily_evidence 读取引用。',
      {first:{type:'integer',required:true,description:'用户选定的第一个候选序号'},second:{type:'integer',required:true,description:'用户选定的第二个候选序号'}}],
    ['memory_continue_session', 'select',
      '用户明确选择上一次候选中的序号后调用。在本聊天恢复选定项目的相关原话、最近进展和工具活动。用户要求继续开发时核对所选绝对路径和当前文件，再用宿主开发工具实际工作。不要在其他项目中写同名文件。',
      { number: { type: 'integer', required: true, description: '用户选择的候选序号，从 1 开始' } }],
    ['memory_read_quote', 'quote',
      '读取已选会话中给定引用的准确原文、角色、相邻发言；长消息可继续翻页。',
      { reference: { type: 'string', required: true, description: '候选或交接内容给出的消息引用' },
        offset: { type: 'integer', description: '字符偏移，默认 0' } }]
  ]
  ctx.effect(() => {
    const dispose = definitions.map(([name, op, description, parameters]) =>
      ctx.tools.register(defineTool({ name, description, parameters, timeoutMs: 180000,
        output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
        async execute(args, exec) {
          const chat = exec.agent?.session?.id
          if (!chat) throw new Error('请从 DeepSeek Harness 会话内使用此工具。')
          const result = await call({ ...args, op, chat },exec.signal)
          if (op === 'evidence' && !result.missing) {
            const chars=Array.from(result.text)
            const offset=Math.min(chars.length,Math.max(0,args.offset ?? 0))
            result.text=chars.slice(offset,offset+3000).join('')
            result.offset=offset
            result.total_chars=chars.length
          }
          if (op === 'select') result.project_directory_available = !!result.project && existsSync(result.project)
          return result
        }
      })))
    return () => dispose.forEach(fn => fn())
  })
}

