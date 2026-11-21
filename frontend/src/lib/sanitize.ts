/**
 * HTML Sanitization Utility
 * Safely escapes HTML special characters in strings before injection into Leaflet popups/tooltips.
 */

export function escapeHtml(str: unknown): string {
  if (str == null) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
