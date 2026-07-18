export type Theme = 'light' | 'dark'

export function initialTheme(): Theme {
  const stored = localStorage.getItem('fm-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  localStorage.setItem('fm-theme', theme)
}
