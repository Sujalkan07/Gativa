import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { APIProvider, Map, useMap } from '@vis.gl/react-google-maps'
import Header from '../components/Header'
import { api, GativaApiError } from '../api/client'
import type { GeoJSONPolygon } from '../types/api'

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || ''
const MAX_AREA_KM2 = 50

interface Point {
  lat: number
  lng: number
}

export interface PresetCorridor {
  name: string
  city: string
  center: Point
  zoom: number
  coords: Point[]
}

export const PRESET_CORRIDORS: PresetCorridor[] = [
  {
    name: 'Sitapur Rd / Jankipuram',
    city: 'Lucknow',
    center: { lat: 26.900, lng: 80.942 },
    zoom: 14,
    coords: [
      { lat: 26.892, lng: 80.932 },
      { lat: 26.892, lng: 80.952 },
      { lat: 26.908, lng: 80.952 },
      { lat: 26.908, lng: 80.932 },
    ],
  },
  {
    name: 'Connaught Place Radial Grid',
    city: 'New Delhi',
    center: { lat: 28.6315, lng: 77.2167 },
    zoom: 14,
    coords: [
      { lat: 28.625, lng: 77.210 },
      { lat: 28.625, lng: 77.225 },
      { lat: 28.638, lng: 77.225 },
      { lat: 28.638, lng: 77.210 },
    ],
  },
  {
    name: 'Indiranagar / 100ft Spine',
    city: 'Bengaluru',
    center: { lat: 12.9775, lng: 77.645 },
    zoom: 14,
    coords: [
      { lat: 12.970, lng: 77.635 },
      { lat: 12.970, lng: 77.655 },
      { lat: 12.985, lng: 77.655 },
      { lat: 12.985, lng: 77.635 },
    ],
  },
]

// ─── Area calculation helpers ─────────────────────────────────────────────────

/** Computes polygon area in km² using the spherical excess formula */
function computeAreaKm2(coords: Point[]): number {
  if (coords.length < 3) return 0
  const R = 6371 // Earth radius km
  let area = 0
  const n = coords.length
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    const lat1 = (coords[i].lat * Math.PI) / 180
    const lat2 = (coords[j].lat * Math.PI) / 180
    const lng1 = (coords[i].lng * Math.PI) / 180
    const lng2 = (coords[j].lng * Math.PI) / 180
    area += (lng2 - lng1) * (2 + Math.sin(lat1) + Math.sin(lat2))
  }
  return Math.abs((area * R * R) / 2)
}

/** Converts coordinate array to GeoJSON Polygon */
function toGeoJSONPolygon(coords: Point[]): GeoJSONPolygon {
  const ring = coords.map((c) => [c.lng, c.lat])
  if (ring.length > 0) {
    ring.push(ring[0])
  }
  return { type: 'Polygon', coordinates: [ring] }
}

// ─── Interactive Map Drawing Layer ────────────────────────────────────────────

interface DrawingLayerProps {
  isDrawing: boolean
  draftPoints: Point[]
  setDraftPoints: React.Dispatch<React.SetStateAction<Point[]>>
  onComplete: () => void
}

function InteractiveDrawingLayer({
  isDrawing,
  draftPoints,
  setDraftPoints,
  onComplete,
}: DrawingLayerProps) {
  const map = useMap()
  const polylineRef = useRef<google.maps.Polyline | null>(null)
  const startMarkerRef = useRef<google.maps.Marker | null>(null)

  // 1. Initialize or clear temporary polyline
  useEffect(() => {
    if (!map) return

    if (!polylineRef.current) {
      polylineRef.current = new google.maps.Polyline({
        path: [],
        strokeColor: '#ff9933',
        strokeOpacity: 0.9,
        strokeWeight: 3,
        map: map,
      })
    }

    return () => {
      if (polylineRef.current) {
        polylineRef.current.setMap(null)
        polylineRef.current = null
      }
      if (startMarkerRef.current) {
        startMarkerRef.current.setMap(null)
        startMarkerRef.current = null
      }
    }
  }, [map])

  // 2. Manage drawing click & double click listeners
  useEffect(() => {
    if (!map) return

    if (!isDrawing) {
      map.setOptions({ draggableCursor: null, disableDoubleClickZoom: false })
      if (polylineRef.current) polylineRef.current.setPath([])
      if (startMarkerRef.current) startMarkerRef.current.setMap(null)
      return
    }

    map.setOptions({ draggableCursor: 'crosshair', disableDoubleClickZoom: true })

    const clickListener = map.addListener('click', (e: google.maps.MapMouseEvent) => {
      if (!e.latLng) return
      const newPt: Point = { lat: e.latLng.lat(), lng: e.latLng.lng() }
      setDraftPoints((prev) => [...prev, newPt])
    })

    const dblClickListener = map.addListener('dblclick', (e: google.maps.MapMouseEvent) => {
      e.stop()
      onComplete()
    })

    return () => {
      if (clickListener && typeof clickListener.remove === 'function') {
        clickListener.remove()
      }
      if (dblClickListener && typeof dblClickListener.remove === 'function') {
        dblClickListener.remove()
      }
      map.setOptions({ draggableCursor: null, disableDoubleClickZoom: false })
    }
  }, [map, isDrawing, onComplete, setDraftPoints])

  // 3. Update preview polyline and start marker when draftPoints change
  useEffect(() => {
    if (!map || !isDrawing) return

    if (polylineRef.current) {
      polylineRef.current.setPath(draftPoints)
    }

    // Origin marker on first point
    if (draftPoints.length > 0) {
      if (!startMarkerRef.current) {
        startMarkerRef.current = new google.maps.Marker({
          position: draftPoints[0],
          map: map,
          title: 'Start point (click to close polygon)',
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 8,
            fillColor: '#138808',
            fillOpacity: 1,
            strokeColor: '#ffffff',
            strokeWeight: 2,
          },
        })
        startMarkerRef.current.addListener('click', () => {
          if (draftPoints.length >= 3) {
            onComplete()
          }
        })
      } else {
        startMarkerRef.current.setPosition(draftPoints[0])
        startMarkerRef.current.setMap(map)
      }
    } else {
      if (startMarkerRef.current) {
        startMarkerRef.current.setMap(null)
      }
    }
  }, [map, isDrawing, draftPoints, onComplete])

  return null
}

// ─── Sub-component to render and edit completed polygon ───────────────────────

interface RenderCompletedPolygonProps {
  coords: Point[]
  onPolygonReady: (poly: google.maps.Polygon) => void
  onAreaUpdate: (area: number) => void
}

function RenderCompletedPolygon({
  coords,
  onPolygonReady,
  onAreaUpdate,
}: RenderCompletedPolygonProps) {
  const map = useMap()
  const polyRef = useRef<google.maps.Polygon | null>(null)

  useEffect(() => {
    if (!map || coords.length < 3) return

    const poly = new google.maps.Polygon({
      paths: coords,
      fillColor: '#ff9933',
      fillOpacity: 0.22,
      strokeColor: '#0b1c30',
      strokeWeight: 2.5,
      editable: true,
      draggable: false,
      map: map,
    })

    polyRef.current = poly
    onPolygonReady(poly)

    // Smoothly pan & fit bounds
    try {
      const bounds = new google.maps.LatLngBounds()
      coords.forEach((c) => bounds.extend(c))
      map.fitBounds(bounds, 60)
    } catch {
      // Ignore if bounds cannot be computed yet
    }

    const path = poly.getPath()
    const handleUpdate = () => {
      const updated = path.getArray().map((c) => ({ lat: c.lat(), lng: c.lng() }))
      onAreaUpdate(computeAreaKm2(updated))
    }

    const setListener = path.addListener('set_at', handleUpdate)
    const insListener = path.addListener('insert_at', handleUpdate)

    return () => {
      if (setListener && typeof setListener.remove === 'function') {
        setListener.remove()
      }
      if (insListener && typeof insListener.remove === 'function') {
        insListener.remove()
      }
      poly.setMap(null)
      polyRef.current = null
    }
  }, [map, coords, onPolygonReady, onAreaUpdate])

  return null
}

// ─── Main Map Selection Page ──────────────────────────────────────────────────

export default function MapSelectionPage() {
  const navigate = useNavigate()
  const [polygon, setPolygon] = useState<google.maps.Polygon | null>(null)
  const [savedCoords, setSavedCoords] = useState<Point[]>([])
  const [draftPoints, setDraftPoints] = useState<Point[]>([])
  const [areaKm2, setAreaKm2] = useState<number | null>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mapsBillingWarning, setMapsBillingWarning] = useState(false)

  // Intercept Google Maps authentication/billing failures
  useEffect(() => {
    const prevAuthFailure = (window as unknown as { gm_authFailure?: () => void }).gm_authFailure
    ;(window as unknown as { gm_authFailure?: () => void }).gm_authFailure = () => {
      setMapsBillingWarning(true)
      if (typeof prevAuthFailure === 'function') {
        prevAuthFailure()
      }
    }
  }, [])

  // Start drawing
  const handleStartDrawing = useCallback(() => {
    if (polygon) {
      polygon.setMap(null)
    }
    setPolygon(null)
    setSavedCoords([])
    setDraftPoints([])
    setAreaKm2(null)
    setError(null)
    setIsDrawing(true)
  }, [polygon])

  // Clear polygon
  const handleClearPolygon = useCallback(() => {
    if (polygon) {
      polygon.setMap(null)
    }
    setPolygon(null)
    setSavedCoords([])
    setDraftPoints([])
    setAreaKm2(null)
    setError(null)
    setIsDrawing(false)
  }, [polygon])

  // Complete drawing polygon
  const handleCompletePolygon = useCallback(() => {
    if (draftPoints.length < 3) {
      setError('Please place at least 3 points before completing the polygon.')
      return
    }

    const area = computeAreaKm2(draftPoints)
    setAreaKm2(area)
    setSavedCoords(draftPoints)
    setIsDrawing(false)
    setError(null)
  }, [draftPoints])

  // Select a preset corridor
  const handleSelectPreset = useCallback(
    (preset: PresetCorridor) => {
      if (polygon) {
        polygon.setMap(null)
      }
      setPolygon(null)
      setDraftPoints([])
      setIsDrawing(false)
      setError(null)
      setSavedCoords(preset.coords)
      const area = computeAreaKm2(preset.coords)
      setAreaKm2(area)
    },
    [polygon],
  )

  // Instantiate completed polygon when drawing completes
  const handlePolygonReady = useCallback((poly: google.maps.Polygon) => {
    setPolygon(poly)
  }, [])

  // Submit analysis
  const handleAnalyze = useCallback(async () => {
    if (savedCoords.length < 3) {
      setError('Please draw or select a valid corridor boundary first.')
      return
    }

    const area = computeAreaKm2(savedCoords)
    if (area > MAX_AREA_KM2) {
      setError(
        `The selected area (${area.toFixed(1)} km²) exceeds the maximum allowed area of ${MAX_AREA_KM2} km². Please draw a smaller polygon.`,
      )
      return
    }
    if (area < 0.01) {
      setError('The selected area is too small. Please select a larger polygon.')
      return
    }

    const geojson = toGeoJSONPolygon(savedCoords)
    setIsLoading(true)
    setError(null)

    try {
      const result = await api.createAnalysis({ polygon: geojson })
      navigate(`/analysis/${result.analysis_id}`)
    } catch (err) {
      if (err instanceof GativaApiError) {
        setError(err.message)
      } else {
        setError('Failed to start analysis. Please check backend connection and try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }, [savedCoords, navigate])

  const hasPolygon = savedCoords.length >= 3 && !isDrawing
  const areaOk = areaKm2 !== null && areaKm2 >= 0.01 && areaKm2 <= MAX_AREA_KM2
  const liveArea = isDrawing && draftPoints.length >= 3 ? computeAreaKm2(draftPoints) : null

  if (!GOOGLE_MAPS_API_KEY) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-surface)]">
        <div className="max-w-md mx-auto p-8 bg-[var(--color-surface-container-lowest)] rounded-xl border border-[var(--color-error-container)] text-center">
          <span className="material-symbols-outlined text-4xl text-[var(--color-error)] mb-4 block">error</span>
          <h1 className="text-xl font-bold text-[var(--color-on-surface)] mb-2">Google Maps API Key Missing</h1>
          <p className="text-sm text-[var(--color-on-surface-variant)] mb-4">
            Configure <code className="bg-[var(--color-surface-container)] px-1 rounded">VITE_GOOGLE_MAPS_API_KEY</code> in <code className="bg-[var(--color-surface-container)] px-1 rounded">frontend/.env</code>.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-surface)]">
      <Header />

      {/* Map area — full height below header */}
      <main className="flex-1 relative pt-14">
        <APIProvider apiKey={GOOGLE_MAPS_API_KEY}>
          <Map
            defaultCenter={{ lat: 26.900, lng: 80.942 }} // Lucknow / New Delhi default
            defaultZoom={13}
            style={{ width: '100%', height: 'calc(100vh - 3.5rem)' }}
            className="w-full h-[calc(100vh-3.5rem)]"
            disableDefaultUI
            gestureHandling="greedy"
          >
            <InteractiveDrawingLayer
              isDrawing={isDrawing}
              draftPoints={draftPoints}
              setDraftPoints={setDraftPoints}
              onComplete={handleCompletePolygon}
            />

            {/* Polygon Renderer once completed */}
            {hasPolygon && (
              <RenderCompletedPolygon
                coords={savedCoords}
                onPolygonReady={handlePolygonReady}
                onAreaUpdate={(newArea) => setAreaKm2(newArea)}
              />
            )}
          </Map>

          {/* Top Center Quick Corridor Presets Bar */}
          <div className="absolute top-[calc(3.5rem+0.75rem)] left-1/2 -translate-x-1/2 z-20 pointer-events-auto flex items-center gap-2 bg-[var(--color-surface-container-lowest)]/95 backdrop-blur-sm px-3.5 py-1.5 rounded-full shadow-md border border-[var(--color-surface-container-high)]">
            <span className="text-xs font-bold text-[var(--color-on-surface)] flex items-center gap-1 shrink-0">
              <span className="material-symbols-outlined text-[15px] text-[var(--color-primary-container)]">
                near_me
              </span>
              Corridors:
            </span>
            <div className="flex items-center gap-1.5">
              {PRESET_CORRIDORS.map((p) => (
                <button
                  key={p.name}
                  onClick={() => handleSelectPreset(p)}
                  className="px-2.5 py-0.5 rounded-full bg-[var(--color-surface-container-low)] hover:bg-[var(--color-secondary-fixed)] hover:text-[var(--color-on-secondary-fixed)] text-[var(--color-on-surface-variant)] text-xs font-semibold transition-colors whitespace-nowrap"
                >
                  📍 {p.city}
                </button>
              ))}
            </div>
          </div>

          {/* Billing Warning Banner (if Google Maps throws BillingNotEnabledMapError) */}
          {mapsBillingWarning && (
            <div className="absolute top-[calc(3.5rem+3.75rem)] left-1/2 -translate-x-1/2 z-20 pointer-events-auto max-w-lg w-full px-4">
              <div className="bg-[#fff8f6] border border-[#ffdad6] text-[#410002] rounded-xl p-3 shadow-lg flex items-start gap-3 text-xs">
                <span className="material-symbols-outlined text-[#ba1a1a] text-lg shrink-0 mt-0.5">
                  warning
                </span>
                <div className="flex-1">
                  <p className="font-bold text-[#ba1a1a]">Google Maps Platform Notice</p>
                  <p className="mt-0.5 text-[#554336] leading-relaxed">
                    Billing is not enabled on this Google Cloud project (<code>BillingNotEnabledMapError</code>). You can click any <strong>Corridor</strong> pill above to run full analysis, or draw on the map watermark.
                  </p>
                </div>
                <button
                  onClick={() => setMapsBillingWarning(false)}
                  className="text-[#554336] hover:text-[#0b1c30] p-1"
                >
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            </div>
          )}

          {/* Top-right map controls */}
          <div className="absolute top-[calc(3.5rem+1rem)] right-4 z-20 flex flex-col gap-2 items-end pointer-events-auto">
            <div className="bg-[var(--color-surface-container-lowest)] rounded-lg shadow-md p-1 flex flex-col gap-1">
              <button
                onClick={handleStartDrawing}
                title={isDrawing ? 'Drawing active' : 'Draw Polygon'}
                className={`w-8 h-8 rounded flex items-center justify-center transition-colors ${
                  isDrawing
                    ? 'bg-[var(--color-primary-container)] text-[var(--color-brand-navy)] shadow-inner'
                    : 'text-[var(--color-secondary)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">polyline</span>
              </button>
              <button
                onClick={handleClearPolygon}
                title="Clear selection"
                disabled={!hasPolygon && draftPoints.length === 0}
                className="w-8 h-8 rounded text-[var(--color-secondary)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-error)] flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">delete</span>
              </button>
            </div>
          </div>

          {/* Bottom info panel */}
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 pointer-events-auto">
            <div className="bg-[var(--color-surface-container-lowest)] rounded-xl shadow-lg border border-[var(--color-surface-container-high)] p-4 min-w-[420px] max-w-[560px]">
              {/* State A: Drawing Mode in progress */}
              {isDrawing ? (
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[var(--color-primary-container)] text-2xl animate-pulse">
                      edit_location_alt
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-[var(--color-on-surface)]">
                          Drawing Area ({draftPoints.length} {draftPoints.length === 1 ? 'vertex' : 'vertices'})
                        </p>
                        {liveArea !== null && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-bold font-mono bg-[var(--color-tertiary-fixed)] text-[var(--color-on-tertiary-fixed)]">
                            ~{liveArea.toFixed(2)} km²
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                        {draftPoints.length < 3
                          ? 'Click on the map to add vertices (at least 3 needed).'
                          : 'Click first point, double-click, or click "Complete" to finish.'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleClearPolygon}
                      className="px-3 py-1.5 rounded-lg bg-[var(--color-surface-container)] text-[var(--color-on-surface)] text-xs font-medium hover:bg-[var(--color-surface-container-high)] transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleCompletePolygon}
                      disabled={draftPoints.length < 3}
                      className="px-3 py-1.5 rounded-lg bg-[var(--color-primary-container)] text-[var(--color-brand-navy)] text-xs font-bold hover:bg-[var(--color-primary-fixed)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      Complete
                    </button>
                  </div>
                </div>
              ) : !hasPolygon ? (
                /* State B: Initial State — Prompt user to draw or choose corridor */
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[var(--color-secondary)] text-2xl">
                      draw
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-[var(--color-on-surface)]">
                        Select an Analysis Area
                      </p>
                      <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                        Click a Corridor preset above or click "Draw Area" to sketch a polygon.
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={handleStartDrawing}
                    className="px-4 py-1.5 rounded-lg bg-[var(--color-primary-container)] text-[var(--color-brand-navy)] text-xs font-bold hover:bg-[var(--color-primary-fixed)] transition-colors flex items-center gap-1.5 shadow-sm"
                  >
                    <span className="material-symbols-outlined text-[16px]">polyline</span>
                    Draw Area
                  </button>
                </div>
              ) : (
                /* State C: Polygon Defined — Ready to Analyze */
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[var(--color-tertiary)] text-2xl">
                      check_circle
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-[var(--color-on-surface)]">
                          Area Selected
                        </p>
                        {areaKm2 !== null && (
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs font-bold font-mono ${
                              areaKm2 > MAX_AREA_KM2
                                ? 'bg-[var(--color-error-container)] text-[var(--color-on-error-container)]'
                                : 'bg-[var(--color-tertiary-fixed)] text-[var(--color-on-tertiary-fixed)]'
                            }`}
                          >
                            {areaKm2.toFixed(2)} km²
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                        {areaKm2 && areaKm2 > MAX_AREA_KM2
                          ? `Area exceeds ${MAX_AREA_KM2} km² limit. Please draw a smaller polygon.`
                          : 'Valid boundary selected. Click Analyze Area to proceed.'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleClearPolygon}
                      className="px-3 py-1.5 rounded-lg bg-[var(--color-surface-container)] text-[var(--color-on-surface)] text-xs font-medium hover:bg-[var(--color-surface-container-high)] transition-colors"
                    >
                      Clear
                    </button>
                    <button
                      onClick={handleAnalyze}
                      disabled={!areaOk || isLoading}
                      className={`px-4 py-1.5 rounded-lg text-xs font-bold flex items-center gap-2 transition-all shadow-sm ${
                        areaOk && !isLoading
                          ? 'bg-[var(--color-primary-container)] text-[var(--color-brand-navy)] hover:bg-[var(--color-primary-fixed)]'
                          : 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface-variant)] cursor-not-allowed opacity-50'
                      }`}
                    >
                      {isLoading ? (
                        <>
                          <span className="material-symbols-outlined text-[16px] animate-spin">
                            progress_activity
                          </span>
                          Analyzing…
                        </>
                      ) : (
                        <>
                          <span className="material-symbols-outlined text-[16px]">analytics</span>
                          Analyze Area
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {/* Error message */}
              {error && (
                <div className="mt-3 flex items-start gap-2 p-2 bg-[var(--color-error-container)] rounded-lg">
                  <span className="material-symbols-outlined text-[var(--color-error)] text-[16px] mt-0.5 shrink-0">
                    error
                  </span>
                  <p className="text-xs text-[var(--color-on-error-container)]">{error}</p>
                </div>
              )}
            </div>
          </div>
        </APIProvider>
      </main>
    </div>
  )
}
