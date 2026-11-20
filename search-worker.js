import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

// One line per request. A persistent Python interpreter keeps the verified ONNX session warm.
export function searchWorker(python, backend) {
  let current
  let nextId=0
  function start() {
    const child=spawn(python,['-B','-X','utf8',backend,'--search-worker'],{windowsHide:true,stdio:['pipe','pipe','pipe']})
    const pending=new Map()
    const state={child,pending}
    current=state
    let lastError=''
    child.stderr.setEncoding('utf8').on('data',s=>{lastError=(lastError+s).slice(-500)})
    function end(error) {
      if(current===state) current=null
      for(const {reject} of pending.values()) reject(error)
      pending.clear()
    }
    child.stdin.on('error',end)
    child.once('error',end)
    child.once('close',()=>end(new Error(lastError || '本地语义检索进程已退出')))
    createInterface({input:child.stdout}).on('line',line=>{
      try {
        const {id,result,error}=JSON.parse(line)
        const request=pending.get(id)
        pending.delete(id)
        if (error) request?.reject(new Error(error))
        else request?.resolve(result)
      } catch(error){child.kill();end(error)}
    })
    return state
  }
  return {
    run(args,signal) {
      const {child,pending}=current || start()
      const id=++nextId
      return new Promise((resolve,reject)=>{
        if(signal?.aborted) return reject(new Error('检索已取消'))
        const cancel=()=>{pending.delete(id);reject(new Error('检索已取消'))}
        signal?.addEventListener('abort',cancel,{once:true})
        pending.set(id,{resolve:value=>{signal?.removeEventListener('abort',cancel);resolve(value)},
                        reject:error=>{signal?.removeEventListener('abort',cancel);reject(error)}})
        child.stdin.write(JSON.stringify({id,args})+'\n')
      })
    },
    stop(){current?.child.kill()}
  }
}

