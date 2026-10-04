// The dev server's proxy to a detector, used by vite.compute.config.js. Pure, so it can be tested.

export const COMPUTE_DETECTOR_URL = 'https://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector'

// /api, /evidence and /ws go to the detector. The key rides on /api only (it guards starting,
// feeding and stopping sessions) and is added by the dev server, so it never reaches the browser.
export function detectorProxy(target, key) {
  const base = target.replace(/\/+$/, '')
  const api = { target: base, changeOrigin: true }
  if (key) api.headers = { 'X-Detector-Key': key }
  return {
    '/api': api,
    '/evidence': { target: base, changeOrigin: true },
    '/ws': { target: base.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
  }
}

// DETECTOR_KEY from the environment, else from backend/.env.compute (written by scripts/deploy_detector.sh).
export function detectorKey(env, computeEnvText) {
  if (env.DETECTOR_KEY) return env.DETECTOR_KEY.trim()
  const line = (computeEnvText || '').split(/\r?\n/).find((l) => l.startsWith('DETECTOR_KEY='))
  return line ? line.slice('DETECTOR_KEY='.length).trim().replace(/^(['"])(.*)\1$/, '$2') : ''
}
