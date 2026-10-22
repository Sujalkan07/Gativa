import axios, { AxiosError } from 'axios'
import type {
  CreateAnalysisRequest,
  AnalysisResult,
  TrafficFlowResult,
  RecommendationsResult,
  SimulationPrepareRequest,
  SimulationStatusResponse,
  ScenarioComparisonResult,
  CongestionSummary,
  SignalListResponse,
  SignalEditRequest,
  SignalEditResponse,
  SignalCandidateListResponse,
  CandidateDecisionRequest,
  GeocodingResult,
  GeocodingSearchResponse,
  ApiError,
} from '../types/api'


// Use the same-origin /api proxy in local development and behind a single
// reverse proxy. Set VITE_API_BASE_URL only when the API is intentionally hosted
// on a separate origin with matching CORS policy.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120000, // 120s ceiling for extensive geospatial operations
  headers: {
    'Content-Type': 'application/json',
  },
})

function extractError(err: unknown): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined
    if (data?.detail) return data.detail
    if (err.message) return err.message
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred'
}

export class GativaApiError extends Error {
  statusCode?: number
  code?: string

  constructor(message: string, statusCode?: number, code?: string) {
    super(message)
    this.name = 'GativaApiError'
    this.statusCode = statusCode
    this.code = code
  }
}

async function handleRequest<T>(promise: Promise<{ data: T }>): Promise<T> {
  try {
    const response = await promise
    return response.data
  } catch (err) {
    const message = extractError(err)
    const statusCode = err instanceof AxiosError ? err.response?.status : undefined
    throw new GativaApiError(message, statusCode)
  }
}

// ─── Endpoints ───────────────────────────────────────────────────────────────

export const api = {
  health: async (): Promise<{ status: string }> =>
    handleRequest(client.get('/api/health')),

  createAnalysis: async (request: CreateAnalysisRequest): Promise<AnalysisResult> =>
    handleRequest(client.post('/api/analyses', request)),

  getAnalysis: async (analysisId: string): Promise<AnalysisResult> =>
    handleRequest(client.get(`/api/analyses/${analysisId}`)),

  getTrafficFlow: async (analysisId: string): Promise<TrafficFlowResult> =>
    handleRequest(client.get(`/api/analyses/${analysisId}/traffic-flow`)),

  getRecommendations: async (analysisId: string): Promise<RecommendationsResult> =>
    handleRequest(client.get(`/api/analyses/${analysisId}/recommendations`)),

  exportGeoJSON: async (analysisId: string): Promise<Blob> => {
    const response = await client.get(`/api/analyses/${analysisId}/export/geojson`, {
      responseType: 'blob',
    })
    return response.data
  },

  prepareSimulation: async (request: SimulationPrepareRequest): Promise<SimulationStatusResponse> =>
    handleRequest(client.post('/api/simulations/prepare', request)),

  startSimulation: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/start`)),

  pauseSimulation: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/pause`)),

  stepSimulation: async (simId: string, steps: number = 2): Promise<SimulationStatusResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/step?steps=${steps}`)),

  resetSimulation: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/reset`)),

  stopSimulation: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/stop`)),

  getSimulationStatus: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.get(`/api/simulations/${simId}`)),

  getScenarioComparison: async (simId: string): Promise<ScenarioComparisonResult> =>
    handleRequest(client.get(`/api/simulations/${simId}/comparison`)),

  getCongestionResults: async (simId: string): Promise<CongestionSummary> =>
    handleRequest(client.get(`/api/simulations/${simId}/congestion`)),

  getBaselineStatus: async (simId: string): Promise<SimulationStatusResponse> =>
    handleRequest(client.get(`/api/simulations/${simId}/baseline`)),

  getSimulationSignals: async (simId: string): Promise<SignalListResponse> =>
    handleRequest(client.get(`/api/simulations/${simId}/signals`)),

  editSimulationSignal: async (
    simId: string,
    tlId: string,
    request: SignalEditRequest
  ): Promise<SignalEditResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/signals/${tlId}/edit`, request)),

  resetSimulationSignals: async (simId: string): Promise<SignalListResponse> =>
    handleRequest(client.post(`/api/simulations/${simId}/signals/reset`)),

  getSignalCandidates: async (analysisId: string): Promise<SignalCandidateListResponse> =>
    handleRequest(client.get(`/api/simulations/${analysisId}/signal-candidates`)),

  updateCandidateDecision: async (
    analysisId: string,
    candidateId: string,
    request: CandidateDecisionRequest
  ): Promise<{ status: string; candidate_id: string; decision: string }> =>
    handleRequest(
      client.post(`/api/simulations/${analysisId}/signal-candidates/${candidateId}/decision`, request)
    ),

  approveAllCandidates: async (
    analysisId: string
  ): Promise<{ message: string; approved_count: number }> =>
    handleRequest(client.post(`/api/simulations/${analysisId}/signal-candidates/approve-all`)),

  resetCandidates: async (analysisId: string): Promise<{ message: string }> =>
    handleRequest(client.post(`/api/simulations/${analysisId}/signal-candidates/reset`)),

  searchLocations: async (
    query: string,
    limit: number = 6,
    signal?: AbortSignal
  ): Promise<GeocodingSearchResponse> => {
    try {
      const resp = await client.get<GeocodingSearchResponse>('/api/geocoding/search', {
        params: { q: query, limit },
        signal,
        timeout: 6000,
      })
      return resp.data
    } catch (err: unknown) {
      if (axios.isCancel(err) || (err as { name?: string })?.name === 'CanceledError') {
        throw err
      }
      try {
        const fallbackUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=jsonv2&addressdetails=1&limit=${limit}`
        const fallbackResp = await fetch(fallbackUrl, {
          signal,
          headers: { 'Accept-Language': 'en' },
        })
        if (!fallbackResp.ok) throw new Error('Geocoding service unavailable')
        const items = (await fallbackResp.json()) as Array<{
          place_id?: string | number
          lat: string | number
          lon: string | number
          display_name?: string
          name?: string
          boundingbox?: string[]
          category?: string
          type?: string
        }>
        const results: GeocodingResult[] = (Array.isArray(items) ? items : []).map((item) => {
          const parts = String(item.display_name || '')
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
          const name = item.name || parts[0] || query
          const secondary = parts.slice(1).join(', ') || null
          const rawBbox = item.boundingbox
          const bbox: [number, number, number, number] | null =
            rawBbox && rawBbox.length === 4
              ? [parseFloat(rawBbox[0]), parseFloat(rawBbox[2]), parseFloat(rawBbox[1]), parseFloat(rawBbox[3])]
              : null
          return {
            place_id: String(item.place_id || `${item.lat}_${item.lon}`),
            name,
            display_name: item.display_name || name,
            secondary_text: secondary,
            lat: parseFloat(String(item.lat)),
            lng: parseFloat(String(item.lon)),
            bounding_box: bbox,
            category: item.category,
            type: item.type,
            provider: 'openstreetmap_direct',
          }
        })
        return {
          query,
          count: results.length,
          results,
          provider: 'openstreetmap_direct',
        }
      } catch (fallbackErr: unknown) {
        if ((fallbackErr as { name?: string })?.name === 'AbortError') throw fallbackErr
        throw new GativaApiError(extractError(err))
      }
    }
  },
}

