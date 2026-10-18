import { useNavigate, useLocation } from 'react-router-dom'

const LOGO_URL =
  'https://lh3.googleusercontent.com/aida/AEtjO1VOsvJY_Uawj0J9X4lmzA6jyPg6L6NzmjLdz44Pbu-nbR6UnC6KxSePWNc3GrR1mrGTXRM3402KWfIeBx-2FWQih7AicyJqciWVcVZfewA9xgxTfmh5znHVzEnfAO0m5fSm39L5kcBH6EEqMV0gNE_AQA7n3mkDHB9KG7j1Nk7Ut-Xm5mep4I8kflQLR6HDTEO7qpVl_ynRZMc3ixabs7VGRa6S4bm05Mdy0Tugovzsv6U4qP-inlNQOLYRNi2R-JBCpIFRyTKPkw'

interface HeaderProps {
  analysisId?: string
}

export default function Header({ analysisId }: HeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const isOnMap = location.pathname === '/'
  const isOnDashboard = analysisId && location.pathname.startsWith('/analysis')

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-[var(--color-surface-container-lowest)] border-b border-[var(--color-surface-container-high)]">
      <div className="h-14 w-full px-[var(--spacing-margin)] flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-[var(--spacing-space-lg)]">
          <img
            src={LOGO_URL}
            alt="GATIVA — Intelligence in Motion"
            className="h-8 w-auto object-contain"
          />
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
