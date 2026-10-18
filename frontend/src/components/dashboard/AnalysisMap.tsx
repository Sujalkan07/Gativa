import { useEffect, useRef, useState, useCallback } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type {
  GeoJSONPolygon,
  RoadSegment,
  BottleneckCandidate,
  Recommendation,
} from '../../types/api'

interface AnalysisMapProps {
  polygon: GeoJSONPolygon
  segments: RoadSegment[]
  bottlenecks: BottleneckCandidate[]
  recommendations?: Recommendation[]
  mode?: 'topology' | 'flow'
  selectedBottleneckId?: string | null
  onSelectBottleneck?: (id: string) => void
  selectedRecommendationId?: string | null
  onSelectRecommendation?: (id: string) => void
  className?: string
}

export default function AnalysisMap({
  polygon,
  segments,
  bottlenecks,
  recommendations = [],
  mode = 'topology',
  selectedBottleneckId,
  onSelectBottleneck,
  selectedRecommendationId,
  onSelectRecommendation,
  className = 'w-full h-[520px]',
}: AnalysisMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Layer groups refs
  const baseTileLayerRef = useRef<L.TileLayer | null>(null)
  const polygonLayerRef = useRef<L.Polygon | null>(null)
  const roadsGroupRef = useRef<L.LayerGroup | null>(null)
  const bottlenecksGroupRef = useRef<L.LayerGroup | null>(null)
  const recommendationsGroupRef = useRef<L.LayerGroup | null>(null)
  const markersMapRef = useRef<Map<string, L.Marker>>(new Map())

  // Controls state
  const [baseLayerType, setBaseLayerType] = useState<'streets' | 'satellite'>('streets')
  const [showRoads, setShowRoads] = useState(true)
  const [showBottlenecks, setShowBottlenecks] = useState(true)
  const [showRecommendations, setShowRecommendations] = useState(true)

  // 1. Initialize Leaflet Map
  useEffect(() => {
    if (!containerRef.current) return
    if (mapRef.current) return

    // Create map instance
    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: false,
    })

    // Add zoom control in bottom-right
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    // Base street tile layer (CartoDB Voyager: high contrast, real road & junction names)
    const streetTile = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      {
        maxZoom: 19,
        subdomains: 'abcd',
      },
    ).addTo(map)

    baseTileLayerRef.current = streetTile
    roadsGroupRef.current = L.layerGroup().addTo(map)
    bottlenecksGroupRef.current = L.layerGroup().addTo(map)
    recommendationsGroupRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // 2. Switch Base Tile Layer (Streets vs Satellite)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (baseTileLayerRef.current) {
      map.removeLayer(baseTileLayerRef.current)
    }

    if (baseLayerType === 'satellite') {
      baseTileLayerRef.current = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19 },
      ).addTo(map)
    } else {
      baseTileLayerRef.current = L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
        { maxZoom: 19, subdomains: 'abcd' },
      ).addTo(map)
    }
  }, [baseLayerType])

  // 3. Render Polygon Boundary & Fit Bounds
  useEffect(() => {
    const map = mapRef.current
    if (!map || !polygon || !polygon.coordinates || polygon.coordinates.length === 0) return

    if (polygonLayerRef.current) {
      map.removeLayer(polygonLayerRef.current)
      polygonLayerRef.current = null
    }

    const ring = polygon.coordinates[0]
    const latLngs: L.LatLngExpression[] = ring.map((c) => [c[1], c[0]])

    const polyLayer = L.polygon(latLngs, {
      color: '#ff9933', // India Saffron
      weight: 3,
      dashArray: '6, 6',
      fillColor: '#ff9933',
      fillOpacity: 0.12,
    }).addTo(map)

    polygonLayerRef.current = polyLayer

    // Fit map bounds to exact user selected polygon
    try {
      const bounds = polyLayer.getBounds()
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [35, 35] })
      }
    } catch {
      // Ignore initial layout bounds
    }
  }, [polygon])

  // 4. Render Road Segments
  useEffect(() => {
    const roadsGroup = roadsGroupRef.current
    if (!roadsGroup) return

    roadsGroup.clearLayers()
    if (!showRoads) return

    segments.forEach((seg) => {
      if (!seg.geometry || !seg.geometry.coordinates || seg.geometry.coordinates.length < 2) return

      const latLngs: L.LatLngExpression[] = seg.geometry.coordinates.map((c) => [c[1], c[0]])

      let color = '#64748b' // default local slate
      let weight = 2.5
      let opacity = 0.75

      if (mode === 'flow') {
        // Congestion / Level of Service flow colors
        const level = seg.traffic?.congestion_level
        if (level === 'severe') {
          color = '#ba1a1a'
          weight = 5
          opacity = 0.95
        } else if (level === 'moderate') {
          color = '#ff9933'
          weight = 4
          opacity = 0.9
        } else if (level === 'free_flow') {
          color = '#138808'
          weight = 3.5
          opacity = 0.85
        } else {
          color = '#94a3b8'
          weight = 2
          opacity = 0.6
        }
      } else {
        // Road classification topology colors
        if (seg.road_type === 'highway') {
          color = '#ff9933' // Orange
          weight = 5
          opacity = 0.95
        } else if (seg.road_type === 'arterial') {
          color = '#2d3b8f' // Royal Navy
          weight = 3.5
          opacity = 0.9
        } else {
          color = '#64748b' // Slate
          weight = 2
          opacity = 0.65
        }
      }

      const polyline = L.polyline(latLngs, {
        color,
        weight,
        opacity,
        lineCap: 'round',
        lineJoin: 'round',
      })

      // Interactive Tooltip showing Real Street Name & Attributes
      const roadTitle = seg.name || (seg.road_type === 'highway' ? 'Highway Corridor' : seg.road_type === 'arterial' ? 'Arterial Corridor' : 'Connecting Street')
      const speedObs = seg.traffic?.observed_speed_kmh
        ? `${seg.traffic.observed_speed_kmh.toFixed(0)} km/h`
        : 'Free Flow'

      polyline.bindTooltip(
        `<div class="font-sans text-xs">
          <p class="font-bold text-[#0b1c30] text-[13px]">${roadTitle}</p>
          <div class="flex items-center gap-2 mt-1 text-[#554336]">
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
              seg.road_type === 'highway'
                ? 'bg-[#ffeedb] text-[#855400]'
                : seg.road_type === 'arterial'
                ? 'bg-[#e0e0ff] text-[#2d3b8f]'
                : 'bg-[#f1f5f9] text-[#475569]'
            }">${seg.road_type}</span>
            <span>${seg.length_m.toFixed(0)}m</span>
            <span>• Speed: ${speedObs}</span>
          </div>
        </div>`,
        { sticky: true, opacity: 0.95 },
      )

      roadsGroup.addLayer(polyline)
    })
  }, [segments, showRoads, mode])

  // 5. Render Problem Markers (Bottlenecks)
  useEffect(() => {
    const bGroup = bottlenecksGroupRef.current
    if (!bGroup) return

    bGroup.clearLayers()
    if (!showBottlenecks) return

    bottlenecks.forEach((b, idx) => {
      const isHigh = b.severity === 'high'
      const label = `B#${idx + 1}`

      // Create Custom Pulsating HTML Pin
      const icon = L.divIcon({
        className: 'custom-problem-pin',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -16],
        html: `
          <div class="relative w-8 h-8 flex items-center justify-center cursor-pointer group">
            <span class="absolute w-8 h-8 rounded-full ${
              isHigh ? 'bg-[#ba1a1a]/40 animate-ping' : 'bg-[#ff9933]/40'
            }"></span>
            <div class="relative w-7 h-7 rounded-full flex items-center justify-center shadow-lg border-2 border-white font-mono text-[10px] font-bold text-white transition-transform transform group-hover:scale-110 ${
              isHigh ? 'bg-[#ba1a1a]' : 'bg-[#e68a00]'
            }">
              ${label}
            </div>
          </div>
        `,
      })

      const marker = L.marker([b.lat, b.lng], { icon })

      const locationLabel = b.location_name || `Junction ${b.segment_id}`

      // Find matching recommendation if available
      const matchingRec = recommendations.find(
        (r) => r.affected_segment_ids.includes(b.segment_id) || (r.lat && Math.abs(r.lat - b.lat) < 0.001)
      )

      const popupHtml = `
        <div class="font-sans p-1 text-xs max-w-[270px]">
          <div class="flex items-center justify-between gap-2 border-b border-[#e2e8f0] pb-1.5 mb-2">
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 rounded-full ${isHigh ? 'bg-[#ba1a1a]' : 'bg-[#ff9933]'}"></span>
              <span class="font-bold text-[#ba1a1a] text-xs uppercase tracking-tight">Traffic Problem ${label}</span>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
              isHigh ? 'bg-[#ffdad6] text-[#ba1a1a]' : 'bg-[#ffeedb] text-[#855400]'
            }">${b.severity}</span>
          </div>

          <p class="font-bold text-[#0b1c30] text-sm leading-snug mb-1.5">${locationLabel}</p>

          <div class="bg-[#f8f9ff] p-2 rounded-lg border border-[#e0e7ff] mb-2">
            <p class="text-[10px] font-semibold text-[#545a90] uppercase mb-1">Diagnosis Evidence</p>
            <ul class="text-[11px] text-[#334155] space-y-0.5 pl-3 list-disc">
              ${b.evidence.map((ev) => `<li>${ev}</li>`).join('')}
            </ul>
          </div>

          ${
            matchingRec
              ? `<div class="bg-[#e6f4ea] border border-[#a8dab5] p-2 rounded-lg text-[11px] text-[#0d652d]">
                  <p class="font-bold">Proposed Fix: ${matchingRec.title}</p>
                  <p class="text-[10px] text-[#137333] mt-0.5">Impact Score: ${matchingRec.impact_score.toFixed(1)}/10</p>
                 </div>`
              : ''
          }
        </div>
      `

      marker.bindPopup(popupHtml, { maxWidth: 300 })
      marker.on('click', () => {
        if (onSelectBottleneck) {
          onSelectBottleneck(b.segment_id)
        }
      })

      markersMapRef.current.set(`bottleneck_${b.segment_id}`, marker)
      bGroup.addLayer(marker)
    })
  }, [bottlenecks, showBottlenecks, recommendations, onSelectBottleneck])

  // 6. Render Solution Markers (Recommendations)
  useEffect(() => {
    const rGroup = recommendationsGroupRef.current
    if (!rGroup) return

    rGroup.clearLayers()
    if (!showRecommendations || recommendations.length === 0) return

    recommendations.forEach((rec, idx) => {
      if (!rec.lat || !rec.lng) return

      const label = `S#${idx + 1}`

      const icon = L.divIcon({
        className: 'custom-solution-pin',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -16],
        html: `
          <div class="relative w-8 h-8 flex items-center justify-center cursor-pointer group">
            <span class="absolute w-7 h-7 rounded-full bg-[#006a6a]/30"></span>
            <div class="relative w-7 h-7 rounded-full flex items-center justify-center shadow-lg border-2 border-white font-mono text-[10px] font-bold text-white bg-[#006a6a] transition-transform transform group-hover:scale-110">
              ${label}
            </div>
          </div>
        `,
      })

      const marker = L.marker([rec.lat, rec.lng], { icon })

      const locationLabel = rec.affected_location || 'Corridor Intervention'

      const popupHtml = `
        <div class="font-sans p-1 text-xs max-w-[280px]">
          <div class="flex items-center justify-between gap-2 border-b border-[#e2e8f0] pb-1.5 mb-2">
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 rounded-full bg-[#006a6a]"></span>
              <span class="font-bold text-[#006a6a] text-xs uppercase tracking-tight">Solution ${label}</span>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[#cce8e8] text-[#004f4f]">${rec.priority} Priority</span>
          </div>

          <p class="font-bold text-[#0b1c30] text-sm leading-snug mb-1">${rec.title}</p>
          <p class="text-[11px] text-[#554336] mb-2 font-medium">📍 ${locationLabel}</p>

          <div class="bg-[#f0fdf4] p-2 rounded-lg border border-[#bbf7d0] mb-2">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10px] font-bold uppercase text-[#166534]">Impact Rating</span>
              <span class="font-mono font-bold text-xs text-[#166534]">${rec.impact_score.toFixed(1)} / 10</span>
            </div>
            <p class="text-[11px] text-[#1e293b] leading-relaxed">${rec.description}</p>
          </div>

          <div class="flex items-center justify-between text-[10px] text-[#64748b] bg-[#f8fafc] p-1.5 rounded">
            <span>Intervention: <strong>${rec.intervention_type.replace('_', ' ')}</strong></span>
            <span>Confidence: <strong>${rec.confidence}</strong></span>
          </div>
        </div>
      `

      marker.bindPopup(popupHtml, { maxWidth: 320 })
      marker.on('click', () => {
        if (onSelectRecommendation) {
          onSelectRecommendation(rec.recommendation_id)
        }
      })

      markersMapRef.current.set(`rec_${rec.recommendation_id}`, marker)
      rGroup.addLayer(marker)
    })
  }, [recommendations, showRecommendations, onSelectRecommendation])

  // 7. Handle fly-to when selected from side diagnostics
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (selectedBottleneckId) {
      const b = bottlenecks.find((item) => item.segment_id === selectedBottleneckId)
      if (b) {
        map.flyTo([b.lat, b.lng], 16, { duration: 0.8 })
        const marker = markersMapRef.current.get(`bottleneck_${b.segment_id}`)
        if (marker) {
          marker.openPopup()
        }
      }
    }
  }, [selectedBottleneckId, bottlenecks])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (selectedRecommendationId) {
      const r = recommendations.find((item) => item.recommendation_id === selectedRecommendationId)
      if (r && r.lat && r.lng) {
        map.flyTo([r.lat, r.lng], 16, { duration: 0.8 })
        const marker = markersMapRef.current.get(`rec_${r.recommendation_id}`)
        if (marker) {
          marker.openPopup()
        }
      }
    }
  }, [selectedRecommendationId, recommendations])

  // Reset view to polygon
  const handleResetView = useCallback(() => {
    const map = mapRef.current
    const polyLayer = polygonLayerRef.current
    if (map && polyLayer) {
      map.fitBounds(polyLayer.getBounds(), { padding: [35, 35] })
    }
  }, [])

  return (
    <div className={`relative rounded-xl overflow-hidden shadow-sm border border-[var(--color-surface-container-high)] ${className}`}>
      {/* Map Surface */}
      <div ref={containerRef} className="w-full h-full z-0" />

      {/* Top Floating Map Controls */}
      <div className="absolute top-3 left-3 right-3 z-10 pointer-events-none flex flex-wrap items-center justify-between gap-2">
        {/* Left: Mode / Legend indicator */}
        <div className="pointer-events-auto bg-[var(--color-surface-container-lowest)]/95 backdrop-blur-md px-3 py-1.5 rounded-lg shadow-md border border-[var(--color-surface-container-high)] flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 font-bold text-[var(--color-on-surface)]">
            <span className="material-symbols-outlined text-[16px] text-[var(--color-primary-container)]">
              map
            </span>
            <span>Real Geographic Analysis</span>
          </div>
          <span className="text-[var(--color-surface-container-high)]">|</span>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-on-surface-variant)]">
              <span className="w-2.5 h-1.5 rounded-sm bg-[#ff9933]"></span> Selected Area
            </span>
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-on-surface-variant)]">
              <span className="w-2.5 h-1.5 rounded-sm bg-[#2d3b8f]"></span> Roads
            </span>
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-error)] font-semibold">
              <span className="w-2 h-2 rounded-full bg-[#ba1a1a]"></span> Problems ({bottlenecks.length})
            </span>
            {recommendations.length > 0 && (
              <span className="flex items-center gap-1 text-[11px] text-[#006a6a] font-semibold">
                <span className="w-2 h-2 rounded-full bg-[#006a6a]"></span> Solutions ({recommendations.length})
              </span>
            )}
          </div>
        </div>

        {/* Right: Active Toggles & Style Switcher */}
        <div className="pointer-events-auto bg-[var(--color-surface-container-lowest)]/95 backdrop-blur-md p-1 rounded-lg shadow-md border border-[var(--color-surface-container-high)] flex items-center gap-1 text-xs">
          {/* Layer toggles */}
          <button
            onClick={() => setShowRoads(!showRoads)}
            title="Toggle Roads"
            className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
              showRoads
                ? 'bg-[var(--color-surface-container-high)] text-[var(--color-on-surface)]'
                : 'text-[var(--color-on-surface-variant)] opacity-50'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">alt_route</span>
            Roads
          </button>

          <button
            onClick={() => setShowBottlenecks(!showBottlenecks)}
            title="Toggle Problem Markers"
            className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
              showBottlenecks
                ? 'bg-[#ffdad6] text-[#ba1a1a]'
                : 'text-[var(--color-on-surface-variant)] opacity-50'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">warning</span>
            Problems
          </button>

          {recommendations.length > 0 && (
            <button
              onClick={() => setShowRecommendations(!showRecommendations)}
              title="Toggle Solutions"
              className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                showRecommendations
                  ? 'bg-[#cce8e8] text-[#004f4f]'
                  : 'text-[var(--color-on-surface-variant)] opacity-50'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">build</span>
              Solutions
            </button>
          )}

          <span className="text-[var(--color-surface-container-high)]">|</span>

          {/* Streets vs Satellite */}
          <button
            onClick={() => setBaseLayerType(baseLayerType === 'streets' ? 'satellite' : 'streets')}
            className="px-2 py-1 rounded text-xs font-bold bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] hover:opacity-90 transition-opacity flex items-center gap-1"
          >
            <span className="material-symbols-outlined text-[14px]">
              {baseLayerType === 'streets' ? 'satellite_alt' : 'streetview'}
            </span>
            {baseLayerType === 'streets' ? 'Satellite' : 'Streets'}
          </button>

          <button
            onClick={handleResetView}
            title="Reset to Area Boundary"
            className="w-7 h-7 rounded flex items-center justify-center text-[var(--color-secondary)] hover:bg-[var(--color-surface-container)] transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">crop_free</span>
          </button>
        </div>
      </div>

      {/* Bottom Hint */}
      <div className="absolute bottom-2.5 left-3 z-10 pointer-events-none">
        <div className="bg-[var(--color-surface-container-lowest)]/90 backdrop-blur-sm px-2.5 py-1 rounded text-[11px] text-[var(--color-on-surface-variant)] shadow-sm border border-[var(--color-surface-container-high)]">
          💡 Click any <span className="font-bold text-[#ba1a1a]">B#</span> or <span className="font-bold text-[#006a6a]">S#</span> pin to inspect problems & civil solutions
        </div>
      </div>
    </div>
  )
}
