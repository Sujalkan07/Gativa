/**
 * Centralized Map Tile Provider & Intelligent Error-Resilient Layer Manager
 *
 * Supports:
 * - TomTom Street Basemap (Primary provider via TomTom Map Display Raster API v1)
 * - OpenStreetMap Street Basemap (Automatic fallback & standard open provider)
 * - CARTO Voyager Street Basemap (Secondary optional provider)
 * - Esri World Imagery Satellite Basemap
 * - TomTom Live Traffic Flow Tile Overlay (Independent Traffic API v4)
 *
 * Requirements:
 * - Decoupled Architecture: TomTom Maps basemap and TomTom Traffic overlay are separate layers.
 * - Credentials & Redaction: Keys are safely redacted in logs; no credentials exposed in UI.
 * - Controlled Fallback: 3 consecutive tile errors trigger fallback to OSM with loop prevention.
 * - Accurate Status: Provider status reflects actual loaded tiles, not merely configured keys.
 */

import L from 'leaflet'

export type BaseLayerType = 'streets' | 'satellite' | 'tomtom' | 'osm' | 'carto'
export type BaseMapProviderId = 'tomtom' | 'osm' | 'esri' | 'carto'
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

export const TOMTOM_MAP_URL_TEMPLATE =
  'https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png'
export const TOMTOM_MAP_ATTRIBUTION =
  '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom</a>, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'

export const TOMTOM_TRAFFIC_URL_TEMPLATE =
  'https://{s}.api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png'
export const TOMTOM_TRAFFIC_ATTRIBUTION =
  '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom Traffic</a>'

export const OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'

export const CARTO_VOYAGER_URL =
  'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
export const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'

export const ESRI_SATELLITE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
export const ESRI_ATTRIBUTION =
  'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'

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
  'your_tomtom_api_key_here',
  'actual_tomtom_key',
  'your_carto_api_key_here',
  'actual_carto_key',
  'your_api_key_here',
  'your_key_here',
  'your_key',
])

/**
 * Retrieve TomTom API key from environment, ensuring placeholders are rejected.
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

/**
 * Builds the complete TomTom Maps Raster basic tile URL.
 * Endpoint: https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key={API_KEY}
 * Subdomains: 'a', 'b', 'c', 'd'.
 */
export function buildTomTomMapTileUrl(apiKey: string): string {
  return `${TOMTOM_MAP_URL_TEMPLATE}?key=${encodeURIComponent(apiKey)}`
}

/**
 * Builds the TomTom Traffic Flow Raster tile URL.
 * Endpoint: https://{s}.api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key={API_KEY}
 */
export function buildTomTomTrafficUrl(apiKey: string): string {
  return `${TOMTOM_TRAFFIC_URL_TEMPLATE}?key=${encodeURIComponent(apiKey)}`
}

export function buildCartoVoyagerUrl(apiKey?: string | null): string {
  if (!apiKey) {
    return OSM_TILE_URL
  }
  return `${CARTO_VOYAGER_URL}?key=${encodeURIComponent(apiKey)}`
}

// ─── Diagnostics & Verification ───────────────────────────────────────────────

/**
 * Verifies TomTom Maps basemap API key and returns structured diagnostic reasons.
 * Probes the root global tile (0/0/0) which does not require specific regional bounds.
 */
export async function verifyTomTomMapKey(
  key?: string | null
): Promise<{ valid: boolean; statusCode?: number; reason?: string }> {
  if (!key) {
    return { valid: false, reason: 'TomTom API key not configured (VITE_TOMTOM_API_KEY missing)' }
  }
  try {
    const probeUrl = `https://a.api.tomtom.com/map/1/tile/basic/main/0/0/0.png?key=${encodeURIComponent(key)}`
    const res = await fetch(probeUrl, { method: 'GET' })
    if (res.status === 200) {
      return { valid: true, statusCode: 200 }
    }
    if (res.status === 401) {
      return { valid: false, statusCode: 401, reason: 'HTTP 401: Invalid or unauthorized TomTom API key' }
    }
    if (res.status === 403) {
      return { valid: false, statusCode: 403, reason: 'HTTP 403: Forbidden, permission denied or domain restriction' }
    }
    if (res.status === 429) {
      return { valid: false, statusCode: 429, reason: 'HTTP 429: TomTom quota or rate limit exceeded' }
    }
    if (res.status >= 500) {
      return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: TomTom provider service failure` }
    }
    return { valid: false, statusCode: res.status, reason: `HTTP ${res.status}: Unexpected response from TomTom Maps` }
  } catch {
    return { valid: false, reason: 'Network/CORS error: Connectivity or browser access blocked' }
  }
}

/**
 * Verifies TomTom Traffic Flow API key and returns structured diagnostic reasons.
 */
export async function verifyTomTomTrafficKey(
  key?: string | null
): Promise<{ valid: boolean; statusCode?: number; reason?: string }> {
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

// Backwards-compatible alias
export const verifyTomTomKey = verifyTomTomTrafficKey

/**
 * Verifies CARTO API key asynchronously.
 * Detects 401/403 errors and CARTO's 2049-byte watermark tile.
 */
export async function verifyCartoKey(
  key?: string | null
): Promise<{ valid: boolean; statusCode?: number; reason?: string }> {
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

// ─── Base Layer Creators ──────────────────────────────────────────────────────

/**
 * Creates a TomTom Street Basemap TileLayer.
 * Maps API: /map/1/tile/basic/main/{z}/{x}/{y}.png
 * Supports zoom 0-22 (configured to maxZoom 20).
 * Host aliases: a, b, c, d.api.tomtom.com.
 */
export function createTomTomBaseTileLayer(apiKey: string): L.TileLayer {
  const url = buildTomTomMapTileUrl(apiKey)
  return L.tileLayer(url, {
    maxZoom: 20,
    subdomains: ['a', 'b', 'c', 'd'],
    keepBuffer: 8,
    updateWhenIdle: false,
    updateWhenZooming: false,
    crossOrigin: true,
    attribution: TOMTOM_MAP_ATTRIBUTION,
  })
}

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
 * Priority for 'streets':
 * 1. TomTom Maps if VITE_TOMTOM_API_KEY configured
 * 2. CARTO Voyager if VITE_CARTO_BASEMAP_API_KEY configured
 * 3. OpenStreetMap fallback
 */
export function createBaseTileLayer(
  type: BaseLayerType,
  options?: {
    tomtomApiKey?: string | null
    cartoApiKey?: string | null
  }
): L.TileLayer {
  if (type === 'satellite') {
    return createEsriSatelliteTileLayer()
  }

  if (type === 'osm') {
    return createOsmTileLayer()
  }

  const tomtomKey = options?.tomtomApiKey !== undefined
    ? options.tomtomApiKey
    : getTomTomApiKey()

  if (type === 'tomtom') {
    if (tomtomKey) return createTomTomBaseTileLayer(tomtomKey)
    return createOsmTileLayer()
  }

  const cartoKey = options?.cartoApiKey !== undefined
    ? options.cartoApiKey
    : getCartoBasemapApiKey()

  if (type === 'carto') {
    if (cartoKey) return createCartoVoyagerTileLayer(cartoKey)
    return createOsmTileLayer()
  }

  // type === 'streets'
  if (tomtomKey) {
    return createTomTomBaseTileLayer(tomtomKey)
  }
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
 * Attaches a base map tile layer to a Leaflet map with intelligent error handling,
 * automatic fallback to OpenStreetMap, and real-time status reporting.
 */
export function attachBaseTileLayer(
  map: L.Map,
  type: BaseLayerType,
  options?: {
    tomtomApiKey?: string | null
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

  // 1. Satellite (Esri World Imagery)
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

  // 2. Explicit OpenStreetMap
  if (type === 'osm') {
    currentLayer = createOsmTileLayer()
    currentStatus = {
      provider: 'osm',
      displayName: 'OpenStreetMap',
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

  // 3. Explicit CARTO Voyager
  if (type === 'carto') {
    const cartoKey = options?.cartoApiKey !== undefined
      ? options.cartoApiKey
      : getCartoBasemapApiKey()

    if (!cartoKey) {
      currentLayer = createOsmTileLayer()
      currentStatus = {
        provider: 'osm',
        displayName: 'OpenStreetMap',
        isFallback: true,
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

    currentLayer = createCartoVoyagerTileLayer(cartoKey)
    currentStatus = {
      provider: 'carto',
      displayName: 'CARTO Voyager',
      isFallback: false,
      status: 'loading',
    }
    notify(currentStatus)

    const triggerCartoOsmFallback = (reason: string) => {
      if (hasFallenBack || isCleanedUp) return
      hasFallenBack = true
      console.warn(`[Gativa Map] CARTO fallback engaged: ${reason}`)
      if (map.hasLayer(currentLayer)) {
        map.removeLayer(currentLayer)
      }
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

    const handleCartoLoad = () => {
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

    const handleCartoError = () => {
      if (hasFallenBack || isCleanedUp) return
      consecutiveErrors++
      if (consecutiveErrors >= 3) {
        triggerCartoOsmFallback('Repeated tile loading failures from CARTO')
      }
    }

    currentLayer.on('tileload', handleCartoLoad)
    currentLayer.on('tileerror', handleCartoError)
    currentLayer.addTo(map)

    verifyCartoKey(cartoKey)
      .then((res) => {
        if (isCleanedUp || hasFallenBack) return
        if (!res.valid) {
          triggerCartoOsmFallback(res.reason || 'CARTO authentication failed')
        }
      })
      .catch(() => {})

    return {
      layer: currentLayer,
      getStatus: () => currentStatus,
      cleanup: () => {
        isCleanedUp = true
        currentLayer.off('tileload', handleCartoLoad)
        currentLayer.off('tileerror', handleCartoError)
        if (map.hasLayer(currentLayer)) {
          map.removeLayer(currentLayer)
        }
      },
    }
  }

  // 4. TomTom Streets / Default 'streets' (TomTom primary, OSM fallback)
  const tomtomKey = options?.tomtomApiKey !== undefined
    ? options.tomtomApiKey
    : getTomTomApiKey()

  // Case A: TomTom key not configured -> immediately use OpenStreetMap
  if (!tomtomKey) {
    currentLayer = createOsmTileLayer()
    currentStatus = {
      provider: 'osm',
      displayName: 'OpenStreetMap',
      isFallback: false,
      fallbackReason: 'TomTom API key not configured',
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

  // Case B: TomTom key configured -> attempt TomTom Street Tiles with automatic OSM fallback
  currentLayer = createTomTomBaseTileLayer(tomtomKey)
  currentStatus = {
    provider: 'tomtom',
    displayName: 'TomTom Streets',
    isFallback: false,
    status: 'loading',
  }
  notify(currentStatus)

  const triggerOsmFallback = (reason: string) => {
    if (hasFallenBack || isCleanedUp) return
    hasFallenBack = true

    console.warn(`[Gativa Map] TomTom basemap fallback engaged: ${reason}`)

    // Remove failed TomTom layer
    if (map.hasLayer(currentLayer)) {
      map.removeLayer(currentLayer)
    }

    // Add clean OSM fallback layer
    const osmLayer = createOsmTileLayer()
    currentLayer = osmLayer
    osmLayer.addTo(map)

    notify({
      provider: 'osm',
      displayName: 'OpenStreetMap',
      isFallback: true,
      fallbackReason: reason,
      status: 'active',
      errorDetails: reason,
    })
  }

  const handleTileLoad = () => {
    if (hasFallenBack || isCleanedUp) return
    consecutiveErrors = 0
    if (currentStatus.status !== 'active') {
      notify({
        provider: 'tomtom',
        displayName: 'TomTom Streets',
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
      verifyTomTomMapKey(tomtomKey)
        .then((diag) => {
          const reason = diag.reason || 'Repeated tile loading failures from TomTom Maps'
          triggerOsmFallback(reason)
        })
        .catch(() => {
          triggerOsmFallback('Repeated tile loading failures from TomTom Maps')
        })
    }
  }

  currentLayer.on('tileload', handleTileLoad)
  currentLayer.on('tileerror', handleTileError)
  currentLayer.addTo(map)

  // Asynchronous key probe to catch invalid/restricted keys immediately
  verifyTomTomMapKey(tomtomKey)
    .then((result) => {
      if (isCleanedUp || hasFallenBack) return
      if (!result.valid) {
        triggerOsmFallback(result.reason || 'TomTom authentication failed')
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
 * Independent overlay rendered above the active basemap.
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
    attribution: TOMTOM_TRAFFIC_ATTRIBUTION,
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
      verifyTomTomTrafficKey(key)
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
