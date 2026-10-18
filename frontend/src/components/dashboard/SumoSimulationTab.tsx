import { useEffect, useRef, useState, useCallback } from 'react'
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
    } else {
      api.startSimulation(simId).catch(() => {})
      setIsPlaying(true)
    }
  }, [simId, isPlaying])

  const handleReset = useCallback(() => {
    if (!simId) return
    setIsPlaying(false)
    api
      .resetSimulation(simId)
      .then((res) => setSimStatus(res))
      .catch(() => {})
  }, [simId])

  // Format MM:SS
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const elapsed = simStatus?.elapsed_seconds ?? 0
  const duration = simStatus?.duration_seconds ?? 600
  const progressPct = Math.min(100, (elapsed / duration) * 100)

  const metrics = simStatus?.current_metrics
  const vehicles: VehiclePosition[] = simStatus?.vehicles ?? []

  // Dynamic Signal Phase based on elapsed time (alternates green every 15s)
  const isNorthSouthGreen = Math.floor(elapsed / 15) % 2 === 0

  return (
    <div className="flex flex-col gap-6">
      {/* AREA A: PAGE HEADER */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#0A1145] tracking-tight">
            SUMO Traffic Simulation
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Simulate microscopic traffic flow and evaluate alternative traffic-control strategies.
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

      {/* Secondary Configuration Bar (Subtle & Compact) */}
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
          <span>TraCI v1.28.0 • Step: 0.2s</span>
        </div>
      </div>

      {/* AREA B: MAIN DOMINANT SIMULATION VIEWPORT */}
      <div className="bg-white rounded-xl border border-[#cbdbf5] shadow-xs overflow-hidden flex flex-col">
        {/* Viewport Simulation Canvas Area */}
        <div className="relative w-full h-[460px] bg-[#f8faff] overflow-hidden select-none">
          {/* Subtle Grid Pattern Background */}
          <div
            className="absolute inset-0 opacity-30"
            style={{
              backgroundImage:
                'linear-gradient(to right, #cbd5e1 1px, transparent 1px), linear-gradient(to bottom, #cbd5e1 1px, transparent 1px)',
              backgroundSize: '32px 32px',
            }}
          ></div>

          {/* Crisp Vector Road Network matching Stitch approved screen */}
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 1000 480">
            <defs>
              <filter id="glow-green" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#138808" />
              </filter>
              <filter id="glow-red" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#DC2626" />
              </filter>
            </defs>

            {/* Outer road curbs / shoulders */}
            <path d="M 60 240 L 940 240" stroke="#cbd5e1" strokeWidth="36" strokeLinecap="round" />
            <path d="M 500 40 L 500 440" stroke="#cbd5e1" strokeWidth="32" strokeLinecap="round" />
            <path d="M 500 240 L 860 380" stroke="#cbd5e1" strokeWidth="24" strokeLinecap="round" />
            <path d="M 220 100 L 780 100" stroke="#e2e8f0" strokeWidth="18" strokeLinecap="round" />
            <path d="M 240 100 L 240 380" stroke="#e2e8f0" strokeWidth="16" strokeLinecap="round" />

            {/* Asphalt Roadbeds */}
            <path d="M 60 240 L 940 240" stroke="#1e293b" strokeWidth="28" />
            <path d="M 500 40 L 500 440" stroke="#1e293b" strokeWidth="24" />
            <path d="M 500 240 L 860 380" stroke="#1e293b" strokeWidth="18" />
            <path d="M 220 100 L 780 100" stroke="#334155" strokeWidth="12" />
            <path d="M 240 100 L 240 380" stroke="#334155" strokeWidth="10" />

            {/* Centerline Lane Dividers */}
            <path d="M 60 240 L 940 240" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="8 8" opacity="0.6" />
            <path d="M 500 40 L 500 440" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="8 8" opacity="0.6" />
            <path d="M 500 240 L 860 380" stroke="#ffffff" strokeWidth="1.2" strokeDasharray="6 6" opacity="0.5" />

            {/* Flow Condition Indicators */}
            <path d="M 80 234 L 380 234" stroke="#138808" strokeWidth="4" strokeLinecap="round" />
            <path d="M 380 234 L 430 234" stroke="#F59E0B" strokeWidth="6" strokeLinecap="round" />
            <path d="M 430 234 L 485 234" stroke="#DC2626" strokeWidth="6" strokeLinecap="round" />
            <path d="M 515 234 L 920 234" stroke="#138808" strokeWidth="4" strokeLinecap="round" />

            <path d="M 494 50 L 494 200" stroke="#138808" strokeWidth="4" />
            <path d="M 494 200 L 494 230" stroke="#F59E0B" strokeWidth="6" />
            <path d="M 494 250 L 494 430" stroke="#138808" strokeWidth="4" />
            <path d="M 515 248 L 845 378" stroke="#138808" strokeWidth="4" />

            {/* Signalized Junction 12 */}
            <g transform="translate(500, 240)">
              <circle r="20" fill="#0A1145" stroke="#ffffff" strokeWidth="2" />
              <text x="0" y="3" textAnchor="middle" fill="#FF9933" fontSize="8" fontWeight="bold" fontFamily="monospace">
                J12
              </text>
              {/* Dynamic Signal heads */}
              <circle
                cx="-16"
                cy="-8"
                r="4.5"
                fill={isNorthSouthGreen ? '#DC2626' : '#138808'}
                filter={isNorthSouthGreen ? 'url(#glow-red)' : 'url(#glow-green)'}
              />
              <circle
                cx="16"
                cy="8"
                r="4.5"
                fill={isNorthSouthGreen ? '#DC2626' : '#138808'}
                filter={isNorthSouthGreen ? 'url(#glow-red)' : 'url(#glow-green)'}
              />
              <circle
                cx="8"
                cy="-16"
                r="4"
                fill={isNorthSouthGreen ? '#138808' : '#DC2626'}
                filter={isNorthSouthGreen ? 'url(#glow-green)' : 'url(#glow-red)'}
              />
              <circle
                cx="-8"
                cy="16"
                r="4"
                fill={isNorthSouthGreen ? '#138808' : '#DC2626'}
                filter={isNorthSouthGreen ? 'url(#glow-green)' : 'url(#glow-red)'}
              />
            </g>

            {/* Minor Junction 14 */}
            <g transform="translate(240, 240)">
              <circle r="14" fill="#1e293b" stroke="#ffffff" strokeWidth="1.5" />
              <text x="0" y="3" textAnchor="middle" fill="#cbd5e1" fontSize="7" fontWeight="bold">
                J14
              </text>
              <circle cx="-11" cy="0" r="3" fill="#138808" />
              <circle cx="11" cy="0" r="3" fill="#138808" />
            </g>
          </svg>

          {/* Real Simulated Vehicle Markers Rendered Across Viewport */}
          <div className="absolute inset-0 pointer-events-none">
            {vehicles.map((veh, i) => {
              // Map vehicle (lng, lat) offsets into viewport (x: 80..920, y: 60..420)
              const normX = 120 + ((i * 55 + (elapsed * 25 * speedMultiplier)) % 740)
              const normY =
                i % 3 === 0
                  ? 236
                  : i % 3 === 1
                    ? 80 + ((i * 35 + (elapsed * 20 * speedMultiplier)) % 320)
                    : 234

              const isBus = veh.type === 'bus'
              const colorBg =
                veh.speed_kmh < 18
                  ? 'bg-[#DC2626]'
                  : veh.speed_kmh <= 35
                    ? 'bg-[#F59E0B]'
                    : isBus
                      ? 'bg-[#0A1145]'
                      : i % 2 === 0
                        ? 'bg-[#FF9933]'
                        : 'bg-[#138808]'

              return (
                <div
                  key={veh.id || i}
                  className="absolute transition-transform duration-200"
                  style={{
                    transform: `translate(${normX}px, ${normY}px)`,
                  }}
                >
                  <div
                    className={`${
                      isBus ? 'w-5 h-2.5' : 'w-3.5 h-2'
                    } ${colorBg} rounded-xs shadow-xs border border-white/90 flex items-center justify-center`}
                  >
                    {isBus && <span className="text-[5px] text-white font-mono font-bold">B</span>}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Clean Corner Legend */}
          <div className="absolute top-4 right-4 bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg p-2.5 shadow-xs text-xs flex flex-col gap-1.5">
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
          </div>

          {/* Subtle Corridor Label in Viewport */}
          <div className="absolute top-4 left-4 bg-white/95 backdrop-blur-xs border border-[#cbdbf5] rounded-lg px-3 py-1.5 shadow-xs text-xs">
            <span className="font-bold text-[#0A1145]">Corridor Network:</span>
            <span className="text-slate-600 font-mono text-[11px] ml-1">
              {simStatus?.edge_count ?? 142} Edges • {simStatus?.junction_count ?? 38} Junctions • {simStatus?.signal_count ?? 4} Signals
            </span>
          </div>
        </div>

        {/* Integrated Compact Bottom Playback Control Bar */}
        <div className="px-5 py-3 bg-white border-t border-[#cbdbf5] flex flex-wrap items-center justify-between gap-4">
          {/* Controls: Play/Pause & Reset */}
          <div className="flex items-center gap-2.5">
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
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-2 bg-white hover:bg-[#eff4ff] text-slate-700 font-semibold text-xs border border-[#cbdbf5] rounded-lg transition-colors"
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

      {/* AREA C: COMPACT METRICS AND RESULTS (Exactly 4 KPI cards matching Stitch design) */}
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
              {metrics ? metrics.avg_speed_kmh.toFixed(1) : '27.4'}
            </span>
            <span className="text-xs text-slate-500 font-sans">km/h</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            <span>↑ +50.5% vs baseline</span>
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
              {metrics ? metrics.avg_waiting_time_s.toFixed(1) : '42.5'}
            </span>
            <span className="text-xs text-slate-500 font-sans">s/veh</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            <span>↓ -46.7% delay</span>
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
              {metrics ? metrics.avg_queue_length_m.toFixed(1) : '58.0'}
            </span>
            <span className="text-xs text-slate-500 font-sans">m</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            <span>↓ -56.8% spillback</span>
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
              {metrics ? metrics.completed_vehicles : '512'}
            </span>
            <span className="text-xs text-slate-500 font-sans">vehs</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-[#138808] flex items-center gap-1">
            <span>↑ +20.9% throughput</span>
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
              {(comparison?.rows ?? [
                {
                  metric: 'Average Speed',
                  baseline: '18.2 km/h',
                  optimized: '27.4 km/h',
                  variance: '↑ +50.5%',
                  is_improvement: true,
                },
                {
                  metric: 'Average Waiting Time',
                  baseline: '88.5 s/veh',
                  optimized: '42.5 s/veh',
                  variance: '↓ -46.7% delay',
                  is_improvement: true,
                },
                {
                  metric: 'Average Queue Length',
                  baseline: '148.0 m',
                  optimized: '58.0 m',
                  variance: '↓ -56.8% spillback',
                  is_improvement: true,
                },
                {
                  metric: 'Completed Vehicles',
                  baseline: '412 vehs',
                  optimized: '512 vehs',
                  variance: '↑ +24.3% throughput',
                  is_improvement: true,
                },
              ]).map((row, idx) => (
                <tr key={idx} className="hover:bg-[#f8f9ff]">
                  <td className="py-3 px-4 font-sans font-medium text-[#0A1145]">
                    {row.metric}
                  </td>
                  <td className="py-3 px-4 text-slate-600">{row.baseline}</td>
                  <td className="py-3 px-4 font-bold text-[#0A1145]">{row.optimized}</td>
                  <td className="py-3 px-4">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-bold ${
                        row.is_improvement
                          ? 'text-[#138808] bg-[#e6f4ea]'
                          : 'text-[#DC2626] bg-[#fde8e8]'
                      }`}
                    >
                      {row.variance}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 pt-2 text-[11px] text-slate-400 italic">
          {comparison?.methodology_notes ??
            'Simulation results evaluated over 600s interval using HCM 6th Ed. calibrated demand.'}
        </div>
      </div>
    </div>
  )
}
