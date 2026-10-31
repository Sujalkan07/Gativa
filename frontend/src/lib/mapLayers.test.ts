/**
 * Comprehensive Automated Tests for Centralized Map Tile Provider (mapLayers.ts)
 * Covers TomTom Street Basemap, OSM Fallback, Esri Satellite, TomTom Live Traffic Overlay,
 * Diagnostics (401, 403, 429), Lifecycle Management, and Credential Isolation.
 */

// Lightweight DOM shim so Leaflet can initialize in Node.js test environment
if (typeof (globalThis as any).window === 'undefined') {
  ;(globalThis as any).window = globalThis
  ;(globalThis as any).document = {
    createElement: () => ({ getContext: () => null }),
    documentElement: { style: {} },
  }
  ;(globalThis as any).screen = { deviceXDPI: 96, logicalXDPI: 96 }
  ;(globalThis as any).devicePixelRatio = 1
}

import { describe, it, afterEach } from 'node:test'
import assert from 'node:assert/strict'

// Dynamic import after shim is established
const {
  sanitizeLogUrl,
  maskApiKey,
  buildTomTomMapTileUrl,
  buildTomTomTrafficUrl,
  createTomTomBaseTileLayer,
  attachBaseTileLayer,
  attachTomTomTrafficLayer,
  verifyTomTomMapKey,
} = await import('./mapLayers.ts')

describe('TomTom Street Basemap & Centralized Provider Tests', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  // 1. TomTom base URL construction
  it('1. constructs correct TomTom base map URL according to official Map Display API spec', () => {
    const url = buildTomTomMapTileUrl('test_tomtom_key')
    assert.strictEqual(
      url,
      'https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=test_tomtom_key'
    )
    assert.ok(url.includes('/map/1/tile/basic/main/'))
    assert.ok(!url.includes('/traffic/'))
  })

  // 2. Correct TomTom host cycling
  it('2. supports documented host aliases and subdomain cycling (a, b, c, d)', () => {
    const layer = createTomTomBaseTileLayer('test_key')
    const subdomains = (layer.options as any).subdomains
    assert.deepStrictEqual(subdomains, ['a', 'b', 'c', 'd'])
  })

  // 3. Correct API-key encoding
  it('3. properly URL-encodes special characters in TomTom API key', () => {
    const specialKey = 'key+with/special&chars=yes?value#hash'
    const url = buildTomTomMapTileUrl(specialKey)
    assert.ok(!url.includes('+with/'))
    assert.ok(url.includes(encodeURIComponent(specialKey)))
    assert.strictEqual(
      url,
      `https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=${encodeURIComponent(specialKey)}`
    )
  })

  // 4. TomTom base layer creation
  it('4. creates TomTom base tile layer with correct attribution, maxZoom, and crossOrigin', () => {
    const layer = createTomTomBaseTileLayer('my_key')
    assert.ok(layer.getAttribution()?.includes('TomTom'))
    assert.ok(layer.getAttribution()?.includes('OpenStreetMap'))
    assert.strictEqual(layer.options.maxZoom, 20)
    assert.strictEqual(layer.options.crossOrigin, true)
  })

  // 5. TomTom provider selection when a key exists
  it('5. selects TomTom as primary street basemap when key is configured', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      tomtomApiKey: 'valid_tomtom_key',
      onStatusChange: (s) => statuses.push(s),
    })

    assert.strictEqual(statuses.length, 1)
    assert.strictEqual(statuses[0].provider, 'tomtom')
    assert.strictEqual(statuses[0].displayName, 'TomTom Streets')
    assert.strictEqual(statuses[0].isFallback, false)
    assert.strictEqual(statuses[0].status, 'loading')
    assert.strictEqual(layers.size, 1)

    handle.cleanup()
  })

  // 6. OSM selection when the TomTom key is missing
  it('6. automatically selects OpenStreetMap when TomTom key is missing', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      tomtomApiKey: null,
      onStatusChange: (s) => statuses.push(s),
    })

    assert.strictEqual(statuses.length, 1)
    assert.strictEqual(statuses[0].provider, 'osm')
    assert.strictEqual(statuses[0].displayName, 'OpenStreetMap')
    assert.strictEqual(statuses[0].isFallback, false)
    assert.strictEqual(statuses[0].status, 'active')
    assert.strictEqual(layers.size, 1)

    handle.cleanup()
  })

  // 7. OSM fallback when TomTom verification fails
  it('7. engages automated OSM fallback when TomTom key verification probe fails', async () => {
    // Mock fetch to simulate 401 Unauthorized
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        statusText: 'Unauthorized',
      })

    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      tomtomApiKey: 'bad_key',
      onStatusChange: (s) => statuses.push(s),
    })

    // Wait for async probe to resolve
    await new Promise((resolve) => setTimeout(resolve, 30))

    const latest = statuses[statuses.length - 1]
    assert.strictEqual(latest.provider, 'osm')
    assert.strictEqual(latest.isFallback, true)
    assert.ok(latest.fallbackReason?.includes('HTTP 401'))

    handle.cleanup()
  })

  // 8. TomTom tile-load success status
  it('8. updates status to active ONLY upon actual tileload event', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      tomtomApiKey: 'my_key',
      onStatusChange: (s) => statuses.push(s),
    })

    // Initially status is loading, not active
    assert.strictEqual(statuses[0].status, 'loading')

    // Simulate successful tile loaded by Leaflet
    handle.layer.fire('tileload')

    const activeStatus = statuses[statuses.length - 1]
    assert.strictEqual(activeStatus.provider, 'tomtom')
    assert.strictEqual(activeStatus.status, 'active')

    handle.cleanup()
  })

  // 9. TomTom tile-error handling
  it('9. avoids switching on isolated tile error, triggers fallback after 3 consecutive errors', async () => {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ error: 'Quota exceeded' }), {
        status: 429,
        statusText: 'Too Many Requests',
      })

    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      tomtomApiKey: 'key_429',
      onStatusChange: (s) => statuses.push(s),
    })

    const initialLayer = handle.layer

    // Fire 2 tile errors: must NOT trigger fallback yet
    initialLayer.fire('tileerror')
    initialLayer.fire('tileerror')
    assert.strictEqual(statuses[statuses.length - 1].provider, 'tomtom')

    // Fire 3rd tile error: must trigger fallback to OSM
    initialLayer.fire('tileerror')

    // Wait for diag probe
    await new Promise((resolve) => setTimeout(resolve, 30))

    const fallbackStatus = statuses[statuses.length - 1]
    assert.strictEqual(fallbackStatus.provider, 'osm')
    assert.strictEqual(fallbackStatus.isFallback, true)

    // Subsequent tile errors must not trigger duplicate fallbacks (loop prevention)
    const count = statuses.length
    initialLayer.fire('tileerror')
    assert.strictEqual(statuses.length, count)

    handle.cleanup()
  })

  // 10. 401, 403 and 429 diagnostics
  it('10. distinguishes HTTP 401, 403, 429, and 500 error diagnostics', async () => {
    // Test 401
    globalThis.fetch = async () => new Response('', { status: 401 })
    const diag401 = await verifyTomTomMapKey('invalid_key')
    assert.strictEqual(diag401.valid, false)
    assert.strictEqual(diag401.statusCode, 401)
    assert.ok(diag401.reason?.includes('HTTP 401: Invalid or unauthorized TomTom API key'))

    // Test 403
    globalThis.fetch = async () => new Response('', { status: 403 })
    const diag403 = await verifyTomTomMapKey('forbidden_key')
    assert.strictEqual(diag403.valid, false)
    assert.strictEqual(diag403.statusCode, 403)
    assert.ok(diag403.reason?.includes('HTTP 403: Forbidden, permission denied or domain restriction'))

    // Test 429
    globalThis.fetch = async () => new Response('', { status: 429 })
    const diag429 = await verifyTomTomMapKey('rate_limited_key')
    assert.strictEqual(diag429.valid, false)
    assert.strictEqual(diag429.statusCode, 429)
    assert.ok(diag429.reason?.includes('HTTP 429: TomTom quota or rate limit exceeded'))

    // Test 500
    globalThis.fetch = async () => new Response('', { status: 500 })
    const diag500 = await verifyTomTomMapKey('server_error_key')
    assert.strictEqual(diag500.valid, false)
    assert.strictEqual(diag500.statusCode, 500)
    assert.ok(diag500.reason?.includes('HTTP 500: TomTom provider service failure'))
  })

  // 11. Traffic overlay remains independent of the base layer
  it('11. manages live traffic overlay independently from the street basemap', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    // 1. Add basemap
    const baseHandle = attachBaseTileLayer(mockMap, 'streets', { tomtomApiKey: 'k1' })
    assert.strictEqual(layers.size, 1)

    // 2. Add traffic overlay
    const trafficHandle = attachTomTomTrafficLayer(mockMap, { apiKey: 'k1' })
    assert.strictEqual(layers.size, 2)
    assert.ok(trafficHandle.layer)
    assert.strictEqual((trafficHandle.layer.options as any).opacity, 0.85)

    // 3. Remove traffic overlay: basemap remains intact!
    trafficHandle.cleanup()
    assert.strictEqual(layers.size, 1)
    assert.strictEqual(mockMap.hasLayer(baseHandle.layer), true)

    baseHandle.cleanup()
    assert.strictEqual(layers.size, 0)
  })

  // 12. Traffic overlay is not mistaken for a complete basemap
  it('12. ensures traffic overlay uses Traffic API v4 endpoint while basemap uses Maps API v1', () => {
    const mapTileUrl = buildTomTomMapTileUrl('k1')
    const trafficTileUrl = buildTomTomTrafficUrl('k1')

    assert.ok(mapTileUrl.includes('/map/1/tile/basic/main/'))
    assert.ok(trafficTileUrl.includes('/traffic/map/4/tile/flow/relative0/'))
    assert.notStrictEqual(mapTileUrl, trafficTileUrl)
  })

  // 13. Satellite provider still works
  it('13. preserves functional Esri satellite basemap provider', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'satellite', {
      onStatusChange: (s) => statuses.push(s),
    })

    assert.strictEqual(statuses[0].provider, 'esri')
    assert.strictEqual(statuses[0].displayName, 'Esri Satellite')
    assert.strictEqual(statuses[0].status, 'active')
    assert.ok(handle.layer.getAttribution()?.includes('Esri'))

    handle.cleanup()
  })

  // 14. Cleanup removes all listeners and layers
  it('14. cleanup thoroughly detaches tile listeners and removes layer from map', () => {
    let removeCalled = false
    const mockMap = {
      hasLayer: () => true,
      addLayer: () => {},
      removeLayer: () => {
        removeCalled = true
      },
    } as any

    const handle = attachBaseTileLayer(mockMap, 'streets', { tomtomApiKey: 'k' })
    handle.cleanup()

    assert.strictEqual(removeCalled, true)
  })

  // 15. Switching between providers does not leave duplicate tile layers
  it('15. switching between providers cleans up prior layers without accumulating duplicates', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    // 1. TomTom
    const h1 = attachBaseTileLayer(mockMap, 'streets', { tomtomApiKey: 'k' })
    assert.strictEqual(layers.size, 1)

    // Switch to satellite
    h1.cleanup()
    const h2 = attachBaseTileLayer(mockMap, 'satellite')
    assert.strictEqual(layers.size, 1)

    // Switch to OSM
    h2.cleanup()
    const h3 = attachBaseTileLayer(mockMap, 'osm')
    assert.strictEqual(layers.size, 1)

    // Final cleanup
    h3.cleanup()
    assert.strictEqual(layers.size, 0)
  })

  // Additional sanity tests for utilities
  it('redacts sensitive credentials in logs and mask helper', () => {
    const raw = 'https://api.tomtom.com/map/1/tile/basic/main/0/0/0.png?key=super_secret_key_1234'
    const redacted = sanitizeLogUrl(raw)
    assert.ok(!redacted.includes('super_secret_key_1234'))
    assert.ok(redacted.includes('key=REDACTED'))

    assert.strictEqual(maskApiKey('abcdefgh12345678'), 'abcd...5678')
    assert.strictEqual(maskApiKey(null), '[NOT CONFIGURED]')
  })
})
