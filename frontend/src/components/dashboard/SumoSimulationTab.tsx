import { useEffect, useRef, useState, useCallback } from 'react'

import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, GativaApiError } from '../../api/client'
import type {
  AnalysisResult,
  SimulationStatusResponse,
  ScenarioComparisonResult,
  VehiclePosition,
  CongestionSummary,
  CongestionRoadResult,
  CongestionSeverity,
  DemandLevel,
  DemandProfile,
  SignalListResponse,
  SignalDetailInfo,
  SignalEditRequest,
  TrafficLightState,
} from '../../types/api'

interface SumoSimulationTabProps {
  analysis: AnalysisResult
}

export default function SumoSimulationTab({ analysis }: SumoSimulationTabProps) {
  // Navigation / View Modes: Mode A ('single'), Mode B ('compare'), Mode C ('results')
  const [viewMode, setViewMode] = useState<'single' | 'compare' | 'results'>('single')

  // Simulation ID & Dual States
  const [simId, setSimId] = useState<string | null>(null)
  const [simStatus, setSimStatus] = useState<SimulationStatusResponse | null>(null)
  const [baselineStatus, setBaselineStatus] = useState<SimulationStatusResponse | null>(null)
  const [comparison, setComparison] = useState<ScenarioComparisonResult | null>(null)
  const [congestion, setCongestion] = useState<CongestionSummary | null>(null)
  const [signalsList, setSignalsList] = useState<SignalListResponse | null>(null)

  // Demand Configuration Controls
  const [demandLevel, setDemandLevel] = useState<DemandLevel>('normal')
  const [demandProfile, setDemandProfile] = useState<DemandProfile>('peak')
  const [durationSeconds, setDurationSeconds] = useState<number>(600)
  const [seed, setSeed] = useState<number>(42)
  const [manualVehicles, setManualVehicles] = useState<number>(85)
  const [showDemandConfig, setShowDemandConfig] = useState<boolean>(false)

  // Fullscreen support in Compare Scenarios mode
  const [fullscreenMap, setFullscreenMap] = useState<'baseline' | 'optimized' | null>(null)

  // Traffic Signal Inspection & Editing Modal State
  const [selectedSignal, setSelectedSignal] = useState<SignalDetailInfo | null>(null)
  const [isEditingSignal, setIsEditingSignal] = useState<boolean>(false)
  const [signalEditCycle, setSignalEditCycle] = useState<number>(90)
  const [signalEditAction, setSignalEditAction] = useState<SignalEditRequest['action']>('set_adaptive')
  const [signalSuccessMsg, setSignalSuccessMsg] = useState<string | null>(null)

  // Congestion segment focus
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)

  // Playback state
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(2)
  const [isPlaying, setIsPlaying] = useState<boolean>(false)
  const [isPreparing, setIsPreparing] = useState<boolean>(true)
  const [isLoadingCongestion, setIsLoadingCongestion] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Playback timer ref
  const timerRef = useRef<number | null>(null)

  // DOM Container Refs
  const singleMapContainerRef = useRef<HTMLDivElement>(null)
  const baselineMapContainerRef = useRef<HTMLDivElement>(null)
  const optimizedMapContainerRef = useRef<HTMLDivElement>(null)
  const resultsMapContainerRef = useRef<HTMLDivElement>(null)

  // Leaflet Map Instance Refs
  const singleMapRef = useRef<L.Map | null>(null)
  const baselineMapRef = useRef<L.Map | null>(null)
  const optimizedMapRef = useRef<L.Map | null>(null)
  const resultsMapRef = useRef<L.Map | null>(null)

  // Marker & Layer Group Refs for Single Map
  const singleVehiclesGroupRef = useRef<L.LayerGroup | null>(null)
  const singleSignalsGroupRef = useRef<L.LayerGroup | null>(null)
  const singleSegmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const singleMarkersMapRef = useRef<Map<string, L.Marker>>(new Map())

  // Marker & Layer Group Refs for Baseline Map
  const baselineVehiclesGroupRef = useRef<L.LayerGroup | null>(null)
  const baselineSignalsGroupRef = useRef<L.LayerGroup | null>(null)
  const baselineSegmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const baselineMarkersMapRef = useRef<Map<string, L.Marker>>(new Map())

  // Marker & Layer Group Refs for Optimized Map
  const optimizedVehiclesGroupRef = useRef<L.LayerGroup | null>(null)
  const optimizedSignalsGroupRef = useRef<L.LayerGroup | null>(null)
  const optimizedSegmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const optimizedMarkersMapRef = useRef<Map<string, L.Marker>>(new Map())

  // Polyline Refs for Results Congestion Map
  const resultsSegmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const resultsPolylineMapRef = useRef<Map<string, L.Polyline>>(new Map())

  const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY

  const getErrorMessage = (err: unknown): string => {
    if (err instanceof GativaApiError) return err.message
    if (err instanceof Error) return err.message
    return String(err)
  }

  // ─── Initialize or Prepare Simulation ───────────────────────────────────────
  const initSimulation = useCallback(
    (customConfig?: {
      level?: DemandLevel
      profile?: DemandProfile
      duration?: number
      manualCount?: number
      simSeed?: number
    }) => {
      setIsPreparing(true)
      setError(null)
      setIsPlaying(false)
      if (timerRef.current) clearInterval(timerRef.current)

      const lvl = customConfig?.level ?? demandLevel
      const prof = customConfig?.profile ?? demandProfile
      const dur = customConfig?.duration ?? durationSeconds
      const s = customConfig?.simSeed ?? seed
      const manual = lvl === 'custom' ? (customConfig?.manualCount ?? manualVehicles) : undefined

      api
        .prepareSimulation({
          analysis_id: analysis.analysis_id,
          duration_seconds: dur,
          strategy: 'actuated_adaptive',
          demand_level: lvl,
          demand_profile: prof,
          manual_vehicle_count: manual,
          seed: s,
        })
        .then(async (res) => {
          setSimId(res.sim_id)
          setSimStatus(res)
          setIsPreparing(false)

          // Fetch baseline state, comparison, and signals in parallel
          try {
            const [baseRes, compRes, sigRes, congRes] = await Promise.allSettled([
              api.getBaselineStatus(res.sim_id),
              api.getScenarioComparison(res.sim_id),
              api.getSimulationSignals(res.sim_id),
              api.getCongestionResults(res.sim_id),
            ])
            if (baseRes.status === 'fulfilled') setBaselineStatus(baseRes.value)
            if (compRes.status === 'fulfilled') setComparison(compRes.value)
            if (sigRes.status === 'fulfilled') setSignalsList(sigRes.value)
            if (congRes.status === 'fulfilled') setCongestion(congRes.value)
          } catch (e) {
            console.warn('Initial telemetry prefetch warning:', e)
          }
        })
        .catch((err) => {
          setError(getErrorMessage(err))
          setIsPreparing(false)
        })
    },
    [analysis.analysis_id, demandLevel, demandProfile, durationSeconds, manualVehicles, seed],
  )

  useEffect(() => {
    initSimulation()
  }, [analysis.analysis_id])

  // ─── Fetch Congestion Telemetry ─────────────────────────────────────────────
  const fetchCongestion = useCallback((id: string) => {
    setIsLoadingCongestion(true)
    api
      .getCongestionResults(id)
      .then((data) => setCongestion(data))
      .catch((err) => console.warn('Failed to fetch congestion summary:', err))
      .finally(() => setIsLoadingCongestion(false))
  }, [])

  // ─── Fullscreen Escape Listener ─────────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreenMap) {
        setFullscreenMap(null)
        setTimeout(() => {
          baselineMapRef.current?.invalidateSize()
          optimizedMapRef.current?.invalidateSize()
        }, 150)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreenMap])

  // ─── Trigger Leaflet InvalidateSize on ViewMode Switch ──────────────────────
  useEffect(() => {
    const timer = setTimeout(() => {
      if (viewMode === 'single') singleMapRef.current?.invalidateSize()
      if (viewMode === 'compare') {
        baselineMapRef.current?.invalidateSize()
        optimizedMapRef.current?.invalidateSize()
      }
      if (viewMode === 'results') resultsMapRef.current?.invalidateSize()
    }, 150)
    return () => clearTimeout(timer)
  }, [viewMode])

  // ─── Shared Tile Layer & Network Initialization Helper ─────────────────────
  const setupBaseNetwork = useCallback(
    (map: L.Map, segGroup: L.LayerGroup, isInteractiveForCongestion = false) => {
      // Tile Layer
      const baseTile = TOMTOM_KEY
        ? L.tileLayer(
            `https://{s}.api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=${TOMTOM_KEY}`,
            {
              maxZoom: 19,
              subdomains: ['a', 'b', 'c', 'd'],
              attribution: '&copy; TomTom, &copy; OpenStreetMap',
            },
          )
        : L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors',
          })
      baseTile.addTo(map)

      // Boundary Polygon
      if (analysis.polygon?.coordinates?.[0]?.length) {
        const ring = analysis.polygon.coordinates[0]
        const latLngs: L.LatLngExpression[] = ring.map((c) => [c[1], c[0]])
        L.polygon(latLngs, {
          color: '#2d3b8f',
          weight: 1.5,
          fillColor: '#eff4ff',
          fillOpacity: 0.12,
          dashArray: '4 4',
        }).addTo(segGroup)

        const bounds = L.latLngBounds(latLngs)
        map.fitBounds(bounds, { padding: [25, 25] })
      }

      // Road Network Segments
      if (analysis.segments?.length) {
        analysis.segments.forEach((seg) => {
          if (!seg.geometry?.coordinates || seg.geometry.coordinates.length < 2) return
          const pts: L.LatLngExpression[] = seg.geometry.coordinates.map((c) => [c[1], c[0]])
          const color =
            seg.road_type === 'highway'
              ? '#ff9933'
              : seg.road_type === 'arterial'
                ? '#2d3b8f'
                : '#64748b'
          const weight = seg.road_type === 'highway' ? 4 : seg.road_type === 'arterial' ? 3 : 2

          const line = L.polyline(pts, {
            color,
            weight,
            opacity: 0.8,
            lineCap: 'round',
            lineJoin: 'round',
          })

          line.bindTooltip(
            `<div class="text-xs font-sans"><b>${seg.name || 'Road Segment'}</b><br/>${seg.road_type} • ${seg.length_m.toFixed(0)}m</div>`,
            { sticky: true },
          )

          if (isInteractiveForCongestion) {
            line.on('click', () => setSelectedSegmentId(seg.segment_id))
            resultsPolylineMapRef.current.set(seg.segment_id, line)
          }

          segGroup.addLayer(line)
        })
      }
    },
    [analysis.polygon, analysis.segments, TOMTOM_KEY],
  )

  // ─── Initialize Single Map (Mode A) ─────────────────────────────────────────
  useEffect(() => {
    if (!singleMapContainerRef.current || singleMapRef.current) return

    const map = L.map(singleMapContainerRef.current, { zoomControl: false })
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    const segGroup = L.layerGroup().addTo(map)
    const vehGroup = L.layerGroup().addTo(map)
    const sigGroup = L.layerGroup().addTo(map)

    singleSegmentsGroupRef.current = segGroup
    singleVehiclesGroupRef.current = vehGroup
    singleSignalsGroupRef.current = sigGroup
    singleMapRef.current = map

    setupBaseNetwork(map, segGroup)

    return () => {
      map.remove()
      singleMapRef.current = null
    }
  }, [setupBaseNetwork])

  // ─── Initialize Baseline Map (Mode B - Left) ────────────────────────────────
  useEffect(() => {
    if (!baselineMapContainerRef.current || baselineMapRef.current) return

    const map = L.map(baselineMapContainerRef.current, { zoomControl: false })
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    const segGroup = L.layerGroup().addTo(map)
    const vehGroup = L.layerGroup().addTo(map)
    const sigGroup = L.layerGroup().addTo(map)

    baselineSegmentsGroupRef.current = segGroup
    baselineVehiclesGroupRef.current = vehGroup
    baselineSignalsGroupRef.current = sigGroup
    baselineMapRef.current = map

    setupBaseNetwork(map, segGroup)

    return () => {
      map.remove()
      baselineMapRef.current = null
    }
  }, [setupBaseNetwork])

  // ─── Initialize Optimized Map (Mode B - Right) ──────────────────────────────
  useEffect(() => {
    if (!optimizedMapContainerRef.current || optimizedMapRef.current) return

    const map = L.map(optimizedMapContainerRef.current, { zoomControl: false })
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    const segGroup = L.layerGroup().addTo(map)
    const vehGroup = L.layerGroup().addTo(map)
    const sigGroup = L.layerGroup().addTo(map)

    optimizedSegmentsGroupRef.current = segGroup
    optimizedVehiclesGroupRef.current = vehGroup
    optimizedSignalsGroupRef.current = sigGroup
    optimizedMapRef.current = map

    setupBaseNetwork(map, segGroup)

    return () => {
      map.remove()
      optimizedMapRef.current = null
    }
  }, [setupBaseNetwork])

  // ─── Initialize Results Congestion Map (Mode C) ─────────────────────────────
  useEffect(() => {
    if (!resultsMapContainerRef.current || resultsMapRef.current) return

    const map = L.map(resultsMapContainerRef.current, { zoomControl: false })
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    const segGroup = L.layerGroup().addTo(map)
    resultsSegmentsGroupRef.current = segGroup
    resultsMapRef.current = map

    setupBaseNetwork(map, segGroup, true)

    return () => {
      map.remove()
      resultsMapRef.current = null
      resultsPolylineMapRef.current.clear()
    }
  }, [setupBaseNetwork])

  // ─── Vehicle Rendering Helper ───────────────────────────────────────────────
  const updateVehicleLayer = useCallback(
    (
      vehicles: VehiclePosition[],
      vehGroup: L.LayerGroup | null,
      markersMap: Map<string, L.Marker>,
    ) => {
      if (!vehGroup) return
      const currentIds = new Set<string>()

      vehicles.forEach((veh) => {
        if (
          veh.lat != null &&
          veh.lng != null &&
          !isNaN(veh.lat) &&
          !isNaN(veh.lng) &&
          veh.lat >= -90 &&
          veh.lat <= 90 &&
          veh.lng >= -180 &&
          veh.lng <= 180
        ) {
          currentIds.add(veh.id)
          const isBus = veh.type === 'bus'
          const speedColor =
            veh.speed_kmh < 18
              ? '#DC2626'
              : veh.speed_kmh <= 35
                ? '#F59E0B'
                : isBus
                  ? '#0A1145'
                  : '#138808'

          const iconHtml = `<div style="transform: rotate(${veh.angle}deg); width: ${isBus ? '22px' : '16px'}; height: ${isBus ? '10px' : '8px'}; background-color: ${speedColor}; border: 1.5px solid #ffffff; border-radius: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;">
            ${isBus ? '<span style="font-size: 5px; color: #ffffff; font-weight: bold; font-family: monospace;">B</span>' : ''}
          </div>`

          const icon = L.divIcon({
            className: 'sumo-vehicle-icon',
            iconSize: [22, 12],
            iconAnchor: [11, 6],
            html: iconHtml,
          })

          const tooltipHtml = `<div class="text-[11px] font-mono"><b>${veh.id}</b> (${veh.type})<br/>Speed: ${veh.speed_kmh.toFixed(1)} km/h<br/>Wait: ${veh.waiting_time_s.toFixed(1)}s</div>`

          const existingMarker = markersMap.get(veh.id)
          if (existingMarker) {
            existingMarker.setLatLng([veh.lat, veh.lng])
            existingMarker.setIcon(icon)
            existingMarker.setTooltipContent(tooltipHtml)
          } else {
            const newMarker = L.marker([veh.lat, veh.lng], { icon })
            newMarker.bindTooltip(tooltipHtml, { direction: 'top', offset: [0, -6] })
            vehGroup.addLayer(newMarker)
            markersMap.set(veh.id, newMarker)
          }
        }
      })

      // Clean up departed/arrived vehicles
      markersMap.forEach((marker, id) => {
        if (!currentIds.has(id)) {
          vehGroup.removeLayer(marker)
          markersMap.delete(id)
        }
      })
    },
    [],
  )

  // ─── Signal Rendering Helper ────────────────────────────────────────────────
  const updateSignalLayer = useCallback(
    (
      trafficLights: TrafficLightState[] | undefined,
      sigGroup: L.LayerGroup | null,
      onSignalClick?: (tl: TrafficLightState) => void,
    ) => {
      if (!sigGroup) return
      sigGroup.clearLayers()

      ;(trafficLights || []).forEach((tl, idx) => {
        if (
          tl.lat != null &&
          tl.lng != null &&
          !isNaN(tl.lat) &&
          !isNaN(tl.lng) &&
          tl.lat >= -90 &&
          tl.lat <= 90 &&
          tl.lng >= -180 &&
          tl.lng <= 180
        ) {
          const stateColor =
            tl.state === 'green' ? '#138808' : tl.state === 'yellow' ? '#F59E0B' : '#DC2626'

          const isRemoved = tl.control_type === 'priority' || tl.control_type === 'uncontrolled'
          const sigIcon = L.divIcon({
            className: 'sumo-signal-icon',
            iconSize: [26, 26],
            iconAnchor: [13, 13],
            html: `<div style="width: 26px; height: 26px; border-radius: 50%; background: ${isRemoved ? '#64748B' : '#0A1145'}; border: 2px solid #ffffff; box-shadow: 0 2px 5px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; position: relative; cursor: pointer;">
              <span style="font-size: 8px; color: ${isRemoved ? '#CBD5E1' : '#FF9933'}; font-weight: bold; font-family: monospace;">TL${idx + 1}</span>
              ${!isRemoved ? `<span style="position: absolute; top: -2px; right: -2px; width: 9px; height: 9px; border-radius: 50%; background: ${stateColor}; border: 1.5px solid #ffffff; box-shadow: 0 0 6px ${stateColor};"></span>` : ''}
            </div>`,
          })

          const sigMarker = L.marker([tl.lat, tl.lng], { icon: sigIcon })
          const ctrlLabel = isRemoved ? 'Unsignalized Priority' : 'Traffic Signal'

          sigMarker.bindTooltip(
            `<div class="text-[11px] font-sans"><b>Signal ${tl.id}</b> (${ctrlLabel})<br/>Current Phase: <span style="font-weight:bold;color:${stateColor}">${tl.state.toUpperCase()}</span><br/><span class="text-indigo-600 font-semibold underline">Click to inspect / edit</span></div>`,
          )


          if (onSignalClick) {
            sigMarker.on('click', () => onSignalClick(tl))
          }

          sigGroup.addLayer(sigMarker)
        }
      })
    },
    [],
  )

  // ─── Click Handler to Inspect Signal in Modal ──────────────────────────────
  const handleInspectSignal = useCallback(
    (tl: TrafficLightState) => {
      // Find full detail in signalsList or build fallback
      const found = signalsList?.signals.find((s) => s.id === tl.id)
      if (found) {
        setSelectedSignal(found)
        setSignalEditCycle(found.cycle_length_s || 90)
      } else {
        setSelectedSignal({
          id: tl.id,
          lat: tl.lat,
          lng: tl.lng,
          junction_id: tl.id,
          control_type: tl.control_type || 'actuated_adaptive',
          original_type: 'actuated_adaptive',
          is_editable: true,
          can_remove: true,
          safety_assessment: 'Standard junction signal inspection',
          movements: [],
          controlled_lanes: tl.controlled_lanes || [],
          connected_roads: [],
          provenance: tl.provenance || 'source_verified',
        } as unknown as SignalDetailInfo)
        setSignalEditCycle(90)
      }
      setIsEditingSignal(true)
      setSignalSuccessMsg(null)
    },
    [signalsList],
  )

  // ─── Live Telemetry Updates across Map Viewports ────────────────────────────
  // Single Map (Mode A)
  useEffect(() => {
    if (viewMode === 'single') {
      updateVehicleLayer(
        simStatus?.vehicles || [],
        singleVehiclesGroupRef.current,
        singleMarkersMapRef.current,
      )
      updateSignalLayer(
        simStatus?.traffic_lights,
        singleSignalsGroupRef.current,
        handleInspectSignal,
      )
    }
  }, [viewMode, simStatus?.vehicles, simStatus?.traffic_lights, updateVehicleLayer, updateSignalLayer, handleInspectSignal])

  // Dual Maps (Mode B)
  useEffect(() => {
    if (viewMode === 'compare') {
      // Baseline Map (Left) - Fixed-Time
      updateVehicleLayer(
        baselineStatus?.vehicles || [],
        baselineVehiclesGroupRef.current,
        baselineMarkersMapRef.current,
      )
      updateSignalLayer(baselineStatus?.traffic_lights, baselineSignalsGroupRef.current)

      // Optimized Map (Right) - Actuated Adaptive (Editable)
      updateVehicleLayer(
        simStatus?.vehicles || [],
        optimizedVehiclesGroupRef.current,
        optimizedMarkersMapRef.current,
      )
      updateSignalLayer(
        simStatus?.traffic_lights,
        optimizedSignalsGroupRef.current,
        handleInspectSignal,
      )
    }
  }, [
    viewMode,
    baselineStatus?.vehicles,
    baselineStatus?.traffic_lights,
    simStatus?.vehicles,
    simStatus?.traffic_lights,
    updateVehicleLayer,
    updateSignalLayer,
    handleInspectSignal,
  ])

  // Results Map (Mode C) - Post-Simulation Congestion Colors
  useEffect(() => {
    if (!analysis.segments?.length || viewMode !== 'results') return

    const severityStyles: Record<
      CongestionSeverity,
      { color: string; weight: number; label: string }
    > = {
      free_flow: { color: '#10B981', weight: 4.5, label: 'Free Flow' },
      low: { color: '#84CC16', weight: 4.5, label: 'Low Congestion' },
      moderate: { color: '#F59E0B', weight: 5, label: 'Moderate Congestion' },
      high: { color: '#EF4444', weight: 5.5, label: 'High Congestion' },
      severe: { color: '#7F1D1D', weight: 6.5, label: 'Severe Congestion' },
      insufficient_data: { color: '#94A3B8', weight: 3, label: 'Insufficient Data' },
    }

    const resultsMap = new Map<string, CongestionRoadResult>()
    if (congestion?.all_results) {
      congestion.all_results.forEach((r) => resultsMap.set(r.segment_id, r))
    }

    analysis.segments.forEach((seg) => {
      const line = resultsPolylineMapRef.current.get(seg.segment_id)
      if (!line) return

      const isSelected = selectedSegmentId === seg.segment_id
      const res = resultsMap.get(seg.segment_id)
      const sev: CongestionSeverity = res?.severity ?? 'insufficient_data'
      const style = severityStyles[sev]

      line.setStyle({
        color: isSelected ? '#4338CA' : style.color,
        weight: isSelected ? style.weight + 3 : style.weight,
        opacity: isSelected ? 1.0 : 0.85,
      })

      const scorePct = res ? (res.congestion_score * 100).toFixed(0) : '—'
      const speedText = res && res.avg_speed_kmh > 0 ? `${res.avg_speed_kmh.toFixed(1)} km/h` : '—'
      const limitText = res ? `${res.ref_speed_kmh} km/h` : '—'
      const occText = res && res.avg_occupancy_pct > 0 ? `${res.avg_occupancy_pct.toFixed(1)}%` : '—'
      const haltText = res ? `${res.avg_halting.toFixed(1)} veh` : '—'

      line.setTooltipContent(
        `<div class="text-xs font-sans min-w-[170px] p-1">
          <div class="font-bold text-[#0A1145] text-sm">${seg.name || 'Road Segment'}</div>
          <div class="text-[10px] text-slate-500 uppercase font-semibold mb-1">${seg.road_type} • ID: ${seg.segment_id}</div>
          <div class="flex items-center justify-between py-0.5 border-t border-slate-100 mt-1">
            <span class="text-slate-600">Severity:</span>
            <span style="font-weight:bold;color:${style.color}">${style.label}</span>
          </div>
          <div class="flex items-center justify-between py-0.5">
            <span class="text-slate-600">Congestion Score:</span>
            <span class="font-mono font-bold text-[#0A1145]">${scorePct}%</span>
          </div>
          <div class="flex items-center justify-between py-0.5">
            <span class="text-slate-600">Mean Speed:</span>
            <span class="font-mono font-semibold">${speedText} <span class="text-slate-400 font-normal">/ ${limitText}</span></span>
          </div>
          <div class="flex items-center justify-between py-0.5">
            <span class="text-slate-600">Occupancy:</span>
            <span class="font-mono font-semibold">${occText}</span>
          </div>
          <div class="flex items-center justify-between py-0.5">
            <span class="text-slate-600">Halting (Queuing):</span>
            <span class="font-mono font-semibold">${haltText}</span>
          </div>
          <div class="flex items-center justify-between py-0.5 text-[10px] text-slate-400 border-t border-slate-100 mt-1">
            <span>Data Quality:</span>
            <span class="capitalize font-semibold text-slate-600">${res?.data_quality ?? 'insufficient'}</span>
          </div>
        </div>`,
      )
    })
  }, [viewMode, congestion, selectedSegmentId, analysis.segments])

  // ─── Playback Loop (Synchronized Both Scenarios) ────────────────────────────
  useEffect(() => {
    if (!isPlaying || !simId) {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      return
    }

    let active = true

    const runStep = () => {
      if (!active) return
      const t0 = performance.now()

      api
        .stepSimulation(simId, speedMultiplier)
        .then(async (res) => {
          if (!active) return
          setSimStatus(res)

          // In compare mode, fetch baseline and comparison simultaneously
          if (viewMode === 'compare' || viewMode === 'results') {
            try {
              const [baseRes, compRes] = await Promise.allSettled([
                api.getBaselineStatus(simId),
                api.getScenarioComparison(simId),
              ])
              if (baseRes.status === 'fulfilled') setBaselineStatus(baseRes.value)
              if (compRes.status === 'fulfilled') setComparison(compRes.value)
            } catch (e) {
              console.warn('Baseline step sync error:', e)
            }
          }

          if (res.state === 'completed') {
            setIsPlaying(false)
            api.getScenarioComparison(simId).then(setComparison).catch(() => {})
            fetchCongestion(simId)
            setViewMode('results')
            return
          }

          const elapsedWall = performance.now() - t0
          const delay = Math.max(20, 200 - elapsedWall)
          timerRef.current = window.setTimeout(runStep, delay)
        })
        .catch((err) => {
          if (!active) return
          setError(getErrorMessage(err))
          setIsPlaying(false)
        })
    }

    runStep()

    return () => {
      active = false
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [isPlaying, simId, speedMultiplier, viewMode, fetchCongestion])

  // ─── Playback Control Handlers ──────────────────────────────────────────────
  const handleTogglePlay = useCallback(() => {
    if (!simId) return
    if (isPlaying) {
      api
        .pauseSimulation(simId)
        .then((res) => setSimStatus(res))
        .catch((err) => setError(getErrorMessage(err)))
      setIsPlaying(false)
      api.getScenarioComparison(simId).then(setComparison).catch(() => {})
      fetchCongestion(simId)
    } else {
      setError(null)
      api
        .startSimulation(simId)
        .then((res) => {
          setSimStatus(res)
          setIsPlaying(true)
        })
        .catch((err) => {
          setError(getErrorMessage(err))
          setIsPlaying(false)
        })
    }
  }, [simId, isPlaying, fetchCongestion])

  const handleStepOnce = useCallback(() => {
    if (!simId) return
    setError(null)
    api
      .stepSimulation(simId, speedMultiplier)
      .then(async (res) => {
        setSimStatus(res)
        try {
          const [baseRes, compRes] = await Promise.allSettled([
            api.getBaselineStatus(simId),
            api.getScenarioComparison(simId),
          ])
          if (baseRes.status === 'fulfilled') setBaselineStatus(baseRes.value)
          if (compRes.status === 'fulfilled') setComparison(compRes.value)
        } catch (e) {
          console.warn('Step once sync error:', e)
        }
        fetchCongestion(simId)
        if (res.state === 'completed') setViewMode('results')
      })
      .catch((err) => setError(getErrorMessage(err)))
  }, [simId, speedMultiplier, fetchCongestion])

  const handleReset = useCallback(() => {
    if (!simId) return
    setIsPlaying(false)
    setError(null)
    singleMarkersMapRef.current.clear()
    baselineMarkersMapRef.current.clear()
    optimizedMarkersMapRef.current.clear()
    singleVehiclesGroupRef.current?.clearLayers()
    baselineVehiclesGroupRef.current?.clearLayers()
    optimizedVehiclesGroupRef.current?.clearLayers()
    setCongestion(null)
    setSelectedSegmentId(null)
    api
      .resetSimulation(simId)
      .then(async (res) => {
        setSimStatus(res)
        try {
          const [baseRes, compRes] = await Promise.allSettled([
            api.getBaselineStatus(simId),
            api.getScenarioComparison(simId),
          ])
          if (baseRes.status === 'fulfilled') setBaselineStatus(baseRes.value)
          if (compRes.status === 'fulfilled') setComparison(compRes.value)
        } catch (e) {
          console.warn('Reset sync error:', e)
        }
      })
      .catch((err) => setError(getErrorMessage(err)))
  }, [simId])

  // ─── Road Focus on Results Map ──────────────────────────────────────────────
  const handleFocusSegment = useCallback((segmentId: string) => {
    setSelectedSegmentId(segmentId)
    setViewMode('results')
    const line = resultsPolylineMapRef.current.get(segmentId)
    if (line && resultsMapRef.current) {
      resultsMapRef.current.fitBounds(line.getBounds(), { padding: [50, 50], maxZoom: 17 })
      line.openTooltip()
    }
  }, [])

  // ─── Signal Edit Submission ─────────────────────────────────────────────────
  const handleSubmitSignalEdit = useCallback(() => {
    if (!simId || !selectedSignal) return
    setError(null)
    setSignalSuccessMsg(null)

    const payload: SignalEditRequest = {
      action: signalEditAction,
      parameters: signalEditAction === 'set_fixed_time' ? { cycle_length_s: signalEditCycle } : undefined,
    }


    api
      .editSimulationSignal(simId, selectedSignal.id, payload)
      .then((res) => {
        setSignalSuccessMsg(res.message)
        // Refresh signals list and status
        api.getSimulationSignals(simId).then(setSignalsList).catch(() => {})
        api.getSimulationStatus(simId).then(setSimStatus).catch(() => {})
        setTimeout(() => setIsEditingSignal(false), 1500)
      })
      .catch((err) => {
        setError(getErrorMessage(err))
      })
  }, [simId, selectedSignal, signalEditAction, signalEditCycle])

  // ─── Computed Telemetry Values ──────────────────────────────────────────────
  const elapsed = simStatus?.elapsed_seconds ?? 0
  const duration = simStatus?.duration_seconds ?? durationSeconds
  const progressPct = Math.min(100, (elapsed / duration) * 100)
  const metrics = simStatus?.current_metrics
  const vehiclesCount = simStatus?.vehicles?.length ?? 0
  const baselineVehiclesCount = baselineStatus?.vehicles?.length ?? 0
  const engineMode = simStatus?.engine_mode ?? 'unavailable'

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="flex flex-col gap-6">
      {/* ─── HEADER: TITLE, BADGES, AND PRIMARY CONTROLS ─── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-[#0A1145] tracking-tight">
              SUMO Traffic Simulation
            </h1>
            {engineMode === 'native_sumo' && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse"></span>
                Native SUMO (TraCI)
              </span>
            )}
            {engineMode === 'fallback' && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-300">
                <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                Fallback Kinematics
              </span>
            )}
          </div>
          <p className="text-sm text-slate-500 mt-0.5">
            Microscopic corridor simulation, automated realistic demand, and empirical comparison.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
              isPreparing
                ? 'bg-amber-50 text-amber-700 border-amber-200'
                : isPlaying
                  ? 'bg-blue-50 text-blue-700 border-blue-200'
                  : elapsed >= duration
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-[#e6f4ea] text-[#138808] border-[#a8dab5]'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isPlaying ? 'bg-blue-600 animate-ping' : 'bg-[#138808] animate-pulse'
              }`}
            ></span>
            {isPreparing
              ? 'Compiling Network...'
              : isPlaying
                ? `Simulating (${formatTime(elapsed)})`
                : elapsed >= duration
                  ? 'Completed'
                  : 'Ready'}
          </span>

          <button
            onClick={handleTogglePlay}
            disabled={isPreparing}
            className={`px-5 py-2 rounded-lg font-bold text-xs shadow-sm transition-all flex items-center gap-2 ${
              isPlaying
                ? 'bg-[#138808] hover:bg-[#0f6b06] text-white'
                : 'bg-[#FF9933] hover:bg-[#e68524] text-[#0A1145]'
            } disabled:opacity-50`}
          >
            <span className="material-symbols-outlined text-[18px]">
              {isPlaying ? 'pause' : 'play_arrow'}
            </span>
            <span>{isPlaying ? 'Pause' : elapsed > 0 ? 'Resume' : 'Start Simulation'}</span>
          </button>
        </div>
      </div>

      {/* ─── ERROR & DIAGNOSTIC BANNERS ─── */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">warning</span>
          <span>{error}</span>
        </div>
      )}

      {/* ─── 3 PRIMARY VIEW MODES BAR ─── */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white border border-[#cbdbf5] rounded-xl px-4 py-2.5 shadow-xs">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wider mr-1">
            Mode:
          </span>
          <div className="flex items-center bg-[#eff4ff] p-1 rounded-lg border border-[#cbdbf5]">
            <button
              onClick={() => setViewMode('single')}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'single'
                  ? 'bg-[#0A1145] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">map</span>
              <span>Single Map (Default)</span>
            </button>
            <button
              onClick={() => setViewMode('compare')}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'compare'
                  ? 'bg-[#0A1145] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">compare</span>
              <span>Compare Scenarios</span>
            </button>
            <button
              onClick={() => {
                setViewMode('results')
                if (!congestion && simId) fetchCongestion(simId)
              }}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'results'
                  ? 'bg-[#0A1145] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">analytics</span>
              <span>Results & Congestion</span>
              {congestion && <span className="w-2 h-2 rounded-full bg-[#10B981]"></span>}
            </button>
          </div>
        </div>

        {/* Demand Configuration Toggle & Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDemandConfig(!showDemandConfig)}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-[#cbdbf5] bg-white hover:bg-[#eff4ff] text-[#0A1145] transition-colors flex items-center gap-1.5"
          >
            <span className="material-symbols-outlined text-[16px]">tune</span>
            <span>Traffic Demand Config</span>
            <span className="material-symbols-outlined text-[14px]">
              {showDemandConfig ? 'expand_less' : 'expand_more'}
            </span>
          </button>

          {signalsList && signalsList.signals.length > 0 && (
            <button
              onClick={() => {
                setSelectedSignal(signalsList.signals[0])
                setSignalEditCycle(signalsList.signals[0].cycle_length_s || 90)
                setIsEditingSignal(true)
              }}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-[#cbdbf5] bg-white hover:bg-[#eff4ff] text-[#0A1145] transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-[16px]">traffic</span>
              <span>Inspect Signals ({signalsList.signals.length})</span>
            </button>
          )}
        </div>
      </div>

      {/* ─── AUTOMATIC REALISTIC DEMAND CONFIGURATION PANEL ─── */}
      {showDemandConfig && (
        <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-xl p-4 shadow-xs flex flex-col gap-3">
          <div className="flex items-center justify-between border-b border-[#cbdbf5] pb-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[#0A1145] text-base">auto_mode</span>
              <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wide">
                Automated Traffic Demand Settings
              </span>
            </div>
            <span className="text-[11px] text-slate-500 font-mono">
              Calibrated from Road Network Capacities & Geometries
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
            {/* 1. Demand Level */}
            <div>
              <label className="block text-slate-600 font-medium mb-1">Demand Level:</label>
              <select
                value={demandLevel}
                onChange={(e) => setDemandLevel(e.target.value as DemandLevel)}
                className="w-full bg-white border border-[#cbdbf5] rounded-lg px-2.5 py-1.5 font-medium text-[#0A1145] focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              >
                <option value="low">Low (35% Capacity)</option>
                <option value="normal">Normal (65% Capacity - Recommended)</option>
                <option value="high">High (95% Peak Capacity)</option>
                <option value="custom">Custom (Target Vehicle Count)</option>
              </select>
            </div>

            {/* 2. Demand Profile */}
            <div>
              <label className="block text-slate-600 font-medium mb-1">Departure Profile:</label>
              <select
                value={demandProfile}
                onChange={(e) => setDemandProfile(e.target.value as DemandProfile)}
                className="w-full bg-white border border-[#cbdbf5] rounded-lg px-2.5 py-1.5 font-medium text-[#0A1145] focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              >
                <option value="peak">Peak (Gaussian Curve)</option>
                <option value="uniform">Uniform Spacing</option>
                <option value="ramp_up">Ramp-Up (Increasing)</option>
                <option value="morning_peak">Morning Peak (Early Rush)</option>
              </select>
            </div>

            {/* 3. Duration */}
            <div>
              <label className="block text-slate-600 font-medium mb-1">Simulation Duration:</label>
              <select
                value={durationSeconds}
                onChange={(e) => setDurationSeconds(Number(e.target.value))}
                className="w-full bg-white border border-[#cbdbf5] rounded-lg px-2.5 py-1.5 font-medium text-[#0A1145] focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              >
                <option value={300}>5 Minutes (300s)</option>
                <option value={600}>10 Minutes (600s - Standard)</option>
                <option value={900}>15 Minutes (900s)</option>
              </select>
            </div>

            {/* 4. Seed or Custom Count */}
            <div>
              {demandLevel === 'custom' ? (
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Target Vehicles:</label>
                  <input
                    type="number"
                    min={10}
                    max={500}
                    value={manualVehicles}
                    onChange={(e) => setManualVehicles(Number(e.target.value))}
                    className="w-full bg-white border border-[#cbdbf5] rounded-lg px-2.5 py-1.5 font-medium text-[#0A1145]"
                  />
                </div>
              ) : (
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Reproducibility Seed:</label>
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    className="w-full bg-white border border-[#cbdbf5] rounded-lg px-2.5 py-1.5 font-medium text-[#0A1145]"
                  />
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-[#cbdbf5]">
            <span className="text-[11px] text-slate-500">
              Boundary through-trips prioritized (75%) over internal trips (25%) with minimum 2.0s departure headways.
            </span>
            <button
              onClick={() => {
                initSimulation({
                  level: demandLevel,
                  profile: demandProfile,
                  duration: durationSeconds,
                  manualCount: manualVehicles,
                  simSeed: seed,
                })
                setShowDemandConfig(false)
              }}
              className="px-4 py-1.5 bg-[#0A1145] text-white font-bold text-xs rounded-lg hover:bg-[#1a237e] transition-colors shadow-xs"
            >
              Apply & Re-generate Simulation
            </button>
          </div>
        </div>
      )}

      {/* ─── MODE A: SINGLE MAP (DEFAULT) ─── */}
      <div className={viewMode === 'single' ? 'flex flex-col gap-4' : 'hidden'}>
        <div className="bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col">
          <div className="relative w-full h-[520px] bg-[#f8faff] overflow-hidden">
            <div ref={singleMapContainerRef} className="w-full h-full" />

            {/* Network Overview Badge */}
            <div className="absolute top-4 left-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg px-3 py-1.5 shadow-xs text-xs">
              <span className="font-bold text-[#0A1145]">Active Network:</span>
              <span className="text-slate-600 font-mono text-[11px] ml-1">
                {simStatus?.edge_count ?? analysis.segments.length} Edges • {simStatus?.junction_count ?? 0} Junctions • {simStatus?.signal_count ?? 0} Signals
              </span>
            </div>

            {/* Active Vehicles Counter */}
            <div className="absolute bottom-4 left-4 z-[500] bg-[#0A1145]/90 text-white backdrop-blur-xs rounded-lg px-3 py-1 shadow-xs text-xs font-mono font-semibold">
              {vehiclesCount} Active Vehicles
            </div>

            {/* Traffic Conditions Legend */}
            <div className="absolute top-4 right-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg p-2.5 shadow-xs text-xs flex flex-col gap-1 max-w-[200px]">
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">
                Vehicle States
              </div>
              <div className="flex items-center gap-2 text-[11px] text-slate-700">
                <span className="w-2.5 h-2.5 rounded-full bg-[#138808]"></span>
                <span>Flowing (&gt; 35 km/h)</span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-slate-700">
                <span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></span>
                <span>Moderate (18-35 km/h)</span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-slate-700">
                <span className="w-2.5 h-2.5 rounded-full bg-[#DC2626]"></span>
                <span>Queue / Congested (&lt; 18)</span>
              </div>
              <div className="border-t border-slate-200 pt-1 mt-0.5 flex items-center gap-2 text-[11px] text-slate-700">
                <span className="w-2.5 h-2.5 rounded-xs bg-[#0A1145]"></span>
                <span>Bus Transit</span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-slate-700">
                <span className="w-2.5 h-2.5 rounded-full bg-[#138808] border border-white shadow-xs"></span>
                <span>Signal (Click to Inspect)</span>
              </div>
            </div>
          </div>

          {/* Integrated Playback Controls */}
          <div className="px-5 py-3 bg-white border-t border-[#cbdbf5] flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <button
                onClick={handleTogglePlay}
                className={`flex items-center gap-1.5 px-4 py-2 font-bold text-xs rounded-lg shadow-xs transition-all ${
                  isPlaying
                    ? 'bg-[#138808] hover:bg-[#0f6b06] text-white'
                    : 'bg-[#FF9933] hover:bg-[#e68524] text-[#0A1145]'
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">
                  {isPlaying ? 'pause' : 'play_arrow'}
                </span>
                <span>{isPlaying ? 'Pause' : elapsed > 0 ? 'Resume' : 'Play'}</span>
              </button>
              <button
                onClick={handleStepOnce}
                disabled={isPlaying}
                className="flex items-center gap-1 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[16px] text-slate-500">redo</span>
                <span>Step</span>
              </button>
              <button
                onClick={handleReset}
                className="flex items-center gap-1 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors"
              >
                <span className="material-symbols-outlined text-[16px] text-slate-500">restart_alt</span>
                <span>Reset</span>
              </button>
            </div>

            {/* Timeline Progress */}
            <div className="flex-1 max-w-md flex items-center gap-3">
              <span className="font-mono text-xs font-bold text-[#0A1145]">{formatTime(elapsed)}</span>
              <div className="flex-1 bg-[#eff4ff] h-2 rounded-full overflow-hidden border border-[#cbdbf5]">
                <div
                  className="bg-[#FF9933] h-full rounded-full transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                ></div>
              </div>
              <span className="font-mono text-xs text-slate-500">{formatTime(duration)}</span>
            </div>

            {/* Speed Selector */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-500">Speed:</span>
              <div className="flex items-center bg-[#eff4ff] p-0.5 rounded-lg border border-[#cbdbf5]">
                {[1, 2, 5].map((spd) => (
                  <button
                    key={spd}
                    onClick={() => setSpeedMultiplier(spd)}
                    className={`px-2.5 py-1 text-xs rounded transition-all ${
                      speedMultiplier === spd
                        ? 'bg-[#0A1145] text-white font-bold shadow-xs'
                        : 'text-slate-600 font-semibold hover:text-[#0A1145]'
                    }`}
                  >
                    {spd}x
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─── MODE B: COMPARE REGULAR VS. OPTIMIZED (DUAL MAPS WITH INDEPENDENT FULLSCREEN) ─── */}
      <div className={viewMode === 'compare' ? 'flex flex-col gap-4' : 'hidden'}>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* LEFT MAP: REGULAR TRAFFIC (BASELINE - FIXED TIME) */}
          <div
            className={`bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col transition-all ${
              fullscreenMap === 'baseline'
                ? 'fixed inset-0 z-[9999] p-4 bg-slate-900/80 backdrop-blur-sm'
                : 'relative'
            }`}
          >
            {/* Header / Expand Control */}
            <div className="px-4 py-2.5 bg-[#f8faff] border-b border-[#cbdbf5] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-slate-500"></span>
                <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wide">
                  Regular Traffic (Baseline)
                </span>
                <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded border border-slate-200">
                  Fixed-Time Control
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono text-slate-500">
                  {baselineVehiclesCount} vehs
                </span>
                <button
                  onClick={() => {
                    const next = fullscreenMap === 'baseline' ? null : 'baseline'
                    setFullscreenMap(next)
                    setTimeout(() => baselineMapRef.current?.invalidateSize(), 150)
                  }}
                  className="p-1 rounded hover:bg-slate-200 text-slate-600 transition-colors"
                  title={fullscreenMap === 'baseline' ? 'Restore side-by-side' : 'Expand full screen'}
                >
                  <span className="material-symbols-outlined text-[18px]">
                    {fullscreenMap === 'baseline' ? 'fullscreen_exit' : 'fullscreen'}
                  </span>
                </button>
              </div>
            </div>

            {/* Baseline Canvas */}
            <div className={`relative w-full ${fullscreenMap === 'baseline' ? 'flex-1' : 'h-[440px]'} bg-[#f8faff] overflow-hidden`}>
              <div ref={baselineMapContainerRef} className="w-full h-full" />
              <div className="absolute bottom-3 left-3 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded px-2.5 py-1 text-[11px] font-mono">
                Speed: {baselineStatus?.current_metrics?.avg_speed_kmh?.toFixed(1) ?? '—'} km/h • Wait: {baselineStatus?.current_metrics?.avg_waiting_time_s?.toFixed(1) ?? '—'}s
              </div>
            </div>
          </div>

          {/* RIGHT MAP: OPTIMIZED TRAFFIC (ACTUATED ADAPTIVE + INTERVENTIONS) */}
          <div
            className={`bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col transition-all ${
              fullscreenMap === 'optimized'
                ? 'fixed inset-0 z-[9999] p-4 bg-slate-900/80 backdrop-blur-sm'
                : 'relative'
            }`}
          >
            {/* Header / Expand Control */}
            <div className="px-4 py-2.5 bg-[#eff4ff] border-b border-[#cbdbf5] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#138808] animate-pulse"></span>
                <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wide">
                  Optimized Traffic
                </span>
                <span className="text-[10px] bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded border border-emerald-300">
                  Actuated Adaptive Control
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono text-emerald-700 font-semibold">
                  {vehiclesCount} vehs
                </span>
                <button
                  onClick={() => {
                    const next = fullscreenMap === 'optimized' ? null : 'optimized'
                    setFullscreenMap(next)
                    setTimeout(() => optimizedMapRef.current?.invalidateSize(), 150)
                  }}
                  className="p-1 rounded hover:bg-slate-200 text-slate-600 transition-colors"
                  title={fullscreenMap === 'optimized' ? 'Restore side-by-side' : 'Expand full screen'}
                >
                  <span className="material-symbols-outlined text-[18px]">
                    {fullscreenMap === 'optimized' ? 'fullscreen_exit' : 'fullscreen'}
                  </span>
                </button>
              </div>
            </div>

            {/* Optimized Canvas */}
            <div className={`relative w-full ${fullscreenMap === 'optimized' ? 'flex-1' : 'h-[440px]'} bg-[#f8faff] overflow-hidden`}>
              <div ref={optimizedMapContainerRef} className="w-full h-full" />
              <div className="absolute bottom-3 left-3 z-[500] bg-white/95 backdrop-blur-xs border border-emerald-300 rounded px-2.5 py-1 text-[11px] font-mono text-[#0A1145]">
                Speed: {metrics?.avg_speed_kmh?.toFixed(1) ?? '—'} km/h • Wait: {metrics?.avg_waiting_time_s?.toFixed(1) ?? '—'}s
              </div>
            </div>
          </div>
        </div>

        {/* Synchronized Playback Control Bar for Compare Mode */}
        <div className="bg-white border border-[#cbdbf5] rounded-xl px-5 py-3 flex flex-wrap items-center justify-between gap-4 shadow-xs">
          <div className="flex items-center gap-2">
            <button
              onClick={handleTogglePlay}
              className={`flex items-center gap-1.5 px-4 py-2 font-bold text-xs rounded-lg shadow-xs transition-all ${
                isPlaying
                  ? 'bg-[#138808] hover:bg-[#0f6b06] text-white'
                  : 'bg-[#FF9933] hover:bg-[#e68524] text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[16px]">
                {isPlaying ? 'pause' : 'play_arrow'}
              </span>
              <span>{isPlaying ? 'Pause' : elapsed > 0 ? 'Resume Both' : 'Play Both'}</span>
            </button>
            <button
              onClick={handleStepOnce}
              disabled={isPlaying}
              className="flex items-center gap-1 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px] text-slate-500">redo</span>
              <span>Step Both</span>
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-1 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors"
            >
              <span className="material-symbols-outlined text-[16px] text-slate-500">restart_alt</span>
              <span>Reset Both</span>
            </button>
          </div>

          <div className="flex-1 max-w-md flex items-center gap-3">
            <span className="font-mono text-xs font-bold text-[#0A1145]">{formatTime(elapsed)}</span>
            <div className="flex-1 bg-[#eff4ff] h-2 rounded-full overflow-hidden border border-[#cbdbf5]">
              <div
                className="bg-[#FF9933] h-full rounded-full transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              ></div>
            </div>
            <span className="font-mono text-xs text-slate-500">{formatTime(duration)}</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">Speed:</span>
            <div className="flex items-center bg-[#eff4ff] p-0.5 rounded-lg border border-[#cbdbf5]">
              {[1, 2, 5].map((spd) => (
                <button
                  key={spd}
                  onClick={() => setSpeedMultiplier(spd)}
                  className={`px-2.5 py-1 text-xs rounded transition-all ${
                    speedMultiplier === spd
                      ? 'bg-[#0A1145] text-white font-bold shadow-xs'
                      : 'text-slate-600 font-semibold hover:text-[#0A1145]'
                  }`}
                >
                  {spd}x
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ─── MODE C: RESULTS & CONGESTION ANALYSIS (SINGLE LARGE CONGESTION MAP) ─── */}
      <div className={viewMode === 'results' ? 'flex flex-col gap-6' : 'hidden'}>
        <div className="bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col">
          <div className="px-5 py-3 border-b border-[#cbdbf5] flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[#0A1145] text-base">traffic</span>
                <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wide">
                  Post-Simulation Congestion Analysis Map
                </span>
                {congestion && (
                  <span className="text-[10px] bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full border border-emerald-300 font-semibold">
                    {congestion.roads_analyzed} Roads Analyzed
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500">
                Segment-level multi-attribute congestion scores calculated directly from TraCI edge telemetry.
              </p>
            </div>
            <button
              onClick={() => simId && fetchCongestion(simId)}
              disabled={isLoadingCongestion}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-[#0A1145] text-white hover:bg-[#1a237e] transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[15px] ${isLoadingCongestion ? 'animate-spin' : ''}`}>
                refresh
              </span>
              <span>{isLoadingCongestion ? 'Analyzing...' : 'Re-analyze Telemetry'}</span>
            </button>
          </div>

          <div className="relative w-full h-[480px] bg-[#f8faff] overflow-hidden">
            <div ref={resultsMapContainerRef} className="w-full h-full" />

            {/* Severity Legend */}
            <div className="absolute top-4 right-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg p-2.5 shadow-xs text-xs flex flex-col gap-1 max-w-[210px]">
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5 flex items-center justify-between">
                <span>Congestion Severity</span>
                <span className="text-[9px] text-[#0A1145] font-mono">Score</span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#10B981]"></span>
                  <span>Free Flow</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">&lt; 20%</span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#84CC16]"></span>
                  <span>Low Congestion</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">20-40%</span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></span>
                  <span>Moderate</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">40-60%</span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#EF4444]"></span>
                  <span>High Congestion</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">60-80%</span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#7F1D1D]"></span>
                  <span>Severe</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">≥ 80%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Top-5 Bottlenecks Table */}
        {congestion && congestion.top_congested.length > 0 && (
          <div className="bg-white rounded-xl border border-[#cbdbf5] p-5 shadow-xs">
            <h2 className="text-sm font-bold text-[#0A1145] mb-3">
              Ranked Network Bottlenecks (Top 5 Congested Roads)
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-[#f8faff] text-slate-600 border-b border-[#cbdbf5]">
                    <th className="py-2.5 px-3 font-semibold w-12 text-center">Rank</th>
                    <th className="py-2.5 px-4 font-semibold">Road Segment</th>
                    <th className="py-2.5 px-3 font-semibold">Type</th>
                    <th className="py-2.5 px-4 font-semibold">Congestion Score</th>
                    <th className="py-2.5 px-3 font-semibold">Severity</th>
                    <th className="py-2.5 px-3 font-semibold">Speed / Limit</th>
                    <th className="py-2.5 px-3 font-semibold">Occupancy</th>
                    <th className="py-2.5 px-3 font-semibold text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#e2e8f0] text-xs">
                  {congestion.top_congested.map((road, idx) => {
                    const isSelected = selectedSegmentId === road.segment_id
                    const scorePct = Math.round(road.congestion_score * 100)
                    return (
                      <tr
                        key={road.segment_id}
                        onClick={() => handleFocusSegment(road.segment_id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected ? 'bg-indigo-50/70 font-medium' : 'hover:bg-[#f8f9ff]'
                        }`}
                      >
                        <td className="py-3 px-3 text-center font-bold text-slate-500 font-mono">
                          #{idx + 1}
                        </td>
                        <td className="py-3 px-4">
                          <div className="font-semibold text-[#0A1145]">{road.road_name}</div>
                          <div className="text-[10px] text-slate-400 font-mono">
                            ID: {road.segment_id} • SUMO: {road.sumo_edge_ids.join(', ')}
                          </div>
                        </td>
                        <td className="py-3 px-3 capitalize text-slate-600 font-medium">
                          {road.road_type}
                        </td>
                        <td className="py-3 px-4 min-w-[140px]">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-200">
                              <div
                                className="h-full rounded-full bg-[#EF4444]"
                                style={{ width: `${scorePct}%` }}
                              ></div>
                            </div>
                            <span className="font-mono font-bold text-[#0A1145] text-xs">
                              {scorePct}%
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-3 capitalize font-bold text-rose-700">
                          {road.severity.replace('_', ' ')}
                        </td>
                        <td className="py-3 px-3 font-mono">
                          {road.avg_speed_kmh.toFixed(1)} / {road.ref_speed_kmh} km/h
                        </td>
                        <td className="py-3 px-3 font-mono">{road.avg_occupancy_pct.toFixed(1)}%</td>
                        <td className="py-3 px-3 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleFocusSegment(road.segment_id)
                            }}
                            className="px-2.5 py-1 text-[11px] font-semibold rounded border border-[#cbdbf5] bg-white hover:bg-slate-100 text-[#0A1145]"
                          >
                            Locate
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* ─── COMPREHENSIVE KPI COMPARISON TABLE (SHARED) ─── */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between border-b border-[#e2e8f0] pb-3 mb-4 gap-2">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-[#0A1145]">Measured KPI Comparison</h2>
              {comparison?.comparison_status && (
                <span
                  className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${
                    comparison.comparison_status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : 'bg-slate-100 text-slate-600 border-slate-200'
                  }`}
                >
                  {comparison.comparison_status}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">
              {comparison?.baseline_strategy || 'Baseline (Fixed-Time)'} vs.{' '}
              {comparison?.optimized_strategy || 'Optimized (Actuated Adaptive)'}
            </p>
          </div>
          <span className="text-[11px] font-mono text-slate-600 bg-[#eff4ff] border border-[#cbdbf5] px-2.5 py-1 rounded">
            Seed: {seed} • {duration}s Duration
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-[#f8faff] text-slate-600 border-b border-[#cbdbf5]">
                <th className="py-2.5 px-4 font-semibold">Performance Metric</th>
                <th className="py-2.5 px-4 font-semibold">Baseline (Fixed-Time)</th>
                <th className="py-2.5 px-4 font-semibold">Optimized (Adaptive)</th>
                <th className="py-2.5 px-4 font-semibold">Empirical Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] font-mono text-xs">
              {comparison?.rows?.map((row, idx) => {
                const isPending =
                  row.variance.toLowerCase().includes('pending') ||
                  row.variance.toLowerCase().includes('insufficient')
                return (
                  <tr key={idx} className="hover:bg-[#f8f9ff]">
                    <td className="py-3 px-4 font-sans font-medium text-[#0A1145]">{row.metric}</td>
                    <td className="py-3 px-4 text-slate-600">{row.baseline}</td>
                    <td className="py-3 px-4 font-bold text-[#0A1145]">{row.optimized}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-bold ${
                          isPending
                            ? 'text-slate-500 bg-slate-100'
                            : row.is_improvement
                              ? 'text-[#138808] bg-[#e6f4ea]'
                              : 'text-[#DC2626] bg-[#fde8e8]'
                        }`}
                      >
                        {row.variance}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-3 pt-2 text-[11px] text-slate-400 italic">
          {comparison?.methodology_notes ??
            'Simulation outputs measured from native TraCI execution without synthetic multipliers.'}
        </div>
      </div>

      {/* ─── TRAFFIC SIGNAL INSPECTION & EDITING MODAL ─── */}
      {isEditingSignal && selectedSignal && (
        <div className="fixed inset-0 z-[10000] bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-[#cbdbf5] max-w-lg w-full p-6 shadow-xl flex flex-col gap-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-[#cbdbf5] pb-3">
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[#0A1145] text-xl">traffic</span>
                <div>
                  <h3 className="text-base font-bold text-[#0A1145]">
                    Inspect & Edit Traffic Signal
                  </h3>
                  <div className="text-[11px] text-slate-500 font-mono">
                    Signal ID: {selectedSignal.id} • Junction: {selectedSignal.junction_id}
                  </div>
                </div>
              </div>
              <button
                onClick={() => setIsEditingSignal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            {signalSuccessMsg && (
              <div className="p-3 bg-emerald-50 border border-emerald-300 rounded-lg text-xs text-emerald-800 flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">check_circle</span>
                <span>{signalSuccessMsg}</span>
              </div>
            )}

            {/* Controller Status & Safety Badge */}
            <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-xl p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-600 font-medium">Current Control Type:</span>
                <span className="font-bold text-[#0A1145] uppercase">
                  {selectedSignal.control_type.replace('_', ' ')}
                </span>
              </div>
              <div className="text-[11px] text-slate-500 border-t border-slate-200 pt-1.5">
                <span className="font-semibold text-slate-700">Safety Assessment: </span>
                <span>{selectedSignal.safety_assessment}</span>
              </div>
            </div>

            {/* Editing Controls (Optimized Scenario Only) */}
            <div className="flex flex-col gap-3 text-xs">
              <div>
                <label className="block text-slate-700 font-semibold mb-1">Select Action:</label>
                <select
                  value={signalEditAction}
                  onChange={(e) => setSignalEditAction(e.target.value as SignalEditRequest['action'])}
                  className="w-full bg-white border border-[#cbdbf5] rounded-lg px-3 py-2 font-medium text-[#0A1145]"
                >
                  <option value="set_adaptive">Enable Actuated Adaptive Control</option>
                  <option value="set_fixed_time">Switch to Fixed-Time Control (Specify Cycle Length)</option>
                  <option value="remove_signal">Remove Signal (Convert to Priority Yielding)</option>
                  <option value="restore_original">Restore Original Configuration</option>
                </select>
              </div>

              {signalEditAction === 'set_fixed_time' && (
                <div>
                  <label className="block text-slate-700 font-semibold mb-1">
                    Cycle Length (seconds):
                  </label>
                  <input
                    type="number"
                    min={40}
                    max={180}
                    value={signalEditCycle}
                    onChange={(e) => setSignalEditCycle(Number(e.target.value))}
                    className="w-full bg-white border border-[#cbdbf5] rounded-lg px-3 py-2 font-mono font-medium text-[#0A1145]"
                  />
                  <span className="text-[10px] text-slate-400 mt-0.5 block">
                    Fixed green splits are distributed with mandatory 3.5s yellow clearance intervals.
                  </span>
                </div>
              )}


              {signalEditAction === 'remove_signal' && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-[11px] flex items-start gap-2">
                  <span className="material-symbols-outlined text-amber-600 text-sm mt-0.5 shrink-0">
                    warning
                  </span>
                  <span>
                    Converting this signalized intersection to an unsignalized priority junction applies right-of-way rules.
                    This change affects the <b>Optimized</b> scenario only; the baseline remains untouched.
                  </span>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#cbdbf5]">
              <button
                onClick={() => setIsEditingSignal(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitSignalEdit}
                className="px-4 py-2 text-xs font-bold text-white bg-[#0A1145] hover:bg-[#1a237e] rounded-lg transition-colors shadow-xs"
              >
                Save Intervention
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
