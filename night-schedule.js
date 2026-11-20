// The Harness service owns this timer. Closing a renderer panel has no effect on it.
export function startNightly(run, hour, clock = Date.now, intervalMs = 60_000) {
  const controller = new AbortController()
  const state = { running:false, error:'', hour }
  let completedPeriod = ''
  let retryAt = 0

  async function tick() {
    const now = clock()
    const local = new Date(now + 8 * 3600_000)
    if (local.getUTCHours() < hour) local.setUTCDate(local.getUTCDate()-1)
    const period = local.toISOString().slice(0,10)
    if (state.running || completedPeriod === period || now < retryAt || controller.signal.aborted) return
    state.running = true
    try {
      const result = await run(controller.signal)
      state.error = ''
      if (result.partial) retryAt = now + 15 * 60_000
      else { completedPeriod = period; retryAt = 0 }
    } catch (err) {
      state.error = String(err.message || err)
      retryAt = now + 5 * 60_000
    } finally {
      state.running = false
    }
  }
  const timer = setInterval(tick, intervalMs)
  timer.unref?.()
  void tick()
  return {state, tick, stop() {clearInterval(timer);controller.abort()} }
}

