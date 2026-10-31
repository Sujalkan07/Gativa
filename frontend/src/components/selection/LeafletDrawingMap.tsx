import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  type BaseLayerType,
  type BaseMapStatus,
  type TrafficLayerStatus,
  type BaseTileLayerHandle,
  type TrafficLayerHandle,
  attachBaseTileLayer,
  attachTomTomTrafficLayer,
  getTomTomApiKey,
} from '../../lib/mapLayers'

export interface Point {
  lat: number
  lng: number
}

export interface SearchedLocationTarget {
  lat: number
  lng: number
  name: string
  bounding_box?: [number, number, number, number] | null
  timestamp: number
}

interface LeafletDrawingMapProps {
  isDrawing: boolean
  draftPoints: Point[]
  savedCoords: Point[]
  onAddDraftPoint: (point: Point) => void
  onCompletePolygon: () => void
  className?: string
  searchedLocation?: SearchedLocationTarget | null
}

export default function LeafletDrawingMap({
  isDrawing,
  draftPoints,
  savedCoords,
  onAddDraftPoint,
  onCompletePolygon,
  className = 'w-full h-full',
  searchedLocation,
}: LeafletDrawingMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Layers
  const baseTileHandleRef = useRef<BaseTileLayerHandle | null>(null)
  const trafficTileHandleRef = useRef<TrafficLayerHandle | null>(null)
  const draftPolylineRef = useRef<L.Polyline | null>(null)
  const draftMarkersGroupRef = useRef<L.LayerGroup | null>(null)
  const completedPolygonRef = useRef<L.Polygon | null>(null)
  const searchMarkerRef = useRef<L.Marker | null>(null)

  const hasTomTomKey = Boolean(getTomTomApiKey())

  const [baseLayerType, setBaseLayerType] = useState<BaseLayerType>('streets')
  const [showTraffic, setShowTraffic] = useState(false)
  const [baseMapStatus, setBaseMapStatus] = useState<BaseMapStatus>({
    provider: hasTomTomKey ? 'tomtom' : 'osm',
    displayName: hasTomTomKey ? 'TomTom Streets' : 'OpenStreetMap',
    isFallback: false,
    status: 'loading',
  })
  const [trafficStatus, setTrafficStatus] = useState<TrafficLayerStatus>({
    enabled: false,
    status: 'idle',
    successCount: 0,
    errorCount: 0,
  })

  const handleToggleTraffic = () => {
    setShowTraffic((prev) => {
      const next = !prev
      if (!next) {
        setTrafficStatus({
          enabled: false,
          status: 'idle',
          successCount: 0,
          errorCount: 0,
        })
      }
      return next
    })
  }

  // 1. Initialize Map
  useEffect(() => {
    if (!containerRef.current) return
    if (mapRef.current) return

    const map = L.map(containerRef.current, {
      center: [26.900, 80.942], // Lucknow default
      zoom: 13,
      zoomControl: false,
      attributionControl: true,
      doubleClickZoom: false, // disabled so double click can complete polygon
      preferCanvas: true,
    })

    // Custom zoom control
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    draftMarkersGroupRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    // Ensure immediate and accurate layout sizing (prevents grey tiles on flex/grid mount)
    const invalidate = () => {
      map.invalidateSize({ animate: false })
    }
    requestAnimationFrame(invalidate)
    const t1 = setTimeout(invalidate, 100)
    const t2 = setTimeout(invalidate, 300)
    const t3 = setTimeout(invalidate, 600)

    let ro: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
      ro = new ResizeObserver(() => {
        requestAnimationFrame(invalidate)
      })
      ro.observe(containerRef.current)
    }

    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
      ro?.disconnect()
      if (baseTileHandleRef.current) {
        baseTileHandleRef.current.cleanup()
        baseTileHandleRef.current = null
      }
      if (trafficTileHandleRef.current) {
        trafficTileHandleRef.current.cleanup()
        trafficTileHandleRef.current = null
      }
      map.remove()
      mapRef.current = null
    }
  }, [])

  // 2. Switch Base Layer (Streets vs Satellite)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (baseTileHandleRef.current) {
      baseTileHandleRef.current.cleanup()
      baseTileHandleRef.current = null
    }

    baseTileHandleRef.current = attachBaseTileLayer(map, baseLayerType, {
      onStatusChange: (status) => setBaseMapStatus(status),
    })
  }, [baseLayerType])

  // 2b. TomTom Live Traffic Flow Tile Overlay
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (trafficTileHandleRef.current) {
      trafficTileHandleRef.current.cleanup()
      trafficTileHandleRef.current = null
    }

    if (showTraffic && hasTomTomKey) {
      trafficTileHandleRef.current = attachTomTomTrafficLayer(map, {
        onStatusChange: (status) => setTrafficStatus(status),
      })
    }
  }, [showTraffic, hasTomTomKey])

  // 3. Map Click & Double Click Event Handling for Drawing
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (!isDrawing) {
      const container = map.getContainer()
      container.style.cursor = ''
      return
    }

    const container = map.getContainer()
    container.style.cursor = 'crosshair'

    const handleClick = (e: L.LeafletMouseEvent) => {
      onAddDraftPoint({ lat: e.latlng.lat, lng: e.latlng.lng })
    }

    const handleDblClick = (e: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(e)
      onCompletePolygon()
    }

    map.on('click', handleClick)
    map.on('dblclick', handleDblClick)

    return () => {
      map.off('click', handleClick)
      map.off('dblclick', handleDblClick)
      container.style.cursor = ''
    }
  }, [isDrawing, onAddDraftPoint, onCompletePolygon])

  // 4. Render Draft Polyline & Vertex Markers
  useEffect(() => {
    const map = mapRef.current
    const markersGroup = draftMarkersGroupRef.current
    if (!map || !markersGroup) return

    markersGroup.clearLayers()

    if (!isDrawing || draftPoints.length === 0) {
      if (draftPolylineRef.current) {
        map.removeLayer(draftPolylineRef.current)
        draftPolylineRef.current = null
      }
      return
    }

    const latLngs: L.LatLngExpression[] = draftPoints.map((p) => [p.lat, p.lng])

    // Update or create draft polyline
    if (!draftPolylineRef.current) {
      draftPolylineRef.current = L.polyline(latLngs, {
        color: '#ff9933', // India Saffron
        weight: 3,
        dashArray: '6, 6',
        opacity: 0.9,
      }).addTo(map)
    } else {
      draftPolylineRef.current.setLatLngs(latLngs)
    }

    // Add vertex markers
    draftPoints.forEach((pt, idx) => {
      const isStart = idx === 0
      const icon = L.divIcon({
        className: 'custom-draft-vertex',
        iconSize: isStart ? [22, 22] : [14, 14],
        iconAnchor: isStart ? [11, 11] : [7, 7],
        html: isStart
          ? `
            <div class="relative w-5 h-5 flex items-center justify-center cursor-pointer group">
              <span class="absolute w-5 h-5 rounded-full bg-[#138808]/40 animate-ping"></span>
              <div class="relative w-4 h-4 rounded-full bg-[#138808] border-2 border-white shadow-md flex items-center justify-center text-[8px] text-white font-bold">
                ●
              </div>
            </div>
          `
          : `
            <div class="w-3.5 h-3.5 rounded-full bg-[#ff9933] border-2 border-white shadow-sm"></div>
          `,
      })

      const marker = L.marker([pt.lat, pt.lng], { icon })

      if (isStart) {
        marker.bindTooltip('Click to close polygon', {
          direction: 'top',
          offset: [0, -10],
          opacity: 0.9,
        })
        marker.on('click', (e) => {
          L.DomEvent.stopPropagation(e)
          if (draftPoints.length >= 3) {
            onCompletePolygon()
          }
        })
      }

      markersGroup.addLayer(marker)
    })
  }, [isDrawing, draftPoints, onCompletePolygon])

  // 5. Render Completed Saved Polygon
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (completedPolygonRef.current) {
      map.removeLayer(completedPolygonRef.current)
      completedPolygonRef.current = null
    }

    if (isDrawing || savedCoords.length < 3) return

    const latLngs: L.LatLngExpression[] = savedCoords.map((p) => [p.lat, p.lng])

    const poly = L.polygon(latLngs, {
      color: '#0b1c30', // Navy border
      weight: 2.5,
      fillColor: '#ff9933', // India Saffron
      fillOpacity: 0.22,
    }).addTo(map)

    completedPolygonRef.current = poly

    try {
      const bounds = poly.getBounds()
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [45, 45] })
      }
    } catch {
      // Ignore layout bounds error
    }
  }, [savedCoords, isDrawing])

  // 6. Handle Searched Location Pan, Zoom & Marker Pin
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // Remove old search marker if any
    if (searchMarkerRef.current) {
      map.removeLayer(searchMarkerRef.current)
      searchMarkerRef.current = null
    }

    if (!searchedLocation) return

    const { lat, lng, name, bounding_box } = searchedLocation

    // Pan & zoom smoothly
    if (bounding_box && bounding_box.length === 4) {
      const [minLat, minLng, maxLat, maxLng] = bounding_box
      const bounds = L.latLngBounds([
        [minLat, minLng],
        [maxLat, maxLng],
      ])
      if (bounds.isValid()) {
        map.flyToBounds(bounds, { padding: [50, 50], maxZoom: 16, duration: 1.2 })
      } else {
        map.flyTo([lat, lng], 15, { duration: 1.2 })
      }
    } else {
      map.flyTo([lat, lng], 15, { duration: 1.2 })
    }

    // Place an elegant marker pin
    const pinIcon = L.divIcon({
      className: 'gativa-search-pin',
      iconSize: [32, 40],
      iconAnchor: [16, 40],
      html: `
        <div class="relative flex flex-col items-center pointer-events-auto cursor-pointer">
          <span class="absolute -top-1 w-6 h-6 rounded-full bg-[#ff9933]/40 animate-ping"></span>
          <div class="w-8 h-8 rounded-full bg-[#0a1145] border-2 border-[#ff9933] shadow-lg flex items-center justify-center text-white">
            <span class="material-symbols-outlined text-[17px] text-[#ff9933]">location_on</span>
          </div>
          <div class="w-1.5 h-2 bg-[#0a1145] -mt-0.5"></div>
        </div>
      `,
    })

    const marker = L.marker([lat, lng], { icon: pinIcon }).addTo(map)
    marker.bindTooltip(
      `<strong>${name}</strong><br/><span style="font-size: 11px; color: #545a90;">Draw area around this location to analyze</span>`,
      {
        permanent: false,
        direction: 'top',
        offset: [0, -38],
        opacity: 0.95,
      }
    )
    searchMarkerRef.current = marker

    return () => {
      if (searchMarkerRef.current) {
        map.removeLayer(searchMarkerRef.current)
        searchMarkerRef.current = null
      }
    }
  }, [searchedLocation])

  return (
    <div className="relative w-full h-full">
      {/* Map DOM node */}
      <div ref={containerRef} className={className} />

      {/* Layer Switcher & TomTom Live Traffic */}
      <div className="absolute top-4 right-16 z-[1000] flex items-center gap-1.5 bg-white/95 backdrop-blur-xs rounded-lg shadow-md border border-[#e2e8f0] p-0.5 text-xs font-semibold">
        {hasTomTomKey ? (
          <>
            <button
              onClick={handleToggleTraffic}
              title={
                trafficStatus.errorMessage
                  ? `TomTom Traffic: ${trafficStatus.errorMessage}`
                  : 'Toggle Live TomTom Real-Time Traffic Flow'
              }
              className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                showTraffic
                  ? trafficStatus.status === 'active'
                    ? 'bg-[#138808] text-white shadow-xs'
                    : trafficStatus.status === 'error'
                      ? 'bg-[#ba1a1a] text-white shadow-xs'
                      : 'bg-[#b45309] text-white shadow-xs'
                  : 'text-[#475569] hover:text-[#0b1c30]'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  !showTraffic
                    ? 'bg-[#94a3b8]'
                    : trafficStatus.status === 'active'
                      ? 'bg-white animate-pulse'
                      : trafficStatus.status === 'loading'
                        ? 'bg-amber-300 animate-pulse'
                        : 'bg-white'
                }`}
              />
              <span>
                {!showTraffic
                  ? 'Live Traffic'
                  : trafficStatus.status === 'active'
                    ? 'Live Traffic'
                    : trafficStatus.status === 'loading'
                      ? 'Connecting...'
                      : 'Traffic Error'}
              </span>
            </button>
            <div className="w-[1px] h-4 bg-[#cbd5e1]" />
          </>
        ) : (
          <>
            <div
              title="TomTom API key not configured (VITE_TOMTOM_API_KEY)"
              className="px-2.5 py-1 text-[#94a3b8] flex items-center gap-1.5 cursor-not-allowed text-[11px]"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#cbd5e1]" />
              <span>Traffic N/A</span>
            </div>
            <div className="w-[1px] h-4 bg-[#cbd5e1]" />
          </>
        )}

        {hasTomTomKey ? (
          <>
            <button
              onClick={() => setBaseLayerType('tomtom')}
              title="TomTom Street Basemap"
              className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
                baseLayerType === 'tomtom' || (baseLayerType === 'streets' && baseMapStatus.provider === 'tomtom')
                  ? 'bg-[#0b1c30] text-white shadow-xs'
                  : 'text-[#475569] hover:text-[#0b1c30]'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">map</span>
              <span>TomTom</span>
            </button>
            <button
              onClick={() => setBaseLayerType('osm')}
              title="OpenStreetMap Basemap"
              className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
                baseLayerType === 'osm' || (baseLayerType === 'streets' && baseMapStatus.provider === 'osm')
                  ? 'bg-[#0b1c30] text-white shadow-xs'
                  : 'text-[#475569] hover:text-[#0b1c30]'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">public</span>
              <span>OSM</span>
            </button>
          </>
        ) : (
          <button
            onClick={() => setBaseLayerType('osm')}
            title="OpenStreetMap Basemap"
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
              baseLayerType === 'osm' || baseLayerType === 'streets'
                ? 'bg-[#0b1c30] text-white shadow-xs'
                : 'text-[#475569] hover:text-[#0b1c30]'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">map</span>
            <span>OpenStreetMap</span>
          </button>
        )}

        <button
          onClick={() => setBaseLayerType('satellite')}
          title="Esri World Imagery Satellite Basemap"
          className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
            baseLayerType === 'satellite'
              ? 'bg-[#0b1c30] text-white shadow-xs'
              : 'text-[#475569] hover:text-[#0b1c30]'
          }`}
        >
          <span className="material-symbols-outlined text-[14px]">satellite_alt</span>
          <span>Satellite</span>
        </button>
      </div>

      {/* Provider Status Indicator */}
      <div className="absolute bottom-2 left-3 z-[999] pointer-events-none">
        <div
          title={
            baseMapStatus.errorDetails ||
            (baseMapStatus.isFallback
              ? `Fallback active: ${baseMapStatus.fallbackReason}`
              : `${baseMapStatus.displayName} active`)
          }
          className="bg-white/90 backdrop-blur-xs px-2.5 py-1 rounded shadow-xs border border-[#e2e8f0] text-[10px] text-[#475569] flex items-center gap-1.5 pointer-events-auto"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              baseMapStatus.status === 'active'
                ? baseMapStatus.isFallback
                  ? 'bg-[#b45309]'
                  : 'bg-[#138808]'
                : baseMapStatus.status === 'loading'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-[#ba1a1a]'
            }`}
          />
          <span className="font-medium text-[#0b1c30]">
            Basemap: {baseMapStatus.displayName}
            {baseMapStatus.isFallback ? ' (OSM Fallback)' : ''}
          </span>
          {showTraffic && hasTomTomKey && (
            <>
              <span className="text-[#cbd5e1]">|</span>
              <span
                className={`flex items-center gap-1 ${
                  trafficStatus.status === 'active'
                    ? 'text-[#138808] font-medium'
                    : trafficStatus.status === 'loading'
                      ? 'text-[#b45309]'
                      : 'text-[#ba1a1a]'
                }`}
              >
                Traffic: {trafficStatus.status === 'active'
                  ? 'TomTom Flow Active'
                  : trafficStatus.status === 'loading'
                    ? 'Connecting...'
                    : 'Unavailable'}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
