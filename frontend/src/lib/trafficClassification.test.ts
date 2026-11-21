import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { escapeHtml } from './sanitize.ts'
import { classifyTrafficFlow } from './trafficClassification.ts'

describe('Security & Sanitization Tests (Leaflet XSS Remediation)', () => {
  it('escapes standard HTML injection characters properly', () => {
    const malicious = '<script>alert("XSS")</script>'
    const clean = escapeHtml(malicious)
    assert.equal(clean, '&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;')
    assert.ok(!clean.includes('<script>'))
  })

  it('handles null, undefined, numbers and safe strings cleanly', () => {
    assert.equal(escapeHtml(null), '')
    assert.equal(escapeHtml(undefined), '')
    assert.equal(escapeHtml(42), '42')
    assert.equal(escapeHtml('Normal Text'), 'Normal Text')
  })

  it('escapes single and double quotes and ampersands', () => {
    assert.equal(escapeHtml(`Tom & Jerry's "Adventure"`), `Tom &amp; Jerry&#39;s &quot;Adventure&quot;`)
  })
})

describe('Unified Traffic Classification (SCI) Tests', () => {
  it('identifies road closures correctly', () => {
    const res = classifyTrafficFlow(0, 50, true)
    assert.equal(res.grade, 'SCI CLOSED')
    assert.equal(res.tier, 'closed')
    assert.equal(res.label, 'Road Closed')
    assert.equal(res.mapColor, '#1e1b18')
  })

  it('identifies unsampled segments when speed data is absent', () => {
    const res = classifyTrafficFlow(null, 50, false)
    assert.equal(res.grade, '—')
    assert.equal(res.tier, 'unknown')
    assert.equal(res.label, 'Unsampled')
    assert.equal(res.ratio, null)
  })

  it('grades optimal free flow (SCI A: >=85%)', () => {
    const res = classifyTrafficFlow(50, 50, false)
    assert.equal(res.grade, 'SCI A')
    assert.equal(res.tier, 'free_flow')
    assert.equal(res.label, 'Optimal (≥85%)')
    assert.equal(res.mapColor, '#138808')
  })

  it('grades minor slowdown (SCI B: 70-85%) with unified green/mild color', () => {
    // 28 km/h on 37 km/h road = 75.6% -> SCI B
    const res = classifyTrafficFlow(28, 37, false)
    assert.equal(res.grade, 'SCI B')
    assert.equal(res.tier, 'free_flow')
    assert.equal(res.label, 'Minor Slowdown (70-85%)')
    assert.equal(res.mapColor, '#16a34a')
  })

  it('grades moderate delays (SCI C: 55-70%)', () => {
    const res = classifyTrafficFlow(30, 50, false) // 60%
    assert.equal(res.grade, 'SCI C')
    assert.equal(res.tier, 'moderate')
    assert.equal(res.mapColor, '#ff9933')
  })

  it('grades heavy delays (SCI D: 40-55%)', () => {
    const res = classifyTrafficFlow(22, 50, false) // 44%
    assert.equal(res.grade, 'SCI D')
    assert.equal(res.tier, 'moderate')
    assert.equal(res.mapColor, '#ea580c')
  })

  it('grades severe bottlenecks (SCI E: 28-40%)', () => {
    const res = classifyTrafficFlow(16, 50, false) // 32%
    assert.equal(res.grade, 'SCI E')
    assert.equal(res.tier, 'severe')
    assert.equal(res.mapColor, '#dc2626')
  })

  it('grades severe breakdown (SCI F: <28%)', () => {
    const res = classifyTrafficFlow(10, 50, false) // 20%
    assert.equal(res.grade, 'SCI F')
    assert.equal(res.tier, 'severe')
    assert.equal(res.mapColor, '#ba1a1a')
  })
})
