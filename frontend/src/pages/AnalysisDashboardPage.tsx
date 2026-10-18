import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import AnalysisOverviewTab from '../components/dashboard/AnalysisOverviewTab'
import TrafficFlowTab from '../components/dashboard/TrafficFlowTab'
import RecommendationsTab from '../components/dashboard/RecommendationsTab'
import SumoSimulationTab from '../components/dashboard/SumoSimulationTab'
import { api, GativaApiError } from '../api/client'
import type {
  AnalysisResult,
  TrafficFlowResult,
  RecommendationsResult,
} from '../types/api'

type TabType = 'analysis' | 'flow' | 'recommendations' | 'simulation'

export default function AnalysisDashboardPage() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const navigate = useNavigate()

  const [currentTab, setCurrentTab] = useState<TabType>('analysis')
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [trafficData, setTrafficData] = useState<TrafficFlowResult | null>(null)
  const [recommendationsData, setRecommendationsData] = useState<RecommendationsResult | null>(null)

  const [isLoadingAnalysis, setIsLoadingAnalysis] = useState(true)
  const [isLoadingTraffic, setIsLoadingTraffic] = useState(false)
  const [isLoadingRecs, setIsLoadingRecs] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 1. Fetch analysis overview, traffic flow, and recommendations concurrently
  useEffect(() => {
    if (!analysisId) {
      navigate('/')
      return
    }

    let isMounted = true
    setIsLoadingAnalysis(true)
    setError(null)

    api
      .getAnalysis(analysisId)
      .then((data) => {
        if (isMounted) {
          setAnalysis(data)
          setIsLoadingAnalysis(false)
        }
      })
      .catch((err) => {
        if (isMounted) {
          const msg =
            err instanceof GativaApiError
              ? err.message
              : 'Failed to retrieve analysis. Please try again.'
          setError(msg)
          setIsLoadingAnalysis(false)
        }
      })

    // Pre-fetch recommendations for instant map solution markers
    setIsLoadingRecs(true)
    api
      .getRecommendations(analysisId)
      .then((data) => {
        if (isMounted) {
          setRecommendationsData(data)
          setIsLoadingRecs(false)
        }
      })
      .catch((err) => {
        console.warn('Could not load recommendations:', err)
        if (isMounted) setIsLoadingRecs(false)
      })

    // Pre-fetch traffic flow for instant telemetry & LOS gradient
    setIsLoadingTraffic(true)
    api
      .getTrafficFlow(analysisId)
      .then((data) => {
        if (isMounted) {
          setTrafficData(data)
          setIsLoadingTraffic(false)
        }
      })
      .catch((err) => {
        console.warn('Could not load traffic flow:', err)
        if (isMounted) setIsLoadingTraffic(false)
      })

    return () => {
      isMounted = false
    }
  }, [analysisId, navigate])

  // Export GeoJSON Shapefile
  const handleExport = async () => {
    if (!analysisId) return
    setIsExporting(true)
    try {
      const blob = await api.exportGeoJSON(analysisId)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `gativa_analysis_${analysisId.substring(0, 8)}.geojson`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setIsExporting(false)
    }
  }

  const recsCount =
    recommendationsData?.recommendations?.length ??
    analysis?.bottlenecks?.length ??
    3

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-surface)]">
      {/* Top Fixed Header with Gativa Logo */}
      <Header analysisId={analysisId} />

      <main className="w-full pt-14 bg-[var(--color-surface)] min-h-screen flex flex-col">
        {/* Sub-Header Area Identification Banner */}
        <div className="w-full bg-[var(--color-surface-container-lowest)] px-[var(--spacing-margin)] py-[var(--spacing-space-md)] shadow-xs border-b border-[var(--color-surface-container-high)]">
          <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-[var(--spacing-space-md)]">
            <div className="flex items-center gap-[var(--spacing-space-md)]">
              <div className="w-10 h-10 rounded-lg bg-[var(--color-surface-container)] flex items-center justify-center text-[var(--color-primary-container)]">
                <span className="material-symbols-outlined text-2xl">
                  share_location
                </span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-secondary)]">
                    Selected Spatial Boundary
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-full font-mono text-[10px] font-bold ${
                      analysis?.storage_mode === 'mongodb'
                        ? 'bg-[var(--color-tertiary-fixed)] text-[var(--color-on-tertiary-fixed)]'
                        : 'bg-[var(--color-primary-fixed)] text-[var(--color-on-primary-fixed)]'
                    }`}
                  >
                    {analysis?.storage_mode === 'mongodb'
                      ? 'MongoDB Persistent'
                      : 'Session Cache (In-Memory Fallback)'}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <h1 className="text-xl font-bold text-[var(--color-on-surface)]">
                    {analysis?.area_name || 'Corridor Analysis Area'}
                  </h1>
                  <span className="font-mono text-xs text-[var(--color-secondary)] bg-[var(--color-surface-container-high)] px-2 py-0.5 rounded">
                    {analysis ? `${analysis.area_km2.toFixed(2)} km²` : '—'}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleExport}
                disabled={isExporting || !analysis}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--color-surface-container)] text-[var(--color-on-surface)] text-xs font-semibold hover:bg-[var(--color-surface-container-high)] transition-colors disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[16px]">
                  file_download
                </span>
                <span>{isExporting ? 'Exporting...' : 'Export GIS GeoJSON'}</span>
              </button>
              <button
                onClick={() => navigate('/')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)] text-xs font-bold hover:bg-[var(--color-primary-fixed)] transition-colors shadow-xs"
              >
                <span className="material-symbols-outlined text-[18px]">
                  edit_location_alt
                </span>
                <span>Change Area</span>
              </button>
            </div>
          </div>
        </div>

        {/* Primary Tab Navigation Bar */}
        <div className="w-full bg-[var(--color-surface-container-lowest)] shadow-xs border-b border-[var(--color-surface-container-high)]">
          <div className="max-w-7xl mx-auto px-[var(--spacing-margin)] flex items-center justify-between">
            <div className="flex items-center space-x-1" id="dashboard-tabs">
              {/* Tab 1: Analysis Overview */}
              <button
                onClick={() => setCurrentTab('analysis')}
                className={`relative px-6 py-3.5 text-sm font-semibold flex items-center gap-2 transition-colors ${
                  currentTab === 'analysis'
                    ? 'text-[var(--color-on-surface)]'
                    : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[18px] ${
                    currentTab === 'analysis' ? 'text-[var(--color-primary-container)]' : ''
                  }`}
                >
                  analytics
                </span>
                <span>Analysis Overview</span>
                {currentTab === 'analysis' && (
                  <span className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--color-primary-container)] rounded-t"></span>
                )}
              </button>

              {/* Tab 2: Traffic Flow */}
              <button
                onClick={() => setCurrentTab('flow')}
                className={`relative px-6 py-3.5 text-sm font-semibold flex items-center gap-2 transition-colors ${
                  currentTab === 'flow'
                    ? 'text-[var(--color-on-surface)]'
                    : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[18px] ${
                    currentTab === 'flow' ? 'text-[var(--color-primary)]' : ''
                  }`}
                >
                  traffic
                </span>
                <span>Traffic Flow & LOS</span>
                {currentTab === 'flow' && (
                  <span className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--color-primary-container)] rounded-t"></span>
                )}
              </button>

              {/* Tab 3: Recommendations */}
              <button
                onClick={() => setCurrentTab('recommendations')}
                className={`relative px-6 py-3.5 text-sm font-semibold flex items-center gap-2 transition-colors ${
                  currentTab === 'recommendations'
                    ? 'text-[var(--color-on-surface)]'
                    : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[18px] ${
                    currentTab === 'recommendations' ? 'text-[var(--color-primary-container)]' : ''
                  }`}
                >
                  lightbulb
                </span>
                <span>Recommendations</span>
                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)] text-[10px] font-mono font-bold">
                  {recsCount}
                </span>
                {currentTab === 'recommendations' && (
                  <span className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--color-primary-container)] rounded-t"></span>
                )}
              </button>

              {/* Tab 4: SUMO Simulation */}
              <button
                onClick={() => setCurrentTab('simulation')}
                className={`relative px-6 py-3.5 text-sm font-semibold flex items-center gap-2 transition-colors ${
                  currentTab === 'simulation'
                    ? 'text-[var(--color-on-surface)]'
                    : 'text-[var(--color-secondary)] hover:text-[var(--color-on-surface)]'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[18px] ${
                    currentTab === 'simulation' ? 'text-[var(--color-primary-container)]' : ''
                  }`}
                >
                  alt_route
                </span>
                <span>SUMO Simulation</span>
                {currentTab === 'simulation' && (
                  <span className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--color-primary-container)] rounded-t"></span>
                )}
              </button>
            </div>

            <div className="hidden md:flex items-center gap-2 font-mono text-[11px] text-[var(--color-secondary)]">
              <span className="material-symbols-outlined text-[16px] text-[var(--color-tertiary)]">
                schedule
              </span>
              <span>Telemetry Polling: T+04m 12s</span>
            </div>
          </div>
        </div>

        {/* Main Content Area */}
        <div className="max-w-7xl mx-auto w-full px-[var(--spacing-margin)] py-[var(--spacing-space-xl)] flex-1">
          {isLoadingAnalysis ? (
            <div className="flex flex-col items-center justify-center p-20 gap-3">
              <span className="material-symbols-outlined text-4xl text-[var(--color-primary-container)] animate-spin">
                progress_activity
              </span>
              <p className="text-sm font-semibold text-[var(--color-on-surface)]">
                Loading saved analysis data...
              </p>
            </div>
          ) : error ? (
            <div className="p-8 max-w-lg mx-auto bg-[var(--color-surface-container-lowest)] rounded-xl border border-[var(--color-error-container)] text-center">
              <span className="material-symbols-outlined text-4xl text-[var(--color-error)] mb-2 block">
                error
              </span>
              <h2 className="text-base font-bold text-[var(--color-on-surface)] mb-1">
                Unable to Load Analysis
              </h2>
              <p className="text-xs text-[var(--color-on-surface-variant)] mb-4">{error}</p>
              <button
                onClick={() => navigate('/')}
                className="px-4 py-2 rounded-lg bg-[var(--color-brand-navy)] text-white text-xs font-bold"
              >
                Return to Area Selection
              </button>
            </div>
          ) : analysis ? (
            <>
              {currentTab === 'analysis' && (
                <AnalysisOverviewTab
                  analysis={analysis}
                  recommendations={recommendationsData?.recommendations}
                  onNavigateToTab={(tab) => setCurrentTab(tab)}
                />
              )}
              {currentTab === 'flow' && (
                <TrafficFlowTab
                  analysis={analysis}
                  trafficData={trafficData}
                  isLoading={isLoadingTraffic && !trafficData}
                />
              )}
              {currentTab === 'recommendations' && (
                <RecommendationsTab
                  analysis={analysis}
                  recommendationsData={recommendationsData}
                  isLoading={isLoadingRecs && !recommendationsData}
                />
              )}
              {currentTab === 'simulation' && (
                <SumoSimulationTab analysis={analysis} />
              )}
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}
