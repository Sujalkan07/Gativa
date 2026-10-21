import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../../api/client'
import type { GeocodingResult } from '../../types/api'

interface LocationSearchBoxProps {
  onSelectLocation: (location: GeocodingResult) => void
  onClearLocation?: () => void
  selectedLocationName?: string | null
  className?: string
}

export default function LocationSearchBox({
  onSelectLocation,
  onClearLocation,
  selectedLocationName,
  className = '',
}: LocationSearchBoxProps) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<GeocodingResult[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const requestIdRef = useRef(0)

  // Update input when parent notifies of selected location
  useEffect(() => {
    if (selectedLocationName) {
      setQuery(selectedLocationName)
    }
  }, [selectedLocationName])

  // Click outside listener to dismiss dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setHighlightedIndex(-1)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Execute debounced search
  useEffect(() => {
    const trimmed = query.trim()

    // Cancel any pending inflight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    if (trimmed.length < 2) {
      setSuggestions([])
      setIsLoading(false)
      setSearchError(null)
      setHasSearched(false)
      setHighlightedIndex(-1)
      return
    }

    // If query matches current selection exactly, do not auto-reopen suggestions
    if (selectedLocationName && trimmed === selectedLocationName.trim()) {
      return
    }

    setIsLoading(true)
    setSearchError(null)
    const currentRequestId = ++requestIdRef.current
    const controller = new AbortController()
    abortControllerRef.current = controller

    const timer = setTimeout(async () => {
      try {
        const response = await api.searchLocations(trimmed, 6, controller.signal)
        if (requestIdRef.current === currentRequestId) {
          setSuggestions(response.results)
          setHasSearched(true)
          setIsOpen(true)
          setHighlightedIndex(response.results.length > 0 ? 0 : -1)
          setIsLoading(false)
        }
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError' && (err as { name?: string })?.name !== 'AbortError') {
          if (requestIdRef.current === currentRequestId) {
            setSearchError('Location search unavailable. Please check connectivity.')
            setSuggestions([])
            setHasSearched(true)
            setIsOpen(true)
            setIsLoading(false)
          }
        }
      }
    }, 320) // 320ms debounce

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, selectedLocationName])

  const handleSelectSuggestion = useCallback(
    (item: GeocodingResult) => {
      setQuery(item.name || item.display_name)
      setIsOpen(false)
      setHighlightedIndex(-1)
      onSelectLocation(item)
      inputRef.current?.blur()
    },
    [onSelectLocation]
  )

  const handleClear = useCallback(() => {
    setQuery('')
    setSuggestions([])
    setIsOpen(false)
    setHighlightedIndex(-1)
    setSearchError(null)
    setHasSearched(false)
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    if (onClearLocation) {
      onClearLocation()
    }
    inputRef.current?.focus()
  }, [onClearLocation])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      if (suggestions.length > 0) {
        setIsOpen(true)
        return
      }
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        if (suggestions.length > 0) {
          setHighlightedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0))
        }
        break
      case 'ArrowUp':
        e.preventDefault()
        if (suggestions.length > 0) {
          setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1))
        }
        break
      case 'Enter':
        e.preventDefault()
        if (isOpen && highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
          handleSelectSuggestion(suggestions[highlightedIndex])
        } else if (suggestions.length > 0) {
          handleSelectSuggestion(suggestions[0])
        }
        break
      case 'Escape':
        e.preventDefault()
        setIsOpen(false)
        setHighlightedIndex(-1)
        inputRef.current?.blur()
        break
      default:
        break
    }
  }

  return (
    <div ref={containerRef} className={`relative z-[1001] w-full max-w-[380px] sm:max-w-[420px] ${className}`}>
      {/* Search Input Bar */}
      <div className="relative flex items-center bg-[var(--color-surface-container-lowest)] rounded-xl shadow-md border border-[var(--color-surface-container-high)] hover:border-[var(--color-secondary)] focus-within:border-[var(--color-primary-container)] focus-within:ring-2 focus-within:ring-[var(--color-primary-container)]/20 transition-all">
        {/* Search Icon */}
        <div className="pl-3.5 pr-2 flex items-center justify-center text-[var(--color-brand-navy)] pointer-events-none">
          {isLoading ? (
            <span className="material-symbols-outlined text-[19px] text-[var(--color-primary-container)] animate-spin">
              progress_activity
            </span>
          ) : (
            <span className="material-symbols-outlined text-[19px] text-[var(--color-secondary)]">
              search
            </span>
          )}
        </div>

        {/* Input Element */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            if (suggestions.length > 0 || (hasSearched && query.trim().length >= 2)) {
              setIsOpen(true)
            }
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search city, area, landmark or road..."
          aria-label="Search city, area, landmark or road"
          aria-autocomplete="list"
          aria-expanded={isOpen}
          role="combobox"
          className="w-full py-2.5 pr-9 text-xs sm:text-sm font-medium text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)]/60 bg-transparent focus:outline-hidden"
        />

        {/* Clear Button */}
        {query.length > 0 && (
          <button
            type="button"
            onClick={handleClear}
            title="Clear search"
            aria-label="Clear search"
            className="absolute right-2.5 w-6 h-6 rounded-full flex items-center justify-center text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container-high)] hover:text-[var(--color-on-surface)] transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
          </button>
        )}
      </div>

      {/* Suggestions Dropdown */}
      {isOpen && (
        <div className="absolute top-[calc(100%+6px)] left-0 right-0 max-h-[300px] overflow-y-auto bg-[var(--color-surface-container-lowest)] rounded-xl shadow-xl border border-[var(--color-surface-container-high)] py-1.5 divide-y divide-[var(--color-surface-container-low)]">
          {isLoading && suggestions.length === 0 && (
            <div className="px-4 py-3 flex items-center gap-2 text-xs text-[var(--color-on-surface-variant)]">
              <span className="material-symbols-outlined text-[16px] text-[var(--color-primary-container)] animate-spin">
                progress_activity
              </span>
              <span>Searching locations across OpenStreetMap…</span>
            </div>
          )}

          {searchError && (
            <div className="px-4 py-3 flex items-start gap-2 text-xs text-[var(--color-error)] bg-[var(--color-error-container)]/30 rounded-lg mx-1.5">
              <span className="material-symbols-outlined text-[16px] shrink-0 mt-0.5">error</span>
              <div>
                <p className="font-semibold">{searchError}</p>
                <p className="text-[11px] text-[var(--color-on-surface-variant)] mt-0.5">
                  Try typing a broader city name or landmark.
                </p>
              </div>
            </div>
          )}

          {!isLoading && !searchError && hasSearched && suggestions.length === 0 && (
            <div className="px-4 py-3 text-center text-xs text-[var(--color-on-surface-variant)]">
              <span className="material-symbols-outlined text-2xl text-[var(--color-secondary)]/60 mb-1 block">
                location_off
              </span>
              <p className="font-semibold text-[var(--color-on-surface)]">No matching places found</p>
              <p className="text-[11px] mt-0.5">Check for typos or search for a nearby city/major junction.</p>
            </div>
          )}

          {suggestions.map((item, idx) => {
            const isHighlighted = idx === highlightedIndex
            return (
              <button
                key={item.place_id || `${item.lat}-${item.lng}-${idx}`}
                type="button"
                onMouseEnter={() => setHighlightedIndex(idx)}
                onClick={() => handleSelectSuggestion(item)}
                className={`w-full text-left px-3.5 py-2.5 flex items-start gap-3 transition-colors ${
                  isHighlighted
                    ? 'bg-[var(--color-surface-container)] text-[var(--color-brand-navy)]'
                    : 'hover:bg-[var(--color-surface-container-low)] text-[var(--color-on-surface)]'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[18px] shrink-0 mt-0.5 ${
                    isHighlighted ? 'text-[var(--color-primary-container)]' : 'text-[var(--color-secondary)]'
                  }`}
                >
                  {item.category === 'highway' || item.type === 'junction'
                    ? 'alt_route'
                    : item.type === 'city' || item.type === 'administrative'
                    ? 'location_city'
                    : 'place'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold truncate leading-tight">{item.name}</p>
                  {item.secondary_text && (
                    <p className="text-[11px] text-[var(--color-on-surface-variant)] truncate leading-normal mt-0.5">
                      {item.secondary_text}
                    </p>
                  )}
                </div>
                {item.type && (
                  <span className="shrink-0 text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-[var(--color-surface-container-high)] text-[var(--color-on-surface-variant)]">
                    {item.type.replace(/_/g, ' ')}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
