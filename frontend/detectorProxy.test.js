// node --test frontend/detectorProxy.test.js
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { COMPUTE_DETECTOR_URL, detectorKey, detectorProxy } from './detectorProxy.js'

test('the proxy keeps the Compute path and switches /ws to wss', () => {
  const proxy = detectorProxy(`${COMPUTE_DETECTOR_URL}/`, '')
  assert.equal(proxy['/api'].target, COMPUTE_DETECTOR_URL)
  assert.equal(proxy['/evidence'].target, COMPUTE_DETECTOR_URL)
  assert.equal(proxy['/ws'].target, 'wss://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector')
  assert.equal(proxy['/ws'].ws, true)
  assert.equal(proxy['/api'].changeOrigin, true)
})

test('the key goes on /api only, and only when there is one', () => {
  const withKey = detectorProxy(COMPUTE_DETECTOR_URL, 'k1')
  assert.deepEqual(withKey['/api'].headers, { 'X-Detector-Key': 'k1' })
  assert.equal(withKey['/evidence'].headers, undefined)
  assert.equal(withKey['/ws'].headers, undefined)
  assert.equal(detectorProxy(COMPUTE_DETECTOR_URL, '')['/api'].headers, undefined)
})

test('a local detector over http gets ws', () => {
  assert.equal(detectorProxy('http://localhost:8000', '')['/ws'].target, 'ws://localhost:8000')
})

test('detectorKey prefers the environment, then backend/.env.compute', () => {
  const file = 'GEMINI_API_KEY=g\r\nDETECTOR_KEY=fromfile\r\n'
  assert.equal(detectorKey({ DETECTOR_KEY: ' fromenv ' }, file), 'fromenv')
  assert.equal(detectorKey({}, file), 'fromfile')
  assert.equal(detectorKey({}, 'DETECTOR_KEY="quoted"\n'), 'quoted')
  assert.equal(detectorKey({}, 'GEMINI_API_KEY=g\n'), '')
  assert.equal(detectorKey({}, ''), '')
})
