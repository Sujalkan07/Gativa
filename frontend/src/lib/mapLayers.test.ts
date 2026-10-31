/**
 * Unit Tests for Centralized Map Tile Provider (mapLayers.ts)
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

import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

// Dynamic import after shim is established
const {
  getCartoBasemapApiKey,
  sanitizeLogUrl,
  maskApiKey,
  buildCartoVoyagerUrl,
  buildTomTomTrafficUrl,
  CARTO_VOYAGER_URL,
  OSM_TILE_URL,
  createOsmTileLayer,
  createEsriSatelliteTileLayer,
  createCartoVoyagerTileLayer,
  createBaseTileLayer,
  attachBaseTileLayer,
  attachTomTomTrafficLayer,
  verifyCartoKey,
  verifyTomTomKey,
} = await import('./mapLayers.ts')

describe('Map Tile Provider Utilities', () => {
  it('correctly identifies placeholder and invalid CARTO keys', () => {
    assert.strictEqual(getCartoBasemapApiKey(), null)
  })

  it('redacts sensitive credentials from URLs and strings', () => {
    const rawUrl = 'https://api.tomtom.com/traffic/map/4/tile/flow/relative0/1/2/3.png?key=secret_12345'
    const sanitized = sanitizeLogUrl(rawUrl)
    assert.ok(!sanitized.includes('secret_12345'))
    assert.ok(sanitized.includes('key=REDACTED'))

    const cartoRaw = 'https://a.basemaps.cartocdn.com/rastertiles/voyager/1/2/3.png?api_key=carto_secret_6789'
    const cartoSanitized = sanitizeLogUrl(cartoRaw)
    assert.ok(!cartoSanitized.includes('carto_secret_6789'))
    assert.ok(cartoSanitized.includes('api_key=REDACTED'))
  })

  it('masks API keys safely without exposing full secrets', () => {
    assert.strictEqual(maskApiKey(null), '[NOT CONFIGURED]')
    assert.strictEqual(maskApiKey(''), '[NOT CONFIGURED]')
    assert.strictEqual(maskApiKey('12345'), '***')
    assert.strictEqual(maskApiKey('my-secret-production-key-99'), 'my-s...y-99')
  })

  it('builds CARTO Voyager URL with API key when configured, or OSM when missing', () => {
    const fallbackUrl = buildCartoVoyagerUrl(null)
    assert.strictEqual(fallbackUrl, OSM_TILE_URL)

    const keyUrl = buildCartoVoyagerUrl('test_carto_key')
    assert.strictEqual(keyUrl, `${CARTO_VOYAGER_URL}?key=test_carto_key`)
  })

  it('builds TomTom traffic URL strictly with TomTom credentials', () => {
    const ttUrl = buildTomTomTrafficUrl('test_tomtom_key')
    assert.ok(ttUrl.includes('api.tomtom.com/traffic/map/4/tile/flow/relative0/'))
    assert.ok(ttUrl.endsWith('?key=test_tomtom_key'))
    assert.ok(!ttUrl.includes('carto'))
  })

  it('enforces strict credential isolation between CARTO and TomTom', () => {
    const cartoKey = 'carto_secret_key'
    const tomtomKey = 'tomtom_secret_key'

    const cartoUrl = buildCartoVoyagerUrl(cartoKey)
    const tomtomUrl = buildTomTomTrafficUrl(tomtomKey)

    assert.ok(!cartoUrl.includes(tomtomKey))
    assert.ok(!tomtomUrl.includes(cartoKey))
  })

  it('creates OSM layer with correct attribution and options', () => {
    const layer = createOsmTileLayer()
    assert.strictEqual(layer.getAttribution(), '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors')
    assert.strictEqual(layer.options.maxZoom, 19)
  })

  it('creates Esri Satellite layer with correct attribution and options', () => {
    const layer = createEsriSatelliteTileLayer()
    assert.ok(layer.getAttribution()?.includes('Esri'))
    assert.strictEqual(layer.options.maxZoom, 19)
  })

  it('creates CARTO Voyager layer with key and attribution', () => {
    const layer = createCartoVoyagerTileLayer('valid_key')
    assert.ok(layer.getAttribution()?.includes('CARTO'))
    assert.strictEqual(layer.options.maxZoom, 20)
  })

  it('creates base tile layer selecting OSM when CARTO key is missing', () => {
    const layer = createBaseTileLayer('streets', { cartoApiKey: null })
    assert.strictEqual(layer.options.maxZoom, 19)
    assert.strictEqual(layer.getAttribution(), '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors')
  })

  it('creates base tile layer selecting CARTO when CARTO key is present', () => {
    const layer = createBaseTileLayer('streets', { cartoApiKey: 'valid_carto_key' })
    assert.strictEqual(layer.options.maxZoom, 20)
    assert.ok(layer.getAttribution()?.includes('CARTO'))
  })

  it('creates base tile layer selecting Esri Satellite when requested', () => {
    const layer = createBaseTileLayer('satellite')
    assert.ok(layer.getAttribution()?.includes('Esri'))
  })

  it('correctly handles missing TomTom key without crashing', () => {
    const mockMap = {
      hasLayer: () => false,
      removeLayer: () => {},
      addLayer: () => {},
    } as any

    const handle = attachTomTomTrafficLayer(mockMap, { apiKey: null })
    assert.strictEqual(handle.layer, null)
    assert.strictEqual(handle.getStatus().enabled, false)
    assert.strictEqual(handle.getStatus().status, 'error')
    assert.ok(handle.getStatus().errorMessage?.includes('not configured'))
    handle.cleanup()
  })

  it('diagnoses missing keys properly', async () => {
    const cartoDiag = await verifyCartoKey(null)
    assert.strictEqual(cartoDiag.valid, false)
    assert.ok(cartoDiag.reason?.includes('not configured'))

    const tomtomDiag = await verifyTomTomKey(null)
    assert.strictEqual(tomtomDiag.valid, false)
    assert.ok(tomtomDiag.reason?.includes('not configured'))
  })

  it('manages base layer lifecycle and cleanup cleanly', () => {
    let removedLayer: any = null
    const layers = new Set<any>()

    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => {
        layers.add(l)
      },
      removeLayer: (l: any) => {
        layers.delete(l)
        removedLayer = l
      },
    } as any

    // 1. Attach streets without CARTO key -> should use OSM
    const statuses: any[] = []
    const handleStreets = attachBaseTileLayer(mockMap, 'streets', {
      cartoApiKey: null,
      onStatusChange: (s) => statuses.push(s),
    })

    assert.strictEqual(statuses.length, 1)
    assert.strictEqual(statuses[0].provider, 'osm')
    assert.strictEqual(statuses[0].isFallback, false)
    assert.strictEqual(layers.size, 1)

    // Cleanup streets
    handleStreets.cleanup()
    assert.strictEqual(layers.size, 0)
    assert.strictEqual(removedLayer, handleStreets.layer)

    // 2. Attach satellite
    const handleSatellite = attachBaseTileLayer(mockMap, 'satellite', {
      onStatusChange: (s) => statuses.push(s),
    })

    assert.strictEqual(statuses[1].provider, 'esri')
    assert.strictEqual(layers.size, 1)

    handleSatellite.cleanup()
    assert.strictEqual(layers.size, 0)
  })

  it('triggers OSM fallback on repeated CARTO tile errors', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachBaseTileLayer(mockMap, 'streets', {
      cartoApiKey: 'some_carto_key',
      onStatusChange: (s) => statuses.push(s),
    })

    // Initial status should be CARTO loading
    assert.strictEqual(statuses[0].provider, 'carto')
    assert.strictEqual(statuses[0].status, 'loading')

    const initialLayer = handle.layer

    // Fire 2 tile errors: should not switch yet (avoid isolated failure false positives)
    initialLayer.fire('tileerror')
    initialLayer.fire('tileerror')
    assert.strictEqual(statuses.length, 1)

    // Fire 3rd tile error: should trigger fallback to OSM
    initialLayer.fire('tileerror')

    const latestStatus = statuses[statuses.length - 1]
    assert.strictEqual(latestStatus.provider, 'osm')
    assert.strictEqual(latestStatus.isFallback, true)
    assert.ok(latestStatus.fallbackReason?.includes('Repeated tile loading failures'))

    // Subsequent tile errors do NOT re-trigger fallback (loop prevention)
    const countBefore = statuses.length
    initialLayer.fire('tileerror')
    assert.strictEqual(statuses.length, countBefore)

    handle.cleanup()
  })

  it('reports TomTom traffic active only upon successful tileload', () => {
    const layers = new Set<any>()
    const mockMap = {
      hasLayer: (l: any) => layers.has(l),
      addLayer: (l: any) => layers.add(l),
      removeLayer: (l: any) => layers.delete(l),
    } as any

    const statuses: any[] = []
    const handle = attachTomTomTrafficLayer(mockMap, {
      apiKey: 'test_tomtom_key',
      onStatusChange: (s) => statuses.push(s),
    })

    assert.ok(handle.layer)
    // Initial status must be loading, NOT active
    assert.strictEqual(statuses[0].status, 'loading')
    assert.strictEqual(statuses[0].successCount, 0)

    // Fire tileload
    handle.layer.fire('tileload')
    const activeStatus = statuses[statuses.length - 1]
    assert.strictEqual(activeStatus.status, 'active')
    assert.strictEqual(activeStatus.successCount, 1)

    handle.cleanup()
  })
})
