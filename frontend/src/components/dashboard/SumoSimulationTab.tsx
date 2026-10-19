import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
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
} from '../../types/api'

interface SumoSimulationTabProps {
  analysis: AnalysisResult
}

export default function SumoSimulationTab({ analysis }: SumoSimulationTabProps) {
  const [simId, setSimId] = useState<string | null>(null)
  const [simStatus, setSimStatus] = useState<SimulationStatusResponse | null>(null)
  const [comparison, setComparison] = useState<ScenarioComparisonResult | null>(null)
  const [congestion, setCongestion] = useState<CongestionSummary | null>(null)
  const [isLoadingCongestion, setIsLoadingCongestion] = useState<boolean>(false)
  const [viewMode, setViewMode] = useState<'simulation' | 'congestion'>('simulation')
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(2)
  const [isPlaying, setIsPlaying] = useState<boolean>(false)
  const [isPreparing, setIsPreparing] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const timerRef = useRef<number | null>(null)
  const isSteppingRef = useRef<boolean>(false)
  const markersMapRef = useRef<Map<string, L.Marker>>(new Map())
  const polylineMapRef = useRef<Map<string, L.Polyline>>(new Map())
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const segmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const vehiclesGroupRef = useRef<L.LayerGroup | null>(null)
  const signalsGroupRef = useRef<L.LayerGroup | null>(null)

  const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY

  const getErrorMessage = (err: unknown): string => {
    if (err instanceof GativaApiError) return err.message
    if (err instanceof Error) return err.message
    return String(err)
  }

  // 1. Prepare Simulation on Mount or when analysisId changes
  useEffect(() => {
    let isMounted = true

    api
      .prepareSimulation({
        analysis_id: analysis.analysis_id,
        duration_seconds: 600,
        demand_rate_veh_hr: 2840,
        strategy: 'actuated_adaptive',
      })
      .then((res) => {
        if (isMounted) {
          setSimId(res.sim_id)
          setSimStatus(res)
          setIsPreparing(false)
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(getErrorMessage(err))
          setIsPreparing(false)
        }
      })

    return () => {
      isMounted = false
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [analysis.analysis_id])

  const fetchCongestion = useCallback((id: string) => {
    setIsLoadingCongestion(true)
    api
      .getCongestionResults(id)
      .then((data) => {
        setCongestion(data)
      })
      .catch((err) => {
        console.warn('Failed to fetch congestion summary:', err)
      })
      .finally(() => {
        setIsLoadingCongestion(false)
      })
  }, [])

  // 2. Fetch Comparison & Initial Congestion Results once prepared
  useEffect(() => {
    if (!simId) return
    api
      .getScenarioComparison(simId)
      .then((data) => setComparison(data))
      .catch((err) => setError(getErrorMessage(err)))

    fetchCongestion(simId)
  }, [simId, fetchCongestion])

  const handleComputeCongestion = useCallback(async () => {
    if (!simId) return
    setIsLoadingCongestion(true)
    try {
      if ((simStatus?.step ?? 0) < 3) {
        const stepRes = await api.stepSimulation(simId, 3)
        setSimStatus(stepRes)
      }
      const data = await api.getCongestionResults(simId)
      setCongestion(data)
    } catch (err) {
      console.warn('Failed to compute congestion:', err)
      setError(getErrorMessage(err))
    } finally {
      setIsLoadingCongestion(false)
    }
  }, [simId, simStatus?.step])

  const handleFocusSegment = useCallback((segmentId: string) => {
    setSelectedSegmentId(segmentId)
    setViewMode('congestion')
    const line = polylineMapRef.current.get(segmentId)
    if (line && mapRef.current) {
      mapRef.current.fitBounds(line.getBounds(), { padding: [50, 50], maxZoom: 17 })
      line.openTooltip()
    }
  }, [])

  // 3. Step Loop when isPlaying is true
  useEffect(() => {
    if (!isPlaying || !simId) {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
      return
    }

    const intervalMs = Math.max(100, Math.floor(400 / speedMultiplier))
    timerRef.current = window.setInterval(() => {
      if (isSteppingRef.current) return
      isSteppingRef.current = true

      api
        .stepSimulation(simId, speedMultiplier)
        .then((res) => {
          setSimStatus(res)
          if (res.state === 'completed') {
            setIsPlaying(false)
            api
              .getScenarioComparison(simId)
              .then(setComparison)
              .catch((err) => setError(getErrorMessage(err)))
            fetchCongestion(simId)
            setViewMode('congestion')
          }
        })
        .catch((err) => {
          setError(getErrorMessage(err))
          setIsPlaying(false)
        })
        .finally(() => {
          isSteppingRef.current = false
        })
    }, intervalMs)

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [isPlaying, simId, speedMultiplier, fetchCongestion])

  // Handlers
  const handleTogglePlay = useCallback(() => {
    if (!simId) return
    if (isPlaying) {
      api
        .pauseSimulation(simId)
        .then((res) => setSimStatus(res))
        .catch((err) => setError(getErrorMessage(err)))
      setIsPlaying(false)
      api
        .getScenarioComparison(simId)
        .then(setComparison)
        .catch((err) => setError(getErrorMessage(err)))
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
      .stepSimulation(simId, 2)
      .then((res) => {
        setSimStatus(res)
        api
          .getScenarioComparison(simId)
          .then(setComparison)
          .catch((err) => setError(getErrorMessage(err)))
        fetchCongestion(simId)
        if (res.state === 'completed') {
          setViewMode('congestion')
        }
      })
      .catch((err) => setError(getErrorMessage(err)))
  }, [simId, fetchCongestion])

  const handleReset = useCallback(() => {
    if (!simId) return
    setIsPlaying(false)
    setError(null)
    markersMapRef.current.clear()
    vehiclesGroupRef.current?.clearLayers()
    setCongestion(null)
    setSelectedSegmentId(null)
    setViewMode('simulation')
    api
      .resetSimulation(simId)
      .then((res) => {
        setSimStatus(res)
        api
          .getScenarioComparison(simId)
          .then(setComparison)
          .catch((err) => setError(getErrorMessage(err)))
      })
      .catch((err) => setError(getErrorMessage(err)))
  }, [simId])

  // 4. Initialize Leaflet Map in Simulation Viewport
  useEffect(() => {
    if (!mapContainerRef.current) return
    if (mapRef.current) return

    const map = L.map(mapContainerRef.current, {
      zoomControl: false,
      attributionControl: true,
    })

    L.control.zoom({ position: 'bottomright' }).addTo(map)

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

    const segGroup = L.layerGroup().addTo(map)
    const vehGroup = L.layerGroup().addTo(map)
    const sigGroup = L.layerGroup().addTo(map)

    segmentsGroupRef.current = segGroup
    vehiclesGroupRef.current = vehGroup
    signalsGroupRef.current = sigGroup
    mapRef.current = map

    // Render polygon boundary and road network
    if (analysis.polygon?.coordinates?.[0]?.length) {
      const ring = analysis.polygon.coordinates[0]
      const latLngs: L.LatLngExpression[] = ring.map((c) => [c[1], c[0]])
      L.polygon(latLngs, {
        color: '#2d3b8f',
        weight: 1.5,
        fillColor: '#eff4ff',
        fillOpacity: 0.15,
        dashArray: '4 4',
      }).addTo(segGroup)

      const bounds = L.latLngBounds(latLngs)
      map.fitBounds(bounds, { padding: [30, 30] })
    }

    // Render road network segments
    polylineMapRef.current.clear()
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

        line.on('click', () => {
          setSelectedSegmentId(seg.segment_id)
        })

        segGroup.addLayer(line)
        polylineMapRef.current.set(seg.segment_id, line)
      })
    }

    const polylineMap = polylineMapRef.current
    return () => {
      polylineMap.clear()
      map.remove()
      mapRef.current = null
    }
  }, [analysis.polygon, analysis.segments, TOMTOM_KEY])

  // 4b. Dynamic Polyline Recoloring based on View Mode (Live Simulation vs Congestion Analysis)
  useEffect(() => {
    if (!analysis.segments?.length) return

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
      const line = polylineMapRef.current.get(seg.segment_id)
      if (!line) return

      const isSelected = selectedSegmentId === seg.segment_id

      if (viewMode === 'congestion' && congestion) {
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
      } else {
        const defaultColor =
          seg.road_type === 'highway'
            ? '#ff9933'
            : seg.road_type === 'arterial'
              ? '#2d3b8f'
              : '#64748b'
        const defaultWeight = seg.road_type === 'highway' ? 4 : seg.road_type === 'arterial' ? 3 : 2

        line.setStyle({
          color: isSelected ? '#4338CA' : defaultColor,
          weight: isSelected ? defaultWeight + 3 : defaultWeight,
          opacity: 0.8,
        })

        line.setTooltipContent(
          `<div class="text-xs font-sans"><b>${seg.name || 'Road Segment'}</b><br/>${seg.road_type} • ${seg.length_m.toFixed(0)}m</div>`,
        )
      }
    })
  }, [viewMode, congestion, selectedSegmentId, analysis.segments])

  // 5. Update vehicle positions and signals dynamically
  const elapsed = simStatus?.elapsed_seconds ?? 0
  const duration = simStatus?.duration_seconds ?? 600
  const progressPct = Math.min(100, (elapsed / duration) * 100)
  const metrics = simStatus?.current_metrics
  const vehicles: VehiclePosition[] = useMemo(
    () => simStatus?.vehicles ?? [],
    [simStatus?.vehicles],
  )
  useEffect(() => {
    const vehGroup = vehiclesGroupRef.current
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

        const existingMarker = markersMapRef.current.get(veh.id)
        if (existingMarker) {
          existingMarker.setLatLng([veh.lat, veh.lng])
          existingMarker.setIcon(icon)
          existingMarker.setTooltipContent(tooltipHtml)
        } else {
          const newMarker = L.marker([veh.lat, veh.lng], { icon })
          newMarker.bindTooltip(tooltipHtml, { direction: 'top', offset: [0, -6] })
          vehGroup.addLayer(newMarker)
          markersMapRef.current.set(veh.id, newMarker)
        }
      }
    })

    // Remove inactive vehicles from the map
    markersMapRef.current.forEach((marker, id) => {
      if (!currentIds.has(id)) {
        vehGroup.removeLayer(marker)
        markersMapRef.current.delete(id)
      }
    })
  }, [vehicles])

  // Update real SUMO signal indicators
  useEffect(() => {
    const sigGroup = signalsGroupRef.current
    if (!sigGroup) return

    sigGroup.clearLayers()

    const trafficLights = simStatus?.traffic_lights || []
    trafficLights.forEach((tl, idx) => {
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
          tl.state === 'green'
            ? '#138808'
            : tl.state === 'yellow'
              ? '#F59E0B'
              : '#DC2626'

        const sigIcon = L.divIcon({
          className: 'sumo-signal-icon',
          iconSize: [26, 26],
          iconAnchor: [13, 13],
          html: `<div style="width: 26px; height: 26px; border-radius: 50%; background: #0A1145; border: 2px solid #ffffff; box-shadow: 0 2px 5px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; position: relative;">
            <span style="font-size: 8px; color: #FF9933; font-weight: bold; font-family: monospace;">TL${idx + 1}</span>
            <span style="position: absolute; top: -2px; right: -2px; width: 9px; height: 9px; border-radius: 50%; background: ${stateColor}; border: 1.5px solid #ffffff; box-shadow: 0 0 6px ${stateColor};"></span>
          </div>`,
        })
        const sigMarker = L.marker([tl.lat, tl.lng], { icon: sigIcon })
        sigMarker.bindTooltip(
          `<div class="text-[11px] font-sans"><b>Traffic Signal: ${tl.id}</b><br/>Current Phase: <span style="font-weight:bold;color:${stateColor}">${tl.state.toUpperCase()}</span><br/>Controlled Approaches: ${tl.controlled_lanes?.length ?? 0} lanes</div>`,
        )
        sigGroup.addLayer(sigMarker)
      }
    })
  }, [simStatus?.traffic_lights])

  // Format MM:SS
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const engineMode = simStatus?.engine_mode ?? 'unavailable'

  return (
    <div className="flex flex-col gap-6">
      {/* AREA A: PAGE HEADER */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-[#0A1145] tracking-tight">
              SUMO Traffic Simulation
            </h1>
            {/* Explicit Engine Mode Badge */}
            {engineMode === 'native_sumo' && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse"></span>
                Native SUMO (TraCI)
              </span>
            )}
            {engineMode === 'fallback' && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-300">
                <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                Fallback Simulation (Internal Engine)
              </span>
            )}
            {engineMode === 'unavailable' && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-50 text-red-700 border border-red-300">
                <span className="w-2 h-2 rounded-full bg-red-500"></span>
                Engine Unavailable
              </span>
            )}
          </div>
          <p className="text-sm text-slate-500 mt-0.5">
            Microscopic traffic simulation and empirical comparative telemetry.
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
                  ? 'Completed (600s)'
                  : 'Ready to Simulate'}
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
            <span>{isPlaying ? 'Pause Simulation' : elapsed > 0 ? 'Resume Simulation' : 'Start Simulation'}</span>
          </button>
        </div>
      </div>

      {/* Fallback Mode Diagnostic Banner */}
      {engineMode === 'fallback' && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800 flex items-start gap-2.5">
          <span className="material-symbols-outlined text-amber-600 text-base shrink-0 mt-0.5">
            info
          </span>
          <div>
            <span className="font-bold">Operating in Fallback Kinematics Mode: </span>
            <span>
              {simStatus?.engine_message ||
                'Running internal physics engine along selected corridor geometry. Measurements reflect empirical kinematics rather than compiled TraCI telemetry.'}
            </span>
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">warning</span>
          <span>{error}</span>
        </div>
      )}

      {/* Secondary Configuration Bar */}
      <div className="bg-white border border-[#cbdbf5] rounded-xl px-5 py-3 flex flex-wrap items-center justify-between gap-4 text-xs shadow-xs">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-slate-500 font-medium">Duration:</span>
            <span className="font-mono font-semibold text-[#0A1145] bg-[#eff4ff] px-2 py-0.5 rounded border border-[#cbdbf5]">
              10 mins (600s)
            </span>
          </div>
          <div className="h-4 w-px bg-[#e2e8f0] hidden sm:block"></div>
          <div className="flex items-center gap-2">
            <span className="text-slate-500 font-medium">Demand:</span>
            <span className="font-semibold text-[#0A1145]">
              Peak ({simStatus?.demand_rate_veh_hr?.toLocaleString() ?? '2,840'} veh/hr)
            </span>
          </div>
          <div className="h-4 w-px bg-[#e2e8f0] hidden sm:block"></div>
          <div className="flex items-center gap-2">
            <span className="text-slate-500 font-medium">Strategy:</span>
            <span className="font-semibold text-[#0A1145] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#138808]"></span>
              Adaptive Signal Control (Actuated)
            </span>
          </div>
        </div>
        <div className="text-[11px] font-mono text-slate-500 flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              engineMode === 'native_sumo' ? 'bg-[#138808]' : 'bg-amber-500'
            }`}
          ></span>
          <span>
            {engineMode === 'native_sumo'
              ? 'TraCI Engine • Step: 0.2s'
              : 'Kinematics Fallback • Step: 0.5s'}
          </span>
        </div>
      </div>

      {/* View Mode Switcher Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white border border-[#cbdbf5] rounded-xl px-4 py-2.5 shadow-xs">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-[#0A1145] uppercase tracking-wider mr-1">
            Display Mode:
          </span>
          <div className="flex items-center bg-[#eff4ff] p-1 rounded-lg border border-[#cbdbf5]">
            <button
              onClick={() => setViewMode('simulation')}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'simulation'
                  ? 'bg-[#0A1145] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">directions_car</span>
              <span>Live Simulation View</span>
            </button>
            <button
              onClick={() => {
                setViewMode('congestion')
                if (!congestion && simId) {
                  fetchCongestion(simId)
                }
              }}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                viewMode === 'congestion'
                  ? 'bg-[#0A1145] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#0A1145]'
              }`}
            >
              <span className="material-symbols-outlined text-[15px]">traffic</span>
              <span>Road Congestion Analysis</span>
              {congestion && (
                <span className="w-2 h-2 rounded-full bg-[#10B981]"></span>
              )}
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {simId && (
            <button
              onClick={handleComputeCongestion}
              disabled={isLoadingCongestion}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-[#cbdbf5] bg-white hover:bg-[#eff4ff] text-[#0A1145] transition-colors flex items-center gap-1.5 disabled:opacity-50"
              title="Compute road-level congestion scores from telemetry"
            >
              <span className={`material-symbols-outlined text-[16px] ${isLoadingCongestion ? 'animate-spin' : ''}`}>
                {isLoadingCongestion ? 'refresh' : 'insights'}
              </span>
              <span>{isLoadingCongestion ? 'Analyzing...' : congestion ? 'Refresh Congestion' : 'Analyze Congestion'}</span>
            </button>
          )}
          {selectedSegmentId && (
            <button
              onClick={() => setSelectedSegmentId(null)}
              className="px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:text-red-600 bg-slate-50 hover:bg-red-50 border border-slate-200 rounded-md transition-colors"
            >
              Clear Selected Road
            </button>
          )}
        </div>
      </div>

      {/* AREA B: MAIN DOMINANT SIMULATION VIEWPORT (Real Geospatial Leaflet Map) */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col">
        {/* Map Canvas */}
        <div className="relative w-full h-[480px] bg-[#f8faff] overflow-hidden">
          <div ref={mapContainerRef} className="w-full h-full" />

          {/* Clean Corner Legend */}
          <div className="absolute top-4 right-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg p-2.5 shadow-xs text-xs flex flex-col gap-1.5 max-w-[210px]">
            {viewMode === 'congestion' ? (
              <>
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
                <div className="border-t border-slate-200 pt-1 mt-0.5 flex items-center justify-between text-[11px] text-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#94A3B8]"></span>
                    <span>Insufficient Data</span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400">&lt; 3 obs</span>
                </div>
              </>
            ) : (
              <>
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">
                  Traffic Conditions
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-700">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#138808]"></span>
                  <span>Flowing (&gt; 35 km/h)</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-700">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></span>
                  <span>Moderate (18 - 35 km/h)</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-700">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#DC2626]"></span>
                  <span>Congested (&lt; 18 km/h)</span>
                </div>
                <div className="border-t border-slate-200 pt-1 mt-0.5 flex items-center gap-2 text-[11px] text-slate-700">
                  <span className="w-2.5 h-2.5 rounded-xs bg-[#0A1145]"></span>
                  <span>Bus Transit</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-700">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#138808] border border-white shadow-xs"></span>
                  <span>Actuated Signal (Phase State)</span>
                </div>
              </>
            )}
          </div>

          {/* Corridor Network Label */}
          <div className="absolute top-4 left-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg px-3 py-1.5 shadow-xs text-xs">
            <span className="font-bold text-[#0A1145]">Corridor Network:</span>
            <span className="text-slate-600 font-mono text-[11px] ml-1">
              {simStatus?.edge_count ?? analysis.segments.length} Edges • {simStatus?.junction_count ?? analysis.road_network?.intersection_count ?? 0} Junctions • {simStatus?.signal_count ?? simStatus?.traffic_lights?.length ?? 0} Signals
            </span>
          </div>

          {/* Active Vehicles Counter */}
          <div className="absolute bottom-4 left-4 z-[500] bg-[#0A1145]/90 text-white backdrop-blur-xs rounded-lg px-3 py-1 shadow-xs text-xs font-mono font-semibold">
            {viewMode === 'congestion'
              ? `${congestion?.roads_analyzed ?? 0} Analyzed Roads`
              : `${vehicles.length} Active Vehicles`}
          </div>
        </div>

        {/* Integrated Bottom Playback Control Bar */}
        <div className="px-5 py-3 bg-white border-t border-[#cbdbf5] flex flex-wrap items-center justify-between gap-4">
          {/* Controls: Play/Pause, Step, & Reset */}
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
              title="Advance single step (2s)"
            >
              <span className="material-symbols-outlined text-[16px] text-slate-500">
                redo
              </span>
              <span>Step</span>
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-1 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors"
            >
              <span className="material-symbols-outlined text-[16px] text-slate-500">
                restart_alt
              </span>
              <span>Reset</span>
            </button>
          </div>

          {/* Timeline Readout & Progress Bar */}
          <div className="flex-1 max-w-md flex items-center gap-3">
            <span className="font-mono text-xs font-bold text-[#0A1145]">
              {formatTime(elapsed)}
            </span>
            <div className="flex-1 bg-[#eff4ff] h-2 rounded-full overflow-hidden border border-[#cbdbf5]">
              <div
                className="bg-[#FF9933] h-full rounded-full transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              ></div>
            </div>
            <span className="font-mono text-xs text-slate-500">{formatTime(duration)}</span>
          </div>

          {/* Speed Selector Pills */}
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

      {/* AREA C: COMPACT METRICS AND RESULTS (4 KPI Cards) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI Card 1: Average Speed */}
        <div className="bg-white border border-[#cbdbf5] rounded-xl p-4 shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500 text-xs mb-2">
            <span className="font-medium">Average Speed</span>
            <span className="material-symbols-outlined text-[#FF9933] text-[18px]">
              speed
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-[#0A1145]">
              {elapsed > 0 && metrics && metrics.avg_speed_kmh > 0
                ? metrics.avg_speed_kmh.toFixed(1)
                : '—'}
            </span>
            {elapsed > 0 && metrics && metrics.avg_speed_kmh > 0 && (
              <span className="text-xs text-slate-500 font-sans">km/h</span>
            )}
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            {elapsed > 0 && metrics?.variance_speed_pct != null ? (
              <span className={metrics.variance_speed_pct >= 0 ? 'text-[#138808]' : 'text-[#DC2626]'}>
                {metrics.variance_speed_pct >= 0 ? '↑ +' : '↓ '}
                {metrics.variance_speed_pct.toFixed(1)}% vs baseline
              </span>
            ) : (
              <span className="text-slate-400 font-normal">Awaiting simulation step</span>
            )}
          </div>
        </div>

        {/* KPI Card 2: Average Waiting Time */}
        <div className="bg-white border border-[#cbdbf5] rounded-xl p-4 shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500 text-xs mb-2">
            <span className="font-medium">Average Waiting Time</span>
            <span className="material-symbols-outlined text-[#DC2626] text-[18px]">
              timer
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-[#0A1145]">
              {elapsed > 0 && metrics && metrics.avg_waiting_time_s > 0
                ? metrics.avg_waiting_time_s.toFixed(1)
                : '—'}
            </span>
            {elapsed > 0 && metrics && metrics.avg_waiting_time_s > 0 && (
              <span className="text-xs text-slate-500 font-sans">s/veh</span>
            )}
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            {elapsed > 0 && metrics?.variance_waiting_pct != null ? (
              <span className={metrics.variance_waiting_pct <= 0 ? 'text-[#138808]' : 'text-[#DC2626]'}>
                {metrics.variance_waiting_pct < 0 ? '↓ ' : '↑ +'}
                {metrics.variance_waiting_pct.toFixed(1)}% delay
              </span>
            ) : (
              <span className="text-slate-400 font-normal">Awaiting simulation step</span>
            )}
          </div>
        </div>

        {/* KPI Card 3: Average Queue Length */}
        <div className="bg-white border border-[#cbdbf5] rounded-xl p-4 shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500 text-xs mb-2">
            <span className="font-medium">Average Queue Length</span>
            <span className="material-symbols-outlined text-[#F59E0B] text-[18px]">
              density_medium
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-[#0A1145]">
              {elapsed > 0 && metrics && metrics.avg_queue_length_m > 0
                ? metrics.avg_queue_length_m.toFixed(1)
                : '—'}
            </span>
            {elapsed > 0 && metrics && metrics.avg_queue_length_m > 0 && (
              <span className="text-xs text-slate-500 font-sans">m</span>
            )}
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            {elapsed > 0 && metrics?.variance_queue_pct != null ? (
              <span className={metrics.variance_queue_pct <= 0 ? 'text-[#138808]' : 'text-[#DC2626]'}>
                {metrics.variance_queue_pct < 0 ? '↓ ' : '↑ +'}
                {metrics.variance_queue_pct.toFixed(1)}% spillback
              </span>
            ) : (
              <span className="text-slate-400 font-normal">Awaiting simulation step</span>
            )}
          </div>
        </div>

        {/* KPI Card 4: Completed Vehicles */}
        <div className="bg-white border border-[#cbdbf5] rounded-xl p-4 shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500 text-xs mb-2">
            <span className="font-medium">Completed Vehicles</span>
            <span className="material-symbols-outlined text-[#138808] text-[18px]">
              check_circle
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-[#0A1145]">
              {elapsed > 0 && metrics ? metrics.completed_vehicles : '—'}
            </span>
            {elapsed > 0 && metrics && (
              <span className="text-xs text-slate-500 font-sans">vehs</span>
            )}
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            {elapsed > 0 && metrics?.variance_completed_pct != null ? (
              <span className={metrics.variance_completed_pct >= 0 ? 'text-[#138808]' : 'text-[#DC2626]'}>
                {metrics.variance_completed_pct >= 0 ? '↑ +' : '↓ '}
                {metrics.variance_completed_pct.toFixed(1)}% throughput
              </span>
            ) : (
              <span className="text-slate-400 font-normal">Awaiting simulation step</span>
            )}
          </div>
        </div>
      </div>

      {/* AREA D: SCENARIO RESULTS (BASELINE VS OPTIMIZED) */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between border-b border-[#e2e8f0] pb-3 mb-4 gap-2">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-[#0A1145]">Scenario Results</h2>
              {comparison?.comparison_status && (
                <span
                  className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${
                    comparison.comparison_status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : comparison.comparison_status === 'pending'
                        ? 'bg-slate-100 text-slate-600 border-slate-200'
                        : 'bg-amber-50 text-amber-700 border-amber-200'
                  }`}
                >
                  {comparison.comparison_status}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">
              {comparison?.baseline_strategy || 'Baseline (Fixed-Time)'} vs.{' '}
              {comparison?.optimized_strategy || 'Optimized (Adaptive Actuated)'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-slate-600 bg-[#eff4ff] border border-[#cbdbf5] px-2.5 py-1 rounded">
              Seed: 42 • {simStatus?.duration_seconds ?? 600}s Interval
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-[#f8faff] text-slate-600 border-b border-[#cbdbf5]">
                <th className="py-2.5 px-4 font-semibold">Metric</th>
                <th className="py-2.5 px-4 font-semibold">Baseline</th>
                <th className="py-2.5 px-4 font-semibold">Optimized</th>
                <th className="py-2.5 px-4 font-semibold">Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] font-mono text-xs">
              {comparison?.rows?.map((row, idx) => {
                const isPending =
                  row.variance.toLowerCase().includes('pending') ||
                  row.variance.toLowerCase().includes('insufficient')
                return (
                  <tr key={idx} className="hover:bg-[#f8f9ff]">
                    <td className="py-3 px-4 font-sans font-medium text-[#0A1145]">
                      {row.metric}
                    </td>
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
            'Simulation results evaluated using empirical telemetry across identical topology and demand.'}
        </div>
      </div>

      {/* AREA E: POST-SIMULATION ROAD-LEVEL CONGESTION ANALYSIS */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between border-b border-[#e2e8f0] pb-3 mb-4 gap-3">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="material-symbols-outlined text-[#0A1145] text-lg">
                traffic
              </span>
              <h2 className="text-sm font-bold text-[#0A1145]">
                Road-Level Congestion Analysis
              </h2>
              {congestion ? (
                <span
                  className={`text-[10px] font-semibold uppercase px-2.5 py-0.5 rounded-full border ${
                    congestion.engine_mode === 'native_sumo'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                      : 'bg-amber-50 text-amber-700 border-amber-300'
                  }`}
                >
                  {congestion.engine_mode === 'native_sumo'
                    ? 'Measured (Native SUMO TraCI)'
                    : 'Estimated (Kinematics Fallback)'}
                </span>
              ) : (
                <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded border bg-slate-100 text-slate-600 border-slate-200">
                  {elapsed >= duration ? 'Ready to Analyze' : 'Simulation Telemetry'}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Post-simulation multi-attribute congestion ranking aggregated from TraCI edge speeds, lane occupancy, and queue halting.
            </p>
          </div>

          <div className="flex items-center gap-2">
            {simId && (
              <button
                onClick={handleComputeCongestion}
                disabled={isLoadingCongestion}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-[#0A1145] text-white hover:bg-[#1e266d] transition-colors flex items-center gap-1.5 disabled:opacity-50 shadow-xs"
              >
                <span className={`material-symbols-outlined text-[15px] ${isLoadingCongestion ? 'animate-spin' : ''}`}>
                  {isLoadingCongestion ? 'refresh' : 'analytics'}
                </span>
                <span>{isLoadingCongestion ? 'Analyzing Telemetry...' : congestion ? 'Recompute Analysis' : 'Compute Congestion'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Summary Statistics Counters */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-lg p-3">
            <span className="text-[11px] text-slate-500 font-medium">Total Network Roads</span>
            <div className="text-xl font-bold font-mono text-[#0A1145] mt-0.5">
              {congestion?.total_roads ?? analysis.segments?.length ?? 0}
            </div>
          </div>
          <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-lg p-3">
            <span className="text-[11px] text-slate-500 font-medium">Roads Analyzed</span>
            <div className="text-xl font-bold font-mono text-emerald-700 mt-0.5">
              {congestion?.roads_analyzed ?? 0}
            </div>
          </div>
          <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-lg p-3">
            <span className="text-[11px] text-slate-500 font-medium">Insufficient Samples</span>
            <div className="text-xl font-bold font-mono text-slate-500 mt-0.5">
              {congestion?.roads_insufficient ?? analysis.segments?.length ?? 0}
            </div>
          </div>
          <div className="bg-[#f8faff] border border-[#cbdbf5] rounded-lg p-3">
            <span className="text-[11px] text-slate-500 font-medium">Top Congested Segment</span>
            <div className="text-sm font-bold font-mono text-red-600 mt-1 truncate" title={congestion?.top_congested?.[0]?.road_name}>
              {congestion?.top_congested?.[0]?.road_name || 'None identified'}
            </div>
          </div>
        </div>

        {/* Top-5 Most Congested Roads Table */}
        {congestion && congestion.top_congested.length > 0 ? (
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
                  <th className="py-2.5 px-3 font-semibold">Halting</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0] text-xs">
                {congestion.top_congested.map((road, idx) => {
                  const isSelected = selectedSegmentId === road.segment_id
                  const scorePct = Math.round(road.congestion_score * 100)

                  const severityBadgeClass =
                    road.severity === 'severe'
                      ? 'bg-rose-100 text-rose-800 border-rose-300'
                      : road.severity === 'high'
                        ? 'bg-red-50 text-red-700 border-red-200'
                        : road.severity === 'moderate'
                          ? 'bg-amber-50 text-amber-700 border-amber-200'
                          : road.severity === 'low'
                            ? 'bg-lime-50 text-lime-700 border-lime-200'
                            : road.severity === 'free_flow'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-slate-100 text-slate-600 border-slate-200'

                  return (
                    <tr
                      key={road.segment_id}
                      onClick={() => handleFocusSegment(road.segment_id)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-indigo-50/70 font-medium'
                          : 'hover:bg-[#f8f9ff]'
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
                              className={`h-full rounded-full ${
                                scorePct >= 80
                                  ? 'bg-[#7F1D1D]'
                                  : scorePct >= 60
                                    ? 'bg-[#EF4444]'
                                    : scorePct >= 40
                                      ? 'bg-[#F59E0B]'
                                      : scorePct >= 20
                                        ? 'bg-[#84CC16]'
                                        : 'bg-[#10B981]'
                              }`}
                              style={{ width: `${scorePct}%` }}
                            ></div>
                          </div>
                          <span className="font-mono font-bold text-[#0A1145] text-xs">
                            {scorePct}%
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold border capitalize ${severityBadgeClass}`}>
                          {road.severity.replace('_', ' ')}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono">
                        <span className="font-semibold text-[#0A1145]">{road.avg_speed_kmh.toFixed(1)}</span>
                        <span className="text-slate-400 text-[10px]"> / {road.ref_speed_kmh} km/h</span>
                      </td>
                      <td className="py-3 px-3 font-mono text-slate-700">
                        {road.avg_occupancy_pct.toFixed(1)}%
                      </td>
                      <td className="py-3 px-3 font-mono text-slate-700">
                        {road.avg_halting.toFixed(1)} veh
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleFocusSegment(road.segment_id)
                          }}
                          className={`px-2.5 py-1 text-[11px] font-semibold rounded border transition-colors ${
                            isSelected
                              ? 'bg-indigo-600 text-white border-indigo-700'
                              : 'bg-white hover:bg-slate-100 text-[#0A1145] border-[#cbdbf5]'
                          }`}
                        >
                          {isSelected ? 'Focused' : 'Locate'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 px-4 text-center bg-[#f8faff] rounded-lg border border-dashed border-[#cbdbf5] flex flex-col items-center justify-center">
            <span className="material-symbols-outlined text-slate-400 text-3xl mb-1">
              hourglass_empty
            </span>
            <div className="text-xs font-semibold text-slate-600">
              No road congestion telemetry aggregated yet
            </div>
            <p className="text-[11px] text-slate-400 max-w-md mt-0.5">
              Run or step the simulation to collect vehicle speeds, lane occupancy, and waiting queues across network edges, then click &ldquo;Compute Congestion&rdquo;.
            </p>
            {simId && (
              <button
                onClick={handleComputeCongestion}
                disabled={isLoadingCongestion}
                className="mt-3 px-3 py-1.5 text-xs font-semibold rounded-lg bg-[#0A1145] text-white hover:bg-[#1e266d] transition-colors disabled:opacity-50"
              >
                {isLoadingCongestion ? 'Analyzing...' : 'Analyze Available Telemetry'}
              </button>
            )}
          </div>
        )}

        {/* Methodology & Formula Disclosure */}
        <div className="mt-4 pt-3 border-t border-[#e2e8f0] text-[11px] text-slate-500 flex flex-col gap-1.5 bg-[#f8faff] p-3 rounded-lg border border-[#e2e8f0]">
          <div className="font-semibold text-slate-700 flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[15px] text-[#0A1145]">
              calculate
            </span>
            <span>Mathematical Congestion Scoring Methodology:</span>
          </div>
          <div className="font-mono text-[10px] text-slate-700 bg-white p-2 rounded border border-[#cbdbf5]">
            Congestion Score = 0.5 × (1 - (Observed Mean Speed / Speed Limit)) + 0.3 × (Lane Occupancy / 100) + 0.2 × (Halting Queue Ratio)
          </div>
          <div className="text-slate-500 text-[10px]">
            {congestion?.methodology_notes ||
              'Scoring weights: 50% speed degradation relative to segment limit, 30% lane occupancy percentage, and 20% relative queue halting. Minimum 3 observation samples required for native measurement classification.'}
          </div>
        </div>
      </div>
    </div>
  )
}
