import React, { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Unhandled React Error in Gativa:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-[#f8f9ff] p-6">
          <div className="max-w-lg w-full bg-white rounded-xl shadow-lg border border-[#ffdad6] p-6 text-center">
            <span className="material-symbols-outlined text-4xl text-[#ba1a1a] mb-3 block">
              error
            </span>
            <h2 className="text-lg font-bold text-[#0b1c30] mb-2">
              Something went wrong loading this view
            </h2>
            <p className="text-xs text-[#554336] mb-4 font-mono bg-[#eff4ff] p-3 rounded text-left overflow-auto">
              {this.state.error?.message || 'An unknown error occurred during rendering.'}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.href = '/'
              }}
              className="px-4 py-2 rounded-lg bg-[#0a1145] text-white text-xs font-bold hover:bg-[#1a2570] transition-colors"
            >
              Reload Application
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
