import { useEffect, useRef, useState, useCallback } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { escapeHtml } from '../../lib/sanitize'
import { classifyTrafficFlow } from '../../lib/trafficClassification'
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
import type {
  GeoJSONPolygon,
  RoadSegment,
  BottleneckCandidate,
  Recommendation,
  TrafficIncident,
} from '../../types/api'

interface AnalysisMapProps {
  polygon: GeoJSONPolygon
  segments: RoadSegment[]
  bottlenecks: BottleneckCandidate[]
  recommendations?: Recommendation[]
  incidents?: TrafficIncident[]
  mode?: 'topology' | 'flow'
  selectedBottleneckId?: string | null
  onSelectBottleneck?: (id: string) => void
  selectedRecommendationId?: string | null
  onSelectRecommendation?: (id: string) => void
  selectedSegmentId?: string | null
  onSelectSegment?: (id: string | null) => void
  selectedIncidentId?: string | null
  onSelectIncident?: (id: string | null) => void
  className?: string
}

export default function AnalysisMap({
  polygon,
  segments,
  bottlenecks,
  recommendations = [],
  incidents = [],
  mode = 'topology',
  selectedBottleneckId,
  onSelectBottleneck,
  selectedRecommendationId,
  onSelectRecommendation,
  selectedSegmentId,
  onSelectSegment,
  selectedIncidentId,
  onSelectIncident,
  className = 'w-full h-[520px]',
}: AnalysisMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Layer groups refs
  const baseTileHandleRef = useRef<BaseTileLayerHandle | null>(null)
  const trafficTileHandleRef = useRef<TrafficLayerHandle | null>(null)
  const polygonLayerRef = useRef<L.Polygon | null>(null)
  const roadsGroupRef = useRef<L.LayerGroup | null>(null)
  const incidentsGroupRef = useRef<L.LayerGroup | null>(null)
  const bottlenecksGroupRef = useRef<L.LayerGroup | null>(null)
  const recommendationsGroupRef = useRef<L.LayerGroup | null>(null)
  const markersMapRef = useRef<Map<string, L.Marker>>(new Map())
  const incidentMarkersMapRef = useRef<Map<string, L.Layer>>(new Map())
  const segmentLayersMapRef = useRef<Map<string, L.Polyline>>(new Map())

  const hasTomTomKey = Boolean(getTomTomApiKey())

  // Controls state
  const [baseLayerType, setBaseLayerType] = useState<BaseLayerType>('streets')
  const [showRoads, setShowRoads] = useState(true)
  const [showIncidents, setShowIncidents] = useState(true)
  const [showClosuresOnly, setShowClosuresOnly] = useState(false)
  const [showBottlenecks, setShowBottlenecks] = useState(mode !== 'flow')
  const [showRecommendations, setShowRecommendations] = useState(true)
  const [showTomTomTraffic, setShowTomTomTraffic] = useState(true)
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

  const handleToggleTomTomTraffic = () => {
    setShowTomTomTraffic((prev) => {
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

  // 1. Initialize Leaflet Map
  useEffect(() => {
    if (!containerRef.current) return
    if (mapRef.current) return

    // Derive initial centroid so Leaflet's _loaded is true on frame 0
    const ring = polygon?.coordinates?.[0]
    const initialCenter: [number, number] = ring?.length
      ? [
          ring.reduce((sum, c) => sum + c[1], 0) / ring.length,
          ring.reduce((sum, c) => sum + c[0], 0) / ring.length,
        ]
      : [26.900, 80.942]

    // Create map instance
    const map = L.map(containerRef.current, {
      center: initialCenter,
      zoom: 14,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
    })

    // Add zoom control in bottom-right
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    roadsGroupRef.current = L.layerGroup().addTo(map)
    incidentsGroupRef.current = L.layerGroup().addTo(map)
    bottlenecksGroupRef.current = L.layerGroup().addTo(map)
    recommendationsGroupRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    // Ensure immediate and accurate layout sizing (prevents grey tiles when tab opens or grid computes)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 2. Switch Base Tile Layer (Streets vs Satellite)
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

  // 2b. TomTom Real-Time Traffic Flow Tile Overlay
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (trafficTileHandleRef.current) {
      trafficTileHandleRef.current.cleanup()
      trafficTileHandleRef.current = null
    }

    if (showTomTomTraffic && hasTomTomKey) {
      trafficTileHandleRef.current = attachTomTomTrafficLayer(map, {
        onStatusChange: (status) => setTrafficStatus(status),
      })
    }
  }, [showTomTomTraffic, hasTomTomKey])

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

    // Invalidate size first to ensure Leaflet has up-to-date viewport pixels
    map.invalidateSize({ animate: false })

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
    segmentLayersMapRef.current.clear()
    if (!showRoads) return

    segments.forEach((seg) => {
      if (seg.is_buffer) return // Core analysis map presents the user's selected study area roads
      if (!seg.geometry || !seg.geometry.coordinates || seg.geometry.coordinates.length < 2) return

      const isClosed = seg.traffic?.congestion_level === 'closed' || seg.traffic?.road_closure === true
      if (showClosuresOnly && !isClosed) return

      const latLngs: L.LatLngExpression[] = seg.geometry.coordinates.map((c) => [c[1], c[0]])
      const isSelected = seg.segment_id === selectedSegmentId
      const isLowMatch = seg.traffic?.match_quality === 'low' || seg.traffic?.match_quality === 'unmatched'

      let color = '#64748b' // default local slate
      let weight = isSelected ? 5.5 : 2.5
      let opacity = 0.75
      let dashArray: string | undefined = undefined

      const sci = classifyTrafficFlow(
        seg.traffic?.observed_speed_kmh,
        seg.traffic?.free_flow_speed_kmh,
        isClosed
      )

      if (mode === 'flow') {
        color = sci.mapColor
        weight = sci.mapWeight(isSelected)
        opacity = sci.mapOpacity
        if (isClosed) {
          dashArray = '6, 6'
        } else if (isLowMatch) {
          dashArray = '4, 4'
        }
      } else {
        // Road classification topology colors
        if (seg.road_type === 'highway') {
          color = '#ff9933' // Orange
          weight = isSelected ? 7 : 5
          opacity = 0.95
        } else if (seg.road_type === 'arterial') {
          color = '#2d3b8f' // Royal Navy
          weight = isSelected ? 5.5 : 3.5
          opacity = 0.9
        } else {
          color = '#64748b' // Slate
          weight = isSelected ? 4 : 2
          opacity = 0.65
        }
      }

      const polyline = L.polyline(latLngs, {
        color,
        weight,
        opacity,
        dashArray,
        lineCap: 'round',
        lineJoin: 'round',
      })

      const roadTitle = seg.name || (seg.road_type === 'highway' ? 'Highway Corridor' : seg.road_type === 'arterial' ? 'Arterial Corridor' : 'Connecting Street')

      if (mode === 'flow') {
        const obs = seg.traffic?.observed_speed_kmh != null ? `${seg.traffic.observed_speed_kmh.toFixed(1)} km/h` : 'Unobserved'
        const ff = seg.traffic?.free_flow_speed_kmh != null ? `${seg.traffic.free_flow_speed_kmh.toFixed(1)} km/h` : '—'
        const delayStr = seg.traffic?.delay_seconds != null
          ? `+${seg.traffic.delay_seconds.toFixed(0)}s (${(seg.traffic.delay_percentage ?? 0).toFixed(0)}%)`
          : '—'
        const confStr = seg.traffic?.confidence != null ? `${Math.round(seg.traffic.confidence * 100)}%` : '—'
        const matchStr = seg.traffic?.match_quality
          ? `${seg.traffic.match_quality}${seg.traffic.match_distance_m != null ? ` (${seg.traffic.match_distance_m.toFixed(1)}m)` : ''}`
          : 'osm-midpoint'

        const statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${sci.badgeClass}">${escapeHtml(sci.grade)}</span>`

        polyline.bindTooltip(
          `<div class="font-sans text-xs min-w-[210px]">
            <div class="flex items-center justify-between gap-1 pb-1 mb-1 border-b border-slate-200">
              <span class="font-bold text-[#0b1c30] text-[13px] truncate">${escapeHtml(roadTitle)}</span>
              ${statusBadge}
            </div>
            <div class="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-[#334155] my-1">
              <div><span class="text-slate-500">Observed:</span> <strong>${obs}</strong></div>
              <div><span class="text-slate-500">Free-Flow:</span> <strong>${ff}</strong></div>
              <div><span class="text-slate-500">Delay:</span> <strong>${delayStr}</strong></div>
              <div><span class="text-slate-500">TomTom Confidence:</span> <strong>${confStr}</strong></div>
            </div>
            <div class="text-[10px] text-slate-500 border-t border-slate-100 pt-1 flex justify-between">
              <span>${escapeHtml(seg.road_type)} • ${seg.length_m.toFixed(0)}m</span>
              <span>Match: ${escapeHtml(matchStr)}</span>
            </div>
          </div>`,
          { sticky: true, opacity: 0.98 }
        )
      } else {
        const speedObs = seg.traffic?.observed_speed_kmh != null
          ? `${seg.traffic.observed_speed_kmh.toFixed(0)} km/h`
          : 'Free Flow'

        polyline.bindTooltip(
          `<div class="font-sans text-xs">
            <p class="font-bold text-[#0b1c30] text-[13px]">${escapeHtml(roadTitle)}</p>
            <div class="flex flex-wrap items-center gap-1.5 mt-1 text-[#554336]">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                seg.road_type === 'highway'
                  ? 'bg-[#ffeedb] text-[#855400]'
                  : seg.road_type === 'arterial'
                  ? 'bg-[#e0e0ff] text-[#2d3b8f]'
                  : 'bg-[#f1f5f9] text-[#475569]'
              }">${escapeHtml(seg.road_type)}</span>
              ${seg.osm_highway ? `<span class="text-[10px] font-mono text-slate-500">osm:${escapeHtml(seg.osm_highway)}</span>` : ''}
              <span>• ${seg.length_m.toFixed(0)}m</span>
              <span>• ${seg.is_oneway ? '1-way' : '2-way'}</span>
              ${seg.lanes ? `<span>• ${seg.lanes}L</span>` : ''}
              <span>• Speed: ${escapeHtml(speedObs)}</span>
            </div>
          </div>`,
          { sticky: true, opacity: 0.95 },
        )
      }

      polyline.on('mouseover', () => {
        polyline.setStyle({ weight: weight + 2.5, opacity: 1.0 })
      })
      polyline.on('mouseout', () => {
        polyline.setStyle({ weight, opacity })
      })
      polyline.on('click', () => {
        if (onSelectSegment) {
          onSelectSegment(seg.segment_id)
        }
      })

      segmentLayersMapRef.current.set(seg.segment_id, polyline)
      roadsGroup.addLayer(polyline)
    })
  }, [segments, showRoads, showClosuresOnly, mode, selectedSegmentId, onSelectSegment])

  // 4b. Render Traffic Incidents
  useEffect(() => {
    const incGroup = incidentsGroupRef.current
    if (!incGroup) return

    incGroup.clearLayers()
    incidentMarkersMapRef.current.clear()

    if (!showIncidents || !incidents || incidents.length === 0) return

    incidents.forEach((inc) => {
      // 1. If geometry is LineString, draw polyline on map
      if (
        inc.geometry &&
        inc.geometry.type === 'LineString' &&
        Array.isArray(inc.geometry.coordinates) &&
        inc.geometry.coordinates.length >= 2
      ) {
        const lineCoords: L.LatLngExpression[] = inc.geometry.coordinates.map((c: number[]) => [c[1], c[0]])
        const incLine = L.polyline(lineCoords, {
          color: '#ba1a1a',
          weight: 6,
          opacity: 0.85,
          dashArray: '6, 4',
          lineCap: 'round',
        })
        incLine.bindTooltip(
          `<div class="font-sans text-xs">
            <p class="font-bold text-[#ba1a1a]">${escapeHtml(inc.type)}</p>
            <p class="text-[11px] text-slate-700">${escapeHtml(inc.description || 'Traffic incident on corridor')}</p>
            ${inc.delay_seconds ? `<p class="font-bold text-red-700 text-[11px]">Delay: +${Math.round(inc.delay_seconds / 60)} min (${inc.delay_seconds.toFixed(0)}s)</p>` : ''}
          </div>`,
          { sticky: true }
        )
        incLine.on('click', () => {
          onSelectIncident?.(inc.incident_id)
        })
        incGroup.addLayer(incLine)
        incidentMarkersMapRef.current.set(`line_${inc.incident_id}`, incLine)
      }

      // 2. Incident Pin at [inc.lat, inc.lng] (skip if coordinates invalid or (0,0))
      if (
        inc.lat == null ||
        inc.lng == null ||
        isNaN(inc.lat) ||
        isNaN(inc.lng) ||
        (inc.lat === 0 && inc.lng === 0)
      ) {
        return
      }

      const delayBadge =
        inc.delay_seconds && inc.delay_seconds > 0
          ? `+${Math.round(inc.delay_seconds / 60)}m`
          : inc.severity_label || inc.severity || 'Alert'

      const isClosure =
        inc.type.toLowerCase().includes('closed') ||
        Boolean(inc.description && inc.description.toLowerCase().includes('closed')) ||
        Boolean(inc.icon_category_name && inc.icon_category_name.toLowerCase().includes('closure'))

      const pinBg = isClosure ? '#1e1b18' : '#ba1a1a'
      const pinIcon = isClosure ? 'block' : 'warning'

      const icon = L.divIcon({
        className: 'custom-incident-pin',
        iconSize: [30, 30],
        iconAnchor: [15, 15],
        popupAnchor: [0, -15],
        html: `
          <div class="relative w-7 h-7 flex items-center justify-center cursor-pointer group">
            <span class="absolute w-7 h-7 rounded-full bg-red-500/30 animate-ping"></span>
            <div class="relative w-6 h-6 rounded-full flex items-center justify-center shadow-lg border-2 border-white text-white font-bold" style="background-color: ${pinBg};">
              <span class="material-symbols-outlined text-[13px]">${pinIcon}</span>
            </div>
            <span class="absolute -bottom-2 bg-red-950 text-white text-[9px] px-1 py-0.2 rounded font-mono font-bold shadow-xs whitespace-nowrap">
              ${escapeHtml(delayBadge)}
            </span>
          </div>
        `,
      })

      const marker = L.marker([inc.lat, inc.lng], { icon })

      const popupHtml = `
        <div class="font-sans p-1 text-xs max-w-[280px]">
          <div class="flex items-center justify-between gap-2 border-b border-[#e2e8f0] pb-1.5 mb-2">
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 rounded-full" style="background-color: ${pinBg};"></span>
              <span class="font-bold text-xs uppercase tracking-tight text-[#ba1a1a]">${escapeHtml(inc.type)}</span>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
              isClosure ? 'bg-zinc-800 text-white' : 'bg-[#ffdad6] text-[#ba1a1a]'
            }">${escapeHtml(inc.severity_label || inc.severity || 'Active')}</span>
          </div>

          <p class="font-bold text-[#0b1c30] text-sm leading-snug mb-1">${escapeHtml(inc.description || 'Active incident impacting traffic corridor.')}</p>

          ${
            inc.road_numbers && inc.road_numbers.length > 0
              ? `<p class="text-[11px] text-[#554336] mb-1 font-semibold">Affected Corridor: ${escapeHtml(inc.road_numbers.join(', '))}</p>`
              : ''
          }
          ${
            inc.from_location || inc.to_location
              ? `<p class="text-[10px] text-slate-500 mb-1.5">Between: ${escapeHtml(inc.from_location || '—')} &rarr; ${escapeHtml(inc.to_location || '—')}</p>`
              : ''
          }

          <div class="bg-[#fef2f2] p-2 rounded border border-[#fecaca] mb-2 space-y-1">
            ${
              inc.delay_seconds != null
                ? `<div class="flex justify-between font-mono text-[11px]">
                    <span class="text-red-700 font-semibold">Incident Delay:</span>
                    <span class="font-bold text-red-900">+${inc.delay_seconds.toFixed(0)}s (+${Math.round(inc.delay_seconds / 60)} min)</span>
                   </div>`
                : ''
            }
            ${
              inc.length_m != null
                ? `<div class="flex justify-between font-mono text-[10px] text-slate-600">
                    <span>Impact Stretch:</span>
                    <span>${inc.length_m.toFixed(0)}m</span>
                   </div>`
                : ''
            }
            ${
              inc.start_time
                ? `<div class="flex justify-between text-[10px] text-slate-600">
                    <span>Incident started:</span>
                    <span>${new Date(inc.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                   </div>`
                : ''
            }
            ${
              inc.last_report_time
                ? `<div class="flex justify-between text-[10px] text-slate-600">
                    <span>Last reported:</span>
                    <span>${new Date(inc.last_report_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                   </div>`
                : ''
            }
            ${
              inc.end_time
                ? `<div class="flex justify-between text-[10px] text-slate-600">
                    <span>Incident ends:</span>
                    <span>${new Date(inc.end_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                   </div>`
                : ''
            }
            ${
              inc.retrieval_timestamp
                ? `<div class="flex justify-between text-[10px] text-slate-500">
                    <span>Retrieved:</span>
                    <span>${new Date(inc.retrieval_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                   </div>`
                : ''
            }
          </div>

          <div class="flex items-center justify-between text-[10px] text-[#64748b] bg-[#f8fafc] p-1.5 rounded">
            <span>Correlated Segments: <strong>${inc.affected_segment_ids.length}</strong></span>
            <span>Match: <strong>${escapeHtml(inc.match_quality || 'spatial')}</strong></span>
          </div>
        </div>
      `

      marker.bindPopup(popupHtml, { maxWidth: 300 })
      marker.on('click', () => {
        onSelectIncident?.(inc.incident_id)
      })

      incidentMarkersMapRef.current.set(`marker_${inc.incident_id}`, marker)
      incGroup.addLayer(marker)
    })
  }, [incidents, showIncidents, onSelectIncident])

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
              <span class="font-bold text-[#ba1a1a] text-xs uppercase tracking-tight">Traffic Problem ${escapeHtml(label)}</span>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
              isHigh ? 'bg-[#ffdad6] text-[#ba1a1a]' : 'bg-[#ffeedb] text-[#855400]'
            }">${escapeHtml(b.severity)}</span>
          </div>

          <p class="font-bold text-[#0b1c30] text-sm leading-snug mb-1.5">${escapeHtml(locationLabel)}</p>

          <div class="bg-[#f8f9ff] p-2 rounded-lg border border-[#e0e7ff] mb-2">
            <p class="text-[10px] font-semibold text-[#545a90] uppercase mb-1">Diagnosis Evidence</p>
            <ul class="text-[11px] text-[#334155] space-y-0.5 pl-3 list-disc">
              ${b.evidence.map((ev) => `<li>${escapeHtml(ev)}</li>`).join('')}
            </ul>
          </div>

          ${
            matchingRec
              ? `<div class="bg-[#e6f4ea] border border-[#a8dab5] p-2 rounded-lg text-[11px] text-[#0d652d]">
                  <p class="font-bold">Proposed Fix: ${escapeHtml(matchingRec.title)}</p>
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

      const isInfra = rec.category === 'infrastructure_planning'
      const label = isInfra ? `I#${idx + 1}` : `S#${idx + 1}`
      const pinBg = isInfra ? '#c2410c' : '#006a6a'
      const haloColor = isInfra ? 'rgba(194, 65, 12, 0.3)' : 'rgba(0, 106, 106, 0.3)'
      const categoryBadge = isInfra
        ? '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-[#ffedd5] text-[#9a3412]">Infrastructure</span>'
        : '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-[#ccfbf1] text-[#115e59]">Traffic Opt</span>'

      // Check if there is a bottleneck at the exact same location
      const hasCoLocatedProblem = bottlenecks.some(
        (b) => Math.abs(b.lat - rec.lat!) < 0.0001 && Math.abs(b.lng - rec.lng!) < 0.0001
      )
      // If co-located, slightly offset solution pin to the northeast so both B# (Problem) and S# (Solution) pins are visible
      const pinLat = hasCoLocatedProblem ? rec.lat + 0.00018 : rec.lat
      const pinLng = hasCoLocatedProblem ? rec.lng + 0.00022 : rec.lng

      const icon = L.divIcon({
        className: 'custom-solution-pin',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -16],
        html: `
          <div class="relative w-8 h-8 flex items-center justify-center cursor-pointer group">
            <span class="absolute w-7 h-7 rounded-full" style="background-color: ${haloColor};"></span>
            <div class="relative w-7 h-7 rounded-full flex items-center justify-center shadow-lg border-2 border-white font-mono text-[10px] font-bold text-white transition-transform transform group-hover:scale-110" style="background-color: ${pinBg};">
              ${escapeHtml(label)}
            </div>
          </div>
        `,
      })

      const marker = L.marker([pinLat, pinLng], { icon })

      const locationLabel = rec.affected_location || 'Corridor Intervention'

      const priorityBadgeClass =
        rec.priority === 'high'
          ? 'bg-[#fee2e2] text-[#991b1b]'
          : rec.priority === 'medium'
          ? 'bg-[#fef3c7] text-[#92400e]'
          : 'bg-[#f1f5f9] text-[#475569]'

      const popupHtml = `
        <div class="font-sans p-1 text-xs max-w-[290px]">
          <div class="flex items-center justify-between gap-2 border-b border-[#e2e8f0] pb-1.5 mb-2">
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 rounded-full" style="background-color: ${pinBg};"></span>
              <span class="font-bold text-xs uppercase tracking-tight" style="color: ${pinBg};">${escapeHtml(label)}</span>
              ${categoryBadge}
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${priorityBadgeClass}">${escapeHtml(rec.priority)} Priority</span>
          </div>

          <p class="font-bold text-[#0b1c30] text-sm leading-snug mb-1">${escapeHtml(rec.title)}</p>
          <p class="text-[11px] text-[#554336] mb-2 font-medium">📍 ${escapeHtml(locationLabel)}</p>

          <div class="bg-[#f0fdf4] p-2 rounded-lg border border-[#bbf7d0] mb-2">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10px] font-bold uppercase text-[#166534]">Impact Rating</span>
              <span class="font-mono font-bold text-xs text-[#166534]">${rec.impact_score.toFixed(1)} / 10</span>
            </div>
            <p class="text-[11px] text-[#1e293b] leading-relaxed">${escapeHtml(rec.description)}</p>
          </div>

          <div class="flex items-center justify-between text-[10px] text-[#64748b] bg-[#f8fafc] p-1.5 rounded">
            <span>Intervention: <strong>${escapeHtml(rec.intervention_type.replace(/_/g, ' '))}</strong></span>
            <span>Confidence: <strong>${escapeHtml(rec.confidence)}</strong></span>
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
  }, [recommendations, bottlenecks, showRecommendations, onSelectRecommendation])

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

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (selectedSegmentId) {
      const seg = segments.find((s) => s.segment_id === selectedSegmentId)
      if (seg?.geometry?.coordinates?.length) {
        const latLngs: L.LatLngExpression[] = seg.geometry.coordinates.map((c) => [c[1], c[0]])
        const bounds = L.latLngBounds(latLngs)
        if (bounds.isValid()) {
          map.fitBounds(bounds, { maxZoom: 17, padding: [40, 40] })
          const polyline = segmentLayersMapRef.current.get(selectedSegmentId)
          if (polyline) {
            polyline.openTooltip()
            polyline.bringToFront()
          }
        }
      }
    }
  }, [selectedSegmentId, segments])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (selectedIncidentId) {
      const inc = incidents.find((i) => i.incident_id === selectedIncidentId)
      if (inc && inc.lat != null && inc.lng != null) {
        map.flyTo([inc.lat, inc.lng], 16, { duration: 0.8 })
        const marker = incidentMarkersMapRef.current.get(`marker_${inc.incident_id}`) as L.Marker | undefined
        if (marker && typeof marker.openPopup === 'function') {
          marker.openPopup()
        }
      }
    }
  }, [selectedIncidentId, incidents])

  // Reset view to polygon
  const handleResetView = useCallback(() => {
    const map = mapRef.current
    const polyLayer = polygonLayerRef.current
    if (map && polyLayer) {
      map.invalidateSize({ animate: false })
      const bounds = polyLayer.getBounds()
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [35, 35] })
      }
    }
  }, [])

  const hasClosures = segments.some(
    (s) => s.traffic?.congestion_level === 'closed' || s.traffic?.road_closure === true
  )

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
              {mode === 'flow' ? 'speed' : 'traffic'}
            </span>
            <span>
              {baseMapStatus.isFallback
                ? `${baseMapStatus.displayName} (TomTom Fallback)`
                : baseMapStatus.displayName}{' '}
              · {mode === 'flow' ? 'Traffic Flow' : 'Traffic Analysis'}
            </span>
          </div>
          <span className="text-[var(--color-surface-container-high)]">|</span>
          {mode === 'flow' ? (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] text-[#138808] font-semibold">
                <span className="w-2.5 h-1.5 rounded-sm bg-[#138808]"></span> Free Flow
              </span>
              <span className="flex items-center gap-1 text-[11px] text-[#ff9933] font-semibold">
                <span className="w-2.5 h-1.5 rounded-sm bg-[#ff9933]"></span> Moderate
              </span>
              <span className="flex items-center gap-1 text-[11px] text-[#ba1a1a] font-semibold">
                <span className="w-2.5 h-1.5 rounded-sm bg-[#ba1a1a]"></span> Severe
              </span>
              <span className="flex items-center gap-1 text-[11px] text-zinc-900 font-bold">
                <span className="w-2.5 h-1.5 rounded-sm bg-[#1e1b18] border border-dashed border-red-500"></span> Closed
              </span>
              <span className="flex items-center gap-1 text-[11px] text-slate-500">
                <span className="w-2.5 h-1.5 rounded-sm bg-[#94a3b8]"></span> Unobserved
              </span>
              {incidents.length > 0 && (
                <span className="flex items-center gap-1 text-[11px] text-[var(--color-error)] font-bold">
                  <span className="w-2 h-2 rounded-full bg-[#ba1a1a]"></span> Incidents ({incidents.length})
                </span>
              )}
            </div>
          ) : (
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
                <>
                  <span className="flex items-center gap-1 text-[11px] text-[#006a6a] font-semibold">
                    <span className="w-2 h-2 rounded-full bg-[#006a6a]"></span> Operations (
                    {
                      recommendations.filter(
                        (r) => (r.category ?? 'traffic_optimization') === 'traffic_optimization'
                      ).length
                    }
                    )
                  </span>
                  {recommendations.some((r) => r.category === 'infrastructure_planning') && (
                    <span className="flex items-center gap-1 text-[11px] text-[#c2410c] font-semibold">
                      <span className="w-2 h-2 rounded-full bg-[#c2410c]"></span> Infrastructure (
                      {recommendations.filter((r) => r.category === 'infrastructure_planning').length})
                    </span>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Right: Active Toggles & Style Switcher */}
        <div className="pointer-events-auto bg-[var(--color-surface-container-lowest)]/95 backdrop-blur-md p-1 rounded-lg shadow-md border border-[var(--color-surface-container-high)] flex items-center gap-1 text-xs">
          {/* TomTom Live Traffic toggle */}
          {hasTomTomKey ? (
            <button
              onClick={handleToggleTomTomTraffic}
              title={
                trafficStatus.errorMessage
                  ? `TomTom Traffic: ${trafficStatus.errorMessage}`
                  : 'Toggle Live TomTom Real-Time Traffic Flow Overlay'
              }
              className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                showTomTomTraffic
                  ? trafficStatus.status === 'active'
                    ? 'bg-[#138808]/20 text-[#138808] border border-[#138808]/40'
                    : trafficStatus.status === 'error'
                      ? 'bg-[#ba1a1a]/20 text-[#ba1a1a] border border-[#ba1a1a]/40'
                      : 'bg-[#b45309]/20 text-[#b45309] border border-[#b45309]/40'
                  : 'text-[var(--color-on-surface-variant)] opacity-50'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  !showTomTomTraffic
                    ? 'bg-[#94a3b8]'
                    : trafficStatus.status === 'active'
                      ? 'bg-[#138808] animate-pulse'
                      : trafficStatus.status === 'loading'
                        ? 'bg-amber-400 animate-pulse'
                        : 'bg-[#ba1a1a]'
                }`}
              />
              <span>
                {!showTomTomTraffic
                  ? 'TomTom Traffic'
                  : trafficStatus.status === 'active'
                    ? 'TomTom Live'
                    : trafficStatus.status === 'loading'
                      ? 'Connecting...'
                      : 'Traffic Error'}
              </span>
            </button>
          ) : (
            <div
              title="TomTom API key not configured (VITE_TOMTOM_API_KEY)"
              className="px-2 py-1 rounded text-xs text-[var(--color-on-surface-variant)] opacity-50 flex items-center gap-1 cursor-not-allowed"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#cbd5e1]" />
              <span>Traffic N/A</span>
            </div>
          )}

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

          {mode === 'flow' && hasClosures && (
            <button
              onClick={() => setShowClosuresOnly(!showClosuresOnly)}
              title="Filter to Closed Roads Only"
              className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                showClosuresOnly
                  ? 'bg-zinc-900 text-red-400 border border-red-500'
                  : 'text-[var(--color-on-surface-variant)] opacity-70'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">block</span>
              Closures Only
            </button>
          )}

          {mode === 'flow' && incidents.length > 0 && (
            <button
              onClick={() => setShowIncidents(!showIncidents)}
              title="Toggle Traffic Incidents"
              className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                showIncidents
                  ? 'bg-[#ffdad6] text-[#ba1a1a]'
                  : 'text-[var(--color-on-surface-variant)] opacity-50'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">report_problem</span>
              Incidents ({incidents.length})
            </button>
          )}

          {mode !== 'flow' && (
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
          )}

          {mode !== 'flow' && recommendations.length > 0 && (
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

          {/* Streets vs Satellite / Provider Switcher */}
          {hasTomTomKey ? (
            <>
              <button
                onClick={() => setBaseLayerType('tomtom')}
                title="TomTom Street Basemap"
                className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                  baseLayerType === 'tomtom' || (baseLayerType === 'streets' && baseMapStatus.provider === 'tomtom')
                    ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] shadow-xs'
                    : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span className="material-symbols-outlined text-[14px]">map</span>
                TomTom
              </button>
              <button
                onClick={() => setBaseLayerType('osm')}
                title="OpenStreetMap Basemap"
                className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                  baseLayerType === 'osm' || (baseLayerType === 'streets' && baseMapStatus.provider === 'osm')
                    ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] shadow-xs'
                    : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span className="material-symbols-outlined text-[14px]">public</span>
                OSM
              </button>
            </>
          ) : (
            <button
              onClick={() => setBaseLayerType('osm')}
              title="OpenStreetMap Basemap"
              className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-colors ${
                baseLayerType === 'osm' || baseLayerType === 'streets'
                  ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] shadow-xs'
                  : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              <span className="material-symbols-outlined text-[14px]">map</span>
              Streets
            </button>
          )}

          <button
            onClick={() => setBaseLayerType('satellite')}
            title="Esri World Imagery Satellite Basemap"
            className={`px-2 py-1 rounded text-xs font-bold transition-all flex items-center gap-1 ${
              baseLayerType === 'satellite'
                ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] shadow-xs'
                : 'text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">satellite_alt</span>
            Satellite
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
          {mode === 'flow' ? (
            <span>
              💡 Click any <span className="font-bold text-[#ba1a1a]">road corridor</span> or{' '}
              <span className="font-bold text-[#ba1a1a]">incident pin</span> to inspect live telemetry
            </span>
          ) : (
            <span>
              💡 Click any <span className="font-bold text-[#ba1a1a]">B#</span> or{' '}
              <span className="font-bold text-[#006a6a]">S#</span> pin to inspect problems & civil solutions
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
