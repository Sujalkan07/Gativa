import { Routes, Route, Navigate } from 'react-router-dom'
import MapSelectionPage from './pages/MapSelectionPage'
import AnalysisDashboardPage from './pages/AnalysisDashboardPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<MapSelectionPage />} />
      <Route path="/analysis/:analysisId" element={<AnalysisDashboardPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
