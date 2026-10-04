// `npm run dev:compute`: the dashboard against the detector on Supabase Compute, at http://localhost:5174.
// vite.config.js stays on the local detector (port 5173), which scripts/run_e2e.sh uses.
// Starting, feeding or stopping a session needs the detector's key: DETECTOR_KEY in the environment,
// or backend/.env.compute from scripts/deploy_detector.sh. Without it, watching still works.
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { COMPUTE_DETECTOR_URL, detectorKey, detectorProxy } from './detectorProxy.js'

function computeEnv() {
  try {
    return readFileSync(new URL('../backend/.env.compute', import.meta.url), 'utf8')
  } catch {
    return ''
  }
}

const target = process.env.DETECTOR_URL || COMPUTE_DETECTOR_URL
const key = detectorKey(process.env, computeEnv())
console.log(`Detector: ${target} (${key ? 'key set' : 'no DETECTOR_KEY: starting or stopping streams will get 401'})`)

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true, proxy: detectorProxy(target, key) },
})
