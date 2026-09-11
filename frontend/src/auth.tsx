import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setCsrf, type Me } from './api'
import { initTheme, toggleTheme, type Theme } from './theme'

type AuthState = {
  loading: boolean
  me: Me | null
  theme: Theme
  refresh: () => Promise<Me>
  logout: () => Promise<void>
  cycleTheme: () => void
}

const AuthCtx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [me, setMe] = useState<Me | null>(null)
  const [theme, setThemeState] = useState<Theme>(() => initTheme())

  const refresh = useCallback(async () => {
    const data = await api<Me>('/admin/api/auth/me')
    setCsrf(data.csrf_token)
    setMe(data)
    return data
  }, [])

  useEffect(() => {
    refresh()
      .catch(() => setMe({ admin: false, csrf_token: '' }))
      .finally(() => setLoading(false))
  }, [refresh])

  const logout = useCallback(async () => {
    await api('/admin/api/auth/logout', { method: 'POST' })
    await refresh()
  }, [refresh])

  const cycleTheme = useCallback(() => {
    setThemeState((t) => toggleTheme(t))
  }, [])

  const value = useMemo(
    () => ({ loading, me, theme, refresh, logout, cycleTheme }),
    [loading, me, theme, refresh, logout, cycleTheme],
  )

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth outside provider')
  return ctx
}
