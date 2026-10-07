"use client"

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react"
import {
  clearTokens,
  getAccessToken,
  getMe,
  getStoredUser,
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  storeAuthUser,
  type User,
} from "@/lib/api"
import { resetAksiStore } from "@/lib/stores/aksi"
import { resetChatStore } from "@/lib/stores/chat"
import { resetSchedulesStore } from "@/lib/stores/schedules"
import { resetThreadsStore } from "@/lib/stores/threads"
import { useRouter, usePathname } from "next/navigation"

interface AuthContextValue {
  token: string | null
  user: User | null
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Start empty so the server render and the first client render agree — the
  // session lives in localStorage, which SSR can't read. Restored post-mount.
  const [hydrated, setHydrated] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const router = useRouter()
  const pathname = usePathname()

  const isAuthPage = pathname === "/login"
  const isLoading = !hydrated || (Boolean(token) && !user)

  const fetchUser = useCallback(async () => {
    try {
      const userData = await getMe()
      setUser(userData)
      storeAuthUser(userData)
      return true
    } catch {
      clearTokens()
      // Session is dead — drop cached app state so a fresh login never sees
      // the previous user's threads, chat, or corporate-action board.
      resetChatStore()
      resetThreadsStore()
      resetAksiStore()
      resetSchedulesStore()
      setToken(null)
      setUser(null)
      return false
    }
  }, [])

  // Restore the persisted session once, after mount. Deferred a tick so the
  // updates don't run synchronously inside the effect body.
  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setToken(getAccessToken())
      setUser(getStoredUser())
      setHydrated(true)
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [])

  // A token without a user means we only have half a session — fetch /me.
  useEffect(() => {
    if (!token || user) return
    const timeoutId = window.setTimeout(() => void fetchUser(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [fetchUser, token, user])

  // Redirect logic
  useEffect(() => {
    if (isLoading) return
    if (!token && !isAuthPage) {
      router.replace("/login")
    } else if (token && isAuthPage) {
      router.replace("/")
    }
  }, [token, isLoading, isAuthPage, router])

  const login = useCallback(
    async (username: string, password: string) => {
      const userData = await apiLogin(username, password)
      setUser(userData)
      setToken(getAccessToken())
      router.replace("/")
    },
    [router]
  )

  const register = useCallback(
    async (username: string, password: string) => {
      const userData = await apiRegister(username, password)
      setUser(userData)
      setToken(getAccessToken())
      router.replace("/")
    },
    [router]
  )

  const logout = useCallback(() => {
    void apiLogout()
    resetChatStore()
    resetThreadsStore()
    resetAksiStore()
    resetSchedulesStore()
    setToken(null)
    setUser(null)
    router.replace("/login")
  }, [router])

  return (
    <AuthContext.Provider value={{ token, user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return ctx
}
