import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import LeafletDrawingMap, { type Point, type SearchedLocationTarget } from '../components/selection/LeafletDrawingMap'
import LocationSearchBox from '../components/selection/LocationSearchBox'
import { api, GativaApiError } from '../api/client'
import type { GeoJSONPolygon, GeocodingResult } from '../types/api'

const MAX_AREA_KM2 = 50

// ─── Area calculation helpers ─────────────────────────────────────────────────

/** Computes polygon area in km² using spherical excess formula */
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

// ─── Main Map Selection Page ──────────────────────────────────────────────────

export default function MapSelectionPage() {
  const navigate = useNavigate()
  const [savedCoords, setSavedCoords] = useState<Point[]>([])
  const [draftPoints, setDraftPoints] = useState<Point[]>([])
  const [areaKm2, setAreaKm2] = useState<number | null>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchedLocation, setSearchedLocation] = useState<SearchedLocationTarget | null>(null)

  // Handle location selection from search box
  const handleSelectLocation = useCallback(
    (loc: GeocodingResult) => {
      // Clear any previously saved polygon if user moves to a new place
      if (savedCoords.length >= 3 || draftPoints.length > 0) {
        setSavedCoords([])
        setDraftPoints([])
        setAreaKm2(null)
      }
      setError(null)
      setSearchedLocation({
        lat: loc.lat,
        lng: loc.lng,
        name: loc.name,
        bounding_box: loc.bounding_box,
        timestamp: Date.now(),
      })
    },
    [savedCoords.length, draftPoints.length]
  )

  const handleClearLocation = useCallback(() => {
    setSearchedLocation(null)
  }, [])

  // Start drawing
  const handleStartDrawing = useCallback(() => {
    setSavedCoords([])
    setDraftPoints([])
    setAreaKm2(null)
    setError(null)
    setIsDrawing(true)
  }, [])

  // Clear polygon
  const handleClearPolygon = useCallback(() => {
    setSavedCoords([])
    setDraftPoints([])
    setAreaKm2(null)
    setError(null)
    setIsDrawing(false)
  }, [])

  // Add draft point
  const handleAddDraftPoint = useCallback((point: Point) => {
    setDraftPoints((prev) => [...prev, point])
  }, [])

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

  // Submit analysis
  const handleAnalyze = useCallback(async () => {
    if (savedCoords.length < 3) {
      setError('Please draw a valid boundary on the map first.')
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

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-surface)]">
      <Header />

      {/* Map area — full height below header */}
      <main className="flex-1 relative pt-14">
        {/* Interactive OpenStreetMap / CartoDB / Satellite Canvas */}
        <LeafletDrawingMap
          isDrawing={isDrawing}
          draftPoints={draftPoints}
          savedCoords={savedCoords}
          onAddDraftPoint={handleAddDraftPoint}
          onCompletePolygon={handleCompletePolygon}
          searchedLocation={searchedLocation}
          className="w-full h-[calc(100vh-3.5rem)]"
        />

        {/* Top-left Location Search Bar */}
        <div className="absolute top-[calc(3.5rem+0.75rem)] left-4 z-[1001] pointer-events-auto">
          <LocationSearchBox
            onSelectLocation={handleSelectLocation}
            onClearLocation={handleClearLocation}
            selectedLocationName={searchedLocation?.name}
          />
        </div>

        {/* Top-right quick draw / clear floating toolbar */}
        <div className="absolute top-[calc(3.5rem+1rem)] right-4 z-[1000] flex flex-col gap-2 items-end pointer-events-auto">
          <div className="bg-[var(--color-surface-container-lowest)] rounded-lg shadow-md p-1 flex flex-col gap-1 border border-[var(--color-surface-container-high)]">
            <button
              onClick={handleStartDrawing}
              title={isDrawing ? 'Drawing active (click on map to place points)' : 'Draw Custom Polygon'}
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
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[1000] pointer-events-auto">
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
              /* State B: Initial State — Prompt user to draw area */
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
                      Search a location above or click "Draw Area" to sketch a polygon boundary.
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
      </main>
    </div>
  )
}
