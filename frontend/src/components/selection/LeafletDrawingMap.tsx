import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

export interface Point {
  lat: number
  lng: number
}

interface LeafletDrawingMapProps {
  isDrawing: boolean
  draftPoints: Point[]
  savedCoords: Point[]
  onAddDraftPoint: (point: Point) => void
  onCompletePolygon: () => void
  className?: string
  presetTrigger?: { coords: Point[]; timestamp: number } | null
}

export default function LeafletDrawingMap({
  isDrawing,
  draftPoints,
  savedCoords,
  onAddDraftPoint,
  onCompletePolygon,
  className = 'w-full h-full',
  presetTrigger,
}: LeafletDrawingMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Layers
  const baseTileRef = useRef<L.TileLayer | null>(null)
  const trafficTileRef = useRef<L.TileLayer | null>(null)
  const draftPolylineRef = useRef<L.Polyline | null>(null)
  const draftMarkersGroupRef = useRef<L.LayerGroup | null>(null)
  const completedPolygonRef = useRef<L.Polygon | null>(null)

  const [baseLayerType, setBaseLayerType] = useState<'streets' | 'satellite'>('streets')
  const [showTraffic, setShowTraffic] = useState(false)

  const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY

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
    })

    // Custom zoom control
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    // Base Street Layer: TomTom Map Display if key configured, fallback to OSM HOT
    const streetTile = TOMTOM_KEY
      ? L.tileLayer(
          `https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=${TOMTOM_KEY}`,
          {
            maxZoom: 19,
            subdomains: ['a', 'b', 'c', 'd'],
            attribution:
              '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom</a>, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>',
          },
        )
      : L.tileLayer(
          'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
          {
            maxZoom: 19,
            subdomains: 'abc',
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors, Tiles style by <a href="https://www.hotosm.org/" target="_blank" rel="noopener noreferrer">HOT</a>',
          },
        )

    streetTile.addTo(map)
    baseTileRef.current = streetTile
    draftMarkersGroupRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // 2. Switch Base Layer (Streets vs Satellite)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (baseTileRef.current) {
      map.removeLayer(baseTileRef.current)
    }

    if (baseLayerType === 'satellite') {
      baseTileRef.current = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 19,
          attribution:
            'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        },
      ).addTo(map)
    } else {
      baseTileRef.current = TOMTOM_KEY
        ? L.tileLayer(
            `https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=${TOMTOM_KEY}`,
            {
              maxZoom: 19,
              subdomains: ['a', 'b', 'c', 'd'],
              attribution:
                '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom</a>, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>',
            },
          ).addTo(map)
        : L.tileLayer(
            'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
            {
              maxZoom: 19,
              subdomains: 'abc',
              attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors, Tiles style by <a href="https://www.hotosm.org/" target="_blank" rel="noopener noreferrer">HOT</a>',
            },
          ).addTo(map)
    }
  }, [baseLayerType])

  // 2b. TomTom Live Traffic Flow Tile Overlay
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (trafficTileRef.current) {
      map.removeLayer(trafficTileRef.current)
      trafficTileRef.current = null
    }

    if (showTraffic && TOMTOM_KEY) {
      trafficTileRef.current = L.tileLayer(
        `https://{s}.api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=${TOMTOM_KEY}`,
        {
          maxZoom: 19,
          subdomains: ['a', 'b', 'c', 'd'],
          opacity: 0.85,
          attribution:
            '&copy; <a href="https://www.tomtom.com" target="_blank" rel="noopener noreferrer">TomTom Traffic</a>',
        },
      ).addTo(map)
    }
  }, [showTraffic])

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

  // 6. Handle Preset Trigger Smooth Fly-To
  useEffect(() => {
    const map = mapRef.current
    if (!map || !presetTrigger || presetTrigger.coords.length === 0) return

    const latLngs: L.LatLngExpression[] = presetTrigger.coords.map((p) => [p.lat, p.lng])
    const bounds = L.latLngBounds(latLngs)
    if (bounds.isValid()) {
      map.flyToBounds(bounds, { padding: [45, 45], duration: 1.0 })
    }
  }, [presetTrigger])

  return (
    <div className="relative w-full h-full">
      {/* Map DOM node */}
      <div ref={containerRef} className={className} />

      {/* Layer Switcher & TomTom Live Traffic */}
      <div className="absolute top-4 right-16 z-[1000] flex items-center gap-1.5 bg-white/95 backdrop-blur-xs rounded-lg shadow-md border border-[#e2e8f0] p-0.5 text-xs font-semibold">
        {TOMTOM_KEY && (
          <>
            <button
              onClick={() => setShowTraffic(!showTraffic)}
              title="Toggle Live TomTom Real-Time Traffic Flow"
              className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                showTraffic
                  ? 'bg-[#138808] text-white shadow-xs'
                  : 'text-[#475569] hover:text-[#0b1c30]'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${showTraffic ? 'bg-white animate-pulse' : 'bg-[#138808]'}`}></span>
              <span>Live Traffic</span>
            </button>
            <div className="w-[1px] h-4 bg-[#cbd5e1]" />
          </>
        )}

        <button
          onClick={() => setBaseLayerType('streets')}
          className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
            baseLayerType === 'streets'
              ? 'bg-[#0b1c30] text-white shadow-xs'
              : 'text-[#475569] hover:text-[#0b1c30]'
          }`}
        >
          <span className="material-symbols-outlined text-[14px]">map</span>
          <span>{TOMTOM_KEY ? 'TomTom Streets' : 'Streets'}</span>
        </button>
        <button
          onClick={() => setBaseLayerType('satellite')}
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
    </div>
  )
}
