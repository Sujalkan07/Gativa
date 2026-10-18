import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, GativaApiError } from '../../api/client'
import type {
  AnalysisResult,
  SimulationStatusResponse,
  ScenarioComparisonResult,
  VehiclePosition,
} from '../../types/api'

interface SumoSimulationTabProps {
  analysis: AnalysisResult
}

export default function SumoSimulationTab({ analysis }: SumoSimulationTabProps) {
  const [simId, setSimId] = useState<string | null>(null)
  const [simStatus, setSimStatus] = useState<SimulationStatusResponse | null>(null)
  const [comparison, setComparison] = useState<ScenarioComparisonResult | null>(null)
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(2)
  const [isPlaying, setIsPlaying] = useState<boolean>(false)
  const [isPreparing, setIsPreparing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const timerRef = useRef<number | null>(null)
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const segmentsGroupRef = useRef<L.LayerGroup | null>(null)
  const vehiclesGroupRef = useRef<L.LayerGroup | null>(null)
  const signalsGroupRef = useRef<L.LayerGroup | null>(null)

  const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY

  // 1. Prepare Simulation on Mount or when analysisId changes
  useEffect(() => {
    let isMounted = true
    setIsPreparing(true)
    setError(null)

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
          const msg =
            err instanceof GativaApiError
              ? err.message
              : 'Failed to initialize SUMO simulation.'
          setError(msg)
          setIsPreparing(false)
        }
      })

    return () => {
      isMounted = false
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [analysis.analysis_id])

  // 2. Fetch Comparison Results once prepared
  useEffect(() => {
    if (!simId) return
    api
      .getScenarioComparison(simId)
      .then((data) => setComparison(data))
      .catch((err) => console.warn('Could not fetch scenario comparison:', err))
  }, [simId])

  // 3. Step Loop when isPlaying is true
  useEffect(() => {
    if (!isPlaying || !simId) {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
      return
    }

    const intervalMs = Math.max(80, Math.floor(400 / speedMultiplier))
    timerRef.current = setInterval(() => {
      api
        .stepSimulation(simId, speedMultiplier)
        .then((res) => {
          setSimStatus(res)
          if (res.state === 'completed') {
            setIsPlaying(false)
            api.getScenarioComparison(simId).then(setComparison).catch(() => {})
          }
        })
        .catch((err) => {
          console.error('Simulation step error:', err)
          setIsPlaying(false)
        })
    }, intervalMs)

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [isPlaying, simId, speedMultiplier])

  // Handlers
  const handleTogglePlay = useCallback(() => {
    if (!simId) return
    if (isPlaying) {
      api.pauseSimulation(simId).catch(() => {})
      setIsPlaying(false)
      api.getScenarioComparison(simId).then(setComparison).catch(() => {})
    } else {
      api.startSimulation(simId).catch(() => {})
      setIsPlaying(true)
    }
  }, [simId, isPlaying])

  const handleStepOnce = useCallback(() => {
    if (!simId) return
    api
      .stepSimulation(simId, 2)
      .then((res) => {
        setSimStatus(res)
        api.getScenarioComparison(simId).then(setComparison).catch(() => {})
      })
      .catch((err) => console.error('Step error:', err))
  }, [simId])

  const handleReset = useCallback(() => {
    if (!simId) return
    setIsPlaying(false)
    api
      .resetSimulation(simId)
      .then((res) => {
        setSimStatus(res)
        api.getScenarioComparison(simId).then(setComparison).catch(() => {})
      })
      .catch(() => {})
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
        segGroup.addLayer(line)
      })
    }

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [analysis.polygon, analysis.segments, TOMTOM_KEY])

  // 5. Update vehicle positions and signals dynamically
  const elapsed = simStatus?.elapsed_seconds ?? 0
  const duration = simStatus?.duration_seconds ?? 600
  const progressPct = Math.min(100, (elapsed / duration) * 100)
  const metrics = simStatus?.current_metrics
  const vehicles: VehiclePosition[] = useMemo(
    () => simStatus?.vehicles ?? [],
    [simStatus?.vehicles],
  )
  const isNorthSouthGreen = Math.floor(elapsed / 15) % 2 === 0

  useEffect(() => {
    const vehGroup = vehiclesGroupRef.current
    if (!vehGroup) return

    vehGroup.clearLayers()

    vehicles.forEach((veh) => {
      if (veh.lat && veh.lng && !isNaN(veh.lat) && !isNaN(veh.lng)) {
        const isBus = veh.type === 'bus'
        const speedColor =
          veh.speed_kmh < 18
            ? '#DC2626'
            : veh.speed_kmh <= 35
              ? '#F59E0B'
              : isBus
                ? '#0A1145'
                : '#138808'

        const icon = L.divIcon({
          className: 'sumo-vehicle-icon',
          iconSize: [22, 12],
          iconAnchor: [11, 6],
          html: `<div style="transform: rotate(${veh.angle}deg); width: ${isBus ? '22px' : '16px'}; height: ${isBus ? '10px' : '8px'}; background-color: ${speedColor}; border: 1.5px solid #ffffff; border-radius: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;">
            ${isBus ? '<span style="font-size: 5px; color: #ffffff; font-weight: bold; font-family: monospace;">B</span>' : ''}
          </div>`,
        })

        const marker = L.marker([veh.lat, veh.lng], { icon })
        marker.bindTooltip(
          `<div class="text-[11px] font-mono"><b>${veh.id}</b> (${veh.type})<br/>Speed: ${veh.speed_kmh.toFixed(1)} km/h<br/>Wait: ${veh.waiting_time_s.toFixed(1)}s</div>`,
          { direction: 'top', offset: [0, -6] },
        )
        vehGroup.addLayer(marker)
      }
    })
  }, [vehicles])

  // Update signal indicators
  useEffect(() => {
    const sigGroup = signalsGroupRef.current
    if (!sigGroup) return

    sigGroup.clearLayers()

    // Mark key bottleneck or intersection nodes as traffic signals
    if (analysis.bottlenecks?.length) {
      analysis.bottlenecks.slice(0, 3).forEach((b, idx) => {
        if (b.lat && b.lng) {
          const sigIcon = L.divIcon({
            className: 'sumo-signal-icon',
            iconSize: [26, 26],
            iconAnchor: [13, 13],
            html: `<div style="width: 26px; height: 26px; border-radius: 50%; background: #0A1145; border: 2px solid #ffffff; box-shadow: 0 2px 5px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; position: relative;">
              <span style="font-size: 8px; color: #FF9933; font-weight: bold; font-family: monospace;">TL${idx + 1}</span>
              <span style="position: absolute; top: -2px; right: -2px; width: 8px; height: 8px; border-radius: 50%; background: ${isNorthSouthGreen ? '#138808' : '#DC2626'}; border: 1.5px solid #ffffff;"></span>
            </div>`,
          })
          const sigMarker = L.marker([b.lat, b.lng], { icon: sigIcon })
          sigMarker.bindTooltip(
            `<div class="text-[11px] font-sans"><b>Traffic Signal TL${idx + 1}</b><br/>Phase: ${isNorthSouthGreen ? 'North-South Green' : 'East-West Green'}</div>`,
          )
          sigGroup.addLayer(sigMarker)
        }
      })
    }
  }, [analysis.bottlenecks, isNorthSouthGreen])

  // Format MM:SS
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="flex flex-col gap-6">
      {/* AREA A: PAGE HEADER */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#0A1145] tracking-tight">
            SUMO Traffic Simulation
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Microscopic traffic simulation powered by Eclipse SUMO &amp; TraCI with live telemetry.
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
          <span className="w-2 h-2 rounded-full bg-[#138808]"></span>
          <span>TraCI Engine • Step: 0.2s</span>
        </div>
      </div>

      {/* AREA B: MAIN DOMINANT SIMULATION VIEWPORT (Real Geospatial Leaflet Map) */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col">
        {/* Map Canvas */}
        <div className="relative w-full h-[480px] bg-[#f8faff] overflow-hidden">
          <div ref={mapContainerRef} className="w-full h-full" />

          {/* Clean Corner Legend */}
          <div className="absolute top-4 right-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg p-2.5 shadow-xs text-xs flex flex-col gap-1.5">
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
          </div>

          {/* Corridor Network Label */}
          <div className="absolute top-4 left-4 z-[500] bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg px-3 py-1.5 shadow-xs text-xs">
            <span className="font-bold text-[#0A1145]">Corridor Network:</span>
            <span className="text-slate-600 font-mono text-[11px] ml-1">
              {simStatus?.edge_count ?? analysis.segments.length} Edges • {simStatus?.junction_count ?? analysis.road_network?.intersection_count ?? 0} Junctions • {simStatus?.signal_count ?? 1} Signals
            </span>
          </div>

          {/* Active Vehicles Counter */}
          <div className="absolute bottom-4 left-4 z-[500] bg-[#0A1145]/90 text-white backdrop-blur-xs rounded-lg px-3 py-1 shadow-xs text-xs font-mono font-semibold">
            {vehicles.length} Active Vehicles
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
              <span>
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
              <span>
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
              <span>
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
              <span>
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
        <div className="flex items-center justify-between border-b border-[#e2e8f0] pb-3 mb-4">
          <div>
            <h2 className="text-sm font-bold text-[#0A1145]">Scenario Results</h2>
            <p className="text-xs text-slate-500">
              Baseline (Fixed-Time) vs. Optimized (Adaptive Actuated) Comparison
            </p>
          </div>
          <span className="text-[11px] font-semibold text-slate-600 bg-[#eff4ff] border border-[#cbdbf5] px-2.5 py-1 rounded">
            600s Simulation Interval
          </span>
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
                const isPending = row.variance.toLowerCase().includes('pending')
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
            'Simulation results evaluated over 600s interval using Highway Capacity Manual (HCM 6th Ed.) calibrated demand.'}
        </div>
      </div>
    </div>
  )
}
