"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

export type ThemePreference = "light" | "dark" | "system"
export type LanguagePreference = "en" | "id"

export interface AppSettings {
  theme: ThemePreference
  /** Enter sends the message; when off, Ctrl/Cmd+Enter sends instead. */
  sendWithEnter: boolean
  /** Toast when a thread that kept generating in the background finishes. */
  notifyOnDone: boolean
  /** Reply language (chat) + Corporate Actions page language. */
  language: LanguagePreference
}

const STORAGE_KEY = "iori:settings"

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "dark",
  sendWithEnter: true,
  notifyOnDone: true,
  language: "en",
}

export function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<AppSettings>) }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function persistSettings(settings: AppSettings) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // Storage may be unavailable (private mode); settings stay session-local.
  }
}

function resolvedTheme(theme: ThemePreference): "light" | "dark" {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light"
  }
  return theme
}

export function applyThemePreference(theme: ThemePreference) {
  const resolved = resolvedTheme(theme)
  document.documentElement.classList.toggle("dark", resolved === "dark")
  document.documentElement.style.colorScheme = resolved
}

interface SettingsContextValue {
  settings: AppSettings
  /** False until the stored settings have been read after mount (SSR-safe). */
  hydrated: boolean
  updateSettings: (patch: Partial<AppSettings>) => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  // Start from defaults so SSR and the first client render agree; the stored
  // settings are read in an effect after mount (same pattern as AuthProvider).
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setSettings(loadSettings())
      setHydrated(true)
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [])

  // Keep the <html> dark class in sync; follow the OS while theme is "system".
  useEffect(() => {
    if (!hydrated) return
    applyThemePreference(settings.theme)
    if (settings.theme !== "system") return

    const media = window.matchMedia("(prefers-color-scheme: dark)")
    const onChange = () => applyThemePreference("system")
    media.addEventListener("change", onChange)
    return () => media.removeEventListener("change", onChange)
  }, [settings.theme, hydrated])

  // Sync across tabs via the storage event.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setSettings(loadSettings())
    }
    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [])

  const updateSettings = useCallback((patch: Partial<AppSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch }
      persistSettings(next)
      return next
    })
  }, [])

  const value = useMemo(
    () => ({ settings, hydrated, updateSettings }),
    [settings, hydrated, updateSettings],
  )

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) {
    throw new Error("useSettings must be used within a SettingsProvider")
  }
  return ctx
}
