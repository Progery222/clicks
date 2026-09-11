import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth'
import { RequireAuth, LoginPage } from './pages/LoginPage'
import { LinksPage } from './pages/LinksPage'
import { StatsPage } from './pages/StatsPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { IndicatorsPage } from './pages/IndicatorsPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/admin/login" element={<LoginPage />} />
          <Route
            path="/admin"
            element={
              <RequireAuth>
                <LinksPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/profiles"
            element={
              <RequireAuth>
                <ProfilesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/links/:linkId/stats"
            element={
              <RequireAuth>
                <StatsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/indicators"
            element={
              <RequireAuth>
                <IndicatorsPage />
              </RequireAuth>
            }
          />
          <Route path="/" element={<Navigate to="/admin" replace />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
