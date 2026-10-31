/**
 * Centralized Map Tile Provider & Intelligent Error-Resilient Layer Manager
 *
 * Supports:
 * - CARTO Voyager street basemap with VITE_CARTO_BASEMAP_API_KEY authentication
 * - OpenStreetMap fallback when CARTO key is missing or when tiles fail to load
 * - Esri World Imagery satellite basemap
 * - TomTom Live Traffic Flow tile overlay (isolated from basemap credentials)
 *
 * Requirements:
 * - Strict isolation: CARTO key is never passed to TomTom; TomTom key is never passed to CARTO.
 * - Sensitive credentials are never exposed in user-facing UI, diagnostics, or console logs.
 * - Controlled fallback prevents infinite recursion.
 * - Live traffic status only reports active after successful tile requests.
 */

import L from 'leaflet'

export type BaseLayerType = 'streets' | 'satellite'
export type BaseMapProviderId = 'carto' | 'osm' | 'esri'
export type TrafficLayerStatusState = 'idle' | 'loading' | 'active' | 'error'

export interface BaseMapStatus {
  provider: BaseMapProviderId
  displayName: string
  isFallback: boolean
  fallbackReason?: string
  status: 'active' | 'loading' | 'error'
  errorDetails?: string
}

export interface TrafficLayerStatus {
  enabled: boolean
  status: TrafficLayerStatusState
  errorMessage?: string
  successCount: number
  errorCount: number
}

// ─── Standard Tile URLs & Attribution Constants ───────────────────────────────

export const CARTO_VOYAGER_URL = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
export const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'

export const OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'

export const ESRI_SATELLITE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
export const ESRI_ATTRIBUTION =
  'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'

export const TOMTOM_TRAFFIC_URL_TEMPLATE =
  'https://{s}.api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png'
export const TOMTOM_ATTRIBUTION =
  '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom Traffic</a>'

// ─── Environment Accessors ─────────────────────────────────────────────────────

function readEnvVar(name: string): string | null {
  try {
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env[name]) {
      return String(import.meta.env[name])
    }
  } catch {
    // Ignore in non-vite contexts
  }
  try {
    const g = globalThis as unknown as { process?: { env?: Record<string, string | undefined> } }
    if (g.process?.env?.[name]) {
      return String(g.process.env[name])
    }
  } catch {
    // Ignore in non-node contexts
  }
  return null
}

const PLACEHOLDER_STRINGS = new Set([
  'your_carto_api_key_here',
  'actual_carto_key',
  'your_tomtom_api_key_here',
  'actual_tomtom_key',
  'your_api_key_here',
  'your_key_here',
])

/**
 * Retrieve CARTO basemap API key from environment, ensuring placeholders are rejected.
 */
export function getCartoBasemapApiKey(): string | null {
  const val = readEnvVar('VITE_CARTO_BASEMAP_API_KEY')
  if (!val || typeof val !== 'string') return null
  const trimmed = val.trim()
  if (!trimmed || PLACEHOLDER_STRINGS.has(trimmed.toLowerCase())) {
    return null
  }
  return trimmed
}

/**
 * Retrieve TomTom Traffic API key from environment, ensuring placeholders are rejected.
 */
export function getTomTomApiKey(): string | null {
  const val = readEnvVar('VITE_TOMTOM_API_KEY')
  if (!val || typeof val !== 'string') return null
  const trimmed = val.trim()
  if (!trimmed || PLACEHOLDER_STRINGS.has(trimmed.toLowerCase())) {
    return null
  }
  return trimmed
}

/**
 * Safely redact API keys from strings, URLs, and logs.
 */
export function sanitizeLogUrl(url: string): string {
  return url.replace(/([?&](?:key|api_key)=)[^&]+/gi, '$1REDACTED')
}

export function maskApiKey(key?: string | null): string {
  if (!key) return '[NOT CONFIGURED]'
  if (key.length <= 8) return '***'
  return `${key.slice(0, 4)}...${key.slice(-4)}`
}

// ─── URL Builders ─────────────────────────────────────────────────────────────

export function buildCartoVoyagerUrl(apiKey?: string | null): string {
  if (!apiKey) {
    return OSM_TILE_URL
  }
  return `${CARTO_VOYAGER_URL}?key=${encodeURIComponent(apiKey)}`
}

export function buildTomTomTrafficUrl(apiKey: string): string {
  return `${TOMTOM_TRAFFIC_URL_TEMPLATE}?key=${encodeURIComponent(apiKey)}`
}

// ─── Diagnostics & Verification ───────────────────────────────────────────────

/**
 * Verifies CARTO API key asynchronously.
 * Detects 401/403 errors and CARTO's 2049-byte watermark tile.
 */
export async function verifyCartoKey(key?: string | null): Promise<{ valid: boolean; statusCode?: number; reason?: string }> {
  if (!key) {
    return { valid: false, reason: 'CARTO API key not configured' }
  }
  try {
    const probeUrl = `https://a.basemaps.cartocdn.com/rastertiles/voyager/0/0/0.png?key=${encodeURIComponent(key)}`
    const res = await fetch(probeUrl, { method: 'GET', cache: 'no-cache' })
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: Invalid or unauthorized CARTO API key` }
      }
      if (res.status === 429) {
        return { valid: false, statusCode: 429, reason: 'HTTP 429: CARTO quota exceeded' }
      }
      return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: CARTO provider service error` }
    }

    const contentLength = res.headers.get('content-length')
    const etag = res.headers.get('etag')
    if (contentLength === '2049' || (etag && etag.includes('wm-'))) {
      return { valid: false, statusCode: 200, reason: 'CARTO watermark tile returned (API key rejected)' }
    }

    const blob = await res.blob()
    if (blob.size === 2049) {
      return { valid: false, statusCode: 200, reason: 'CARTO watermark tile returned (API key rejected)' }
    }

    return { valid: true, statusCode: 200 }
  } catch {
    return { valid: false, reason: 'Network/CORS error contacting CARTO' }
  }
}

/**
 * Verifies TomTom API key and returns structured diagnostic reasons.
 */
export async function verifyTomTomKey(key?: string | null): Promise<{ valid: boolean; statusCode?: number; reason?: string }> {
  if (!key) {
    return { valid: false, reason: 'TomTom API key not configured' }
  }
  try {
    const probeUrl = `https://api.tomtom.com/traffic/map/4/tile/flow/relative0/12/2044/1360.png?key=${encodeURIComponent(key)}`
    const res = await fetch(probeUrl, { method: 'GET' })
    if (res.status === 200) {
      return { valid: true, statusCode: 200 }
    }
    if (res.status === 401) {
      return { valid: false, statusCode: 401, reason: 'HTTP 401: Invalid or missing TomTom credentials' }
    }
    if (res.status === 403) {
      return { valid: false, statusCode: 403, reason: 'HTTP 403: Forbidden, invalid permissions or domain restrictions' }
    }
    if (res.status === 429) {
      return { valid: false, statusCode: 429, reason: 'HTTP 429: TomTom quota or rate limit exceeded' }
    }
    if (res.status >= 500) {
      return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: TomTom provider service failure` }
    }
    return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: Unexpected response` }
  } catch {
    return { valid: false, reason: 'Network/CORS error: Connectivity or browser access problem' }
  }
}

// ─── Base Layer Creators ──────────────────────────────────────────────────────

export function createOsmTileLayer(): L.TileLayer {
  return L.tileLayer(OSM_TILE_URL, {
    maxZoom: 19,
    subdomains: ['a', 'b', 'c'],
    keepBuffer: 8,
    updateWhenIdle: false,
    updateWhenZooming: false,
    crossOrigin: true,
    attribution: OSM_ATTRIBUTION,
  })
}

export function createEsriSatelliteTileLayer(): L.TileLayer {
  return L.tileLayer(ESRI_SATELLITE_URL, {
    maxZoom: 19,
    keepBuffer: 8,
    updateWhenIdle: false,
    updateWhenZooming: false,
    crossOrigin: true,
    attribution: ESRI_ATTRIBUTION,
  })
}

export function createCartoVoyagerTileLayer(key: string): L.TileLayer {
  const url = `${CARTO_VOYAGER_URL}?key=${encodeURIComponent(key)}`
  return L.tileLayer(url, {
    maxZoom: 20,
    subdomains: ['a', 'b', 'c', 'd'],
    keepBuffer: 8,
    updateWhenIdle: false,
    updateWhenZooming: false,
    crossOrigin: true,
    attribution: CARTO_ATTRIBUTION,
  })
}

/**
 * Creates a standalone Leaflet TileLayer according to layer type and available credentials.
 */
export function createBaseTileLayer(
  type: BaseLayerType,
  options?: { cartoApiKey?: string | null }
): L.TileLayer {
  if (type === 'satellite') {
    return createEsriSatelliteTileLayer()
  }

  const cartoKey = options?.cartoApiKey !== undefined
    ? options.cartoApiKey
    : getCartoBasemapApiKey()

  if (cartoKey) {
    return createCartoVoyagerTileLayer(cartoKey)
  }

  return createOsmTileLayer()
}

// ─── Managed Base Layer Attachment with Error Handling & Fallback ─────────────

export interface BaseTileLayerHandle {
  layer: L.TileLayer
  getStatus: () => BaseMapStatus
  cleanup: () => void
}

/**
 * Attaches a base map tile layer to a Leaflet map with error handling,
 * automatic fallback from CARTO to OpenStreetMap, and real-time status reporting.
 */
export function attachBaseTileLayer(
  map: L.Map,
  type: BaseLayerType,
  options?: {
    cartoApiKey?: string | null
    onStatusChange?: (status: BaseMapStatus) => void
  }
): BaseTileLayerHandle {
  let isCleanedUp = false
  let currentLayer: L.TileLayer
  let currentStatus: BaseMapStatus
  let consecutiveErrors = 0
  let hasFallenBack = false

  const notify = (status: BaseMapStatus) => {
    currentStatus = status
    if (!isCleanedUp && options?.onStatusChange) {
      options.onStatusChange(status)
    }
  }

  if (type === 'satellite') {
    currentLayer = createEsriSatelliteTileLayer()
    currentStatus = {
      provider: 'esri',
      displayName: 'Esri Satellite',
      isFallback: false,
      status: 'active',
    }
    notify(currentStatus)
    currentLayer.addTo(map)

    return {
      layer: currentLayer,
      getStatus: () => currentStatus,
      cleanup: () => {
        isCleanedUp = true
        if (map.hasLayer(currentLayer)) {
          map.removeLayer(currentLayer)
        }
      },
    }
  }

  // Type is 'streets'
  const cartoKey = options?.cartoApiKey !== undefined
    ? options.cartoApiKey
    : getCartoBasemapApiKey()

  // Case 1: CARTO key is missing or blank -> immediately use OpenStreetMap
  if (!cartoKey) {
    currentLayer = createOsmTileLayer()
    currentStatus = {
      provider: 'osm',
      displayName: 'OpenStreetMap',
      isFallback: false,
      fallbackReason: 'CARTO API key not configured',
      status: 'active',
    }
    notify(currentStatus)
    currentLayer.addTo(map)

    return {
      layer: currentLayer,
      getStatus: () => currentStatus,
      cleanup: () => {
        isCleanedUp = true
        if (map.hasLayer(currentLayer)) {
          map.removeLayer(currentLayer)
        }
      },
    }
  }

  // Case 2: CARTO key is configured -> attempt CARTO Voyager with fallback listener
  currentLayer = createCartoVoyagerTileLayer(cartoKey)
  currentStatus = {
    provider: 'carto',
    displayName: 'CARTO Voyager',
    isFallback: false,
    status: 'loading',
  }
  notify(currentStatus)

  const triggerOsmFallback = (reason: string) => {
    if (hasFallenBack || isCleanedUp) return
    hasFallenBack = true

    console.warn(`[Gativa Map] Base map fallback engaged: ${reason}`)

    // Remove failed CARTO layer
    if (map.hasLayer(currentLayer)) {
      map.removeLayer(currentLayer)
    }

    // Create and add OSM layer
    const osmLayer = createOsmTileLayer()
    currentLayer = osmLayer
    osmLayer.addTo(map)

    notify({
      provider: 'osm',
      displayName: 'OpenStreetMap',
      isFallback: true,
      fallbackReason: reason,
      status: 'active',
    })
  }

  const handleTileLoad = () => {
    if (hasFallenBack || isCleanedUp) return
    consecutiveErrors = 0
    if (currentStatus.status !== 'active') {
      notify({
        provider: 'carto',
        displayName: 'CARTO Voyager',
        isFallback: false,
        status: 'active',
      })
    }
  }

  const handleTileError = () => {
    if (hasFallenBack || isCleanedUp) return
    consecutiveErrors++
    // Avoid switching on a single isolated tile error; switch after 3 consecutive errors
    if (consecutiveErrors >= 3) {
      triggerOsmFallback('Repeated tile loading failures from CARTO')
    }
  }

  currentLayer.on('tileload', handleTileLoad)
  currentLayer.on('tileerror', handleTileError)
  currentLayer.addTo(map)

  // Asynchronous key verification probe to catch watermark tiles or immediate auth rejection
  verifyCartoKey(cartoKey)
    .then((result) => {
      if (isCleanedUp || hasFallenBack) return
      if (!result.valid) {
        triggerOsmFallback(result.reason || 'CARTO authentication failed')
      }
    })
    .catch(() => {
      // Background probe network error is handled by Leaflet runtime tileerror
    })

  return {
    layer: currentLayer,
    getStatus: () => currentStatus,
    cleanup: () => {
      isCleanedUp = true
      currentLayer.off('tileload', handleTileLoad)
      currentLayer.off('tileerror', handleTileError)
      if (map.hasLayer(currentLayer)) {
        map.removeLayer(currentLayer)
      }
    },
  }
}

// ─── Managed TomTom Traffic Flow Layer ────────────────────────────────────────

export interface TrafficLayerHandle {
  layer: L.TileLayer | null
  getStatus: () => TrafficLayerStatus
  cleanup: () => void
}

/**
 * Attaches TomTom live traffic flow tile layer with tile error diagnostics and status verification.
 */
export function attachTomTomTrafficLayer(
  map: L.Map,
  options?: {
    apiKey?: string | null
    onStatusChange?: (status: TrafficLayerStatus) => void
  }
): TrafficLayerHandle {
  let isCleanedUp = false
  const key = options?.apiKey !== undefined ? options?.apiKey : getTomTomApiKey()

  let currentStatus: TrafficLayerStatus = {
    enabled: true,
    status: 'loading',
    successCount: 0,
    errorCount: 0,
  }

  const notify = (status: TrafficLayerStatus) => {
    currentStatus = status
    if (!isCleanedUp && options?.onStatusChange) {
      options.onStatusChange(status)
    }
  }

  if (!key) {
    notify({
      enabled: false,
      status: 'error',
      errorMessage: 'TomTom API key not configured',
      successCount: 0,
      errorCount: 0,
    })
    return {
      layer: null,
      getStatus: () => currentStatus,
      cleanup: () => {},
    }
  }

  const url = buildTomTomTrafficUrl(key)
  const trafficLayer = L.tileLayer(url, {
    maxZoom: 19,
    subdomains: ['a', 'b', 'c', 'd'],
    opacity: 0.85,
    keepBuffer: 8,
    updateWhenIdle: false,
    updateWhenZooming: false,
    crossOrigin: true,
    attribution: TOMTOM_ATTRIBUTION,
  })

  let successCount = 0
  let errorCount = 0
  let hasDiagnosed = false

  const handleTileLoad = () => {
    if (isCleanedUp) return
    successCount++
    if (currentStatus.status !== 'active') {
      notify({
        enabled: true,
        status: 'active',
        successCount,
        errorCount,
      })
    }
  }

  const handleTileError = () => {
    if (isCleanedUp) return
    errorCount++

    // If initial tiles are failing and none succeeded, update status and diagnose
    if (successCount === 0 && errorCount >= 3 && !hasDiagnosed) {
      hasDiagnosed = true
      verifyTomTomKey(key)
        .then((diag) => {
          if (isCleanedUp) return
          const msg = diag.reason || 'Failed to load TomTom traffic tiles'
          console.warn(`[Gativa Map] TomTom traffic tile error: ${msg}`)
          notify({
            enabled: true,
            status: 'error',
            errorMessage: msg,
            successCount,
            errorCount,
          })
        })
        .catch(() => {
          if (isCleanedUp) return
          notify({
            enabled: true,
            status: 'error',
            errorMessage: 'Network or CORS failure loading TomTom traffic',
            successCount,
            errorCount,
          })
        })
    }
  }

  trafficLayer.on('tileload', handleTileLoad)
  trafficLayer.on('tileerror', handleTileError)
  trafficLayer.addTo(map)

  notify(currentStatus)

  return {
    layer: trafficLayer,
    getStatus: () => currentStatus,
    cleanup: () => {
      isCleanedUp = true
      trafficLayer.off('tileload', handleTileLoad)
      trafficLayer.off('tileerror', handleTileError)
      if (map.hasLayer(trafficLayer)) {
        map.removeLayer(trafficLayer)
      }
    },
  }
}
