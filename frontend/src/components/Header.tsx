import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

const LOCAL_LOGO_URL = '/gativa-logo.png'

interface HeaderProps {
  analysisId?: string
}

export default function Header({ analysisId }: HeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [logoFailed, setLogoFailed] = useState(false)
  const isOnMap = location.pathname === '/'
  const isOnDashboard = analysisId && location.pathname.startsWith('/analysis')

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-[var(--color-surface-container-lowest)] border-b border-[var(--color-surface-container-high)]">
      <div className="h-14 w-full px-[var(--spacing-margin)] flex items-center justify-between">
        {/* Logo */}
        <div
          onClick={() => navigate('/')}
          className="flex items-center gap-[var(--spacing-space-md)] cursor-pointer select-none"
          title="Gativa — Return to Map Selection"
        >
          {!logoFailed ? (
            <img
              src={LOCAL_LOGO_URL}
              alt="GATIVA — Intelligence in Motion"
              className="h-9 w-auto object-contain"
              onError={() => setLogoFailed(true)}
            />
          ) : (
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 rounded-lg bg-[var(--color-brand-navy)] flex items-center justify-center text-white font-extrabold text-sm">
                G
              </span>
              <div className="flex flex-col">
                <span className="font-extrabold text-base tracking-tight text-[var(--color-brand-navy)] leading-none">
                  GAT<span className="text-[var(--color-primary-container)]">I</span>VA
                </span>
                <span className="text-[9px] font-semibold text-[var(--color-secondary)] tracking-wider mt-0.5">
                  INTELLIGENCE IN MOTION
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Navigation pills */}
        <div className="flex items-center gap-[var(--spacing-space-xl)]">
          <nav className="flex items-center gap-[var(--spacing-space-xs)] p-1 bg-[var(--color-surface-container-low)] rounded-lg">
            <button
              onClick={() => navigate('/')}
              className={`px-[var(--spacing-space-md)] py-1.5 rounded text-sm font-medium transition-colors ${
                isOnMap
                  ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] font-semibold'
                  : 'text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container-high)] hover:text-[var(--color-on-surface)]'
              }`}
            >
              Area Selection
            </button>
            <button
              onClick={() => analysisId && navigate(`/analysis/${analysisId}`)}
              disabled={!analysisId}
              className={`px-[var(--spacing-space-md)] py-1.5 rounded text-sm font-medium transition-colors ${
                isOnDashboard
                  ? 'bg-[var(--color-secondary-fixed)] text-[var(--color-on-secondary-fixed)] font-semibold'
                  : analysisId
                  ? 'text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container-high)] hover:text-[var(--color-on-surface)]'
                  : 'text-[var(--color-on-surface-variant)] opacity-40 cursor-not-allowed'
              }`}
            >
              Analysis Dashboard
            </button>
          </nav>
        </div>
      </div>
    </header>
  )
}
