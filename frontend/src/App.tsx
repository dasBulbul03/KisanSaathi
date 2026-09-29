/**
 * Routes and access control.
 *
 * `RequireAuth` and `RequireRole` are the only two guards, and both redirect
 * rather than render an error. A role that opens a URL it cannot use should end
 * up on its own landing page, not on a "403" screen: the nav never offers the
 * link, so arriving there means a stale bookmark or a hand-edited URL, and a
 * dead end helps nobody.
 */

import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import AppLayout from './components/AppLayout'
import { AuthProvider, useAuth, DEFAULT_LANDING } from './auth/AuthContext'
import { I18nProvider } from './lib/i18n'
import { Loading } from './components/ui'
import ErrorBoundary from './components/ErrorBoundary'
import { NavProvider, useAsync } from './hooks'
import { notifications as notificationsApi } from './lib/endpoints'
import type { UserRole } from './lib/types'

import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import FarmerDashboardPage from './pages/FarmerDashboardPage'
import BuyerDashboardPage from './pages/BuyerDashboardPage'
import AdminDashboardPage from './pages/AdminDashboardPage'
import { LotsPage } from './pages/LotsPage'
import { LotDetailPage } from './pages/LotDetailPage'
import { DemandsPage, DemandFormPage } from './pages/DemandsPage'
import { DemandDetailPage } from './pages/DemandDetailPage'
import { LotFormPage } from './pages/LotFormPage'
import { OffersPage } from './pages/OffersPage'
import { OrdersPage, OrderDetailPage } from './pages/OrdersPage'
import { MarketPage } from './pages/MarketPage'
import { StoragePage } from './pages/StoragePage'
import { PaymentsPage } from './pages/PaymentsPage'
import { LogisticsPage } from './pages/LogisticsPage'
import { InspectionsPage } from './pages/InspectionsPage'
import { GrievancesPage } from './pages/GrievancesPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { ProfilePage } from './pages/ProfilePage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { profile, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading />
  if (!profile) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

function RequireRole({ roles, children }: { roles: UserRole[]; children: ReactNode }) {
  const { role } = useAuth()
  if (!role) return <Navigate to="/login" replace />
  if (!roles.includes(role)) return <Navigate to={DEFAULT_LANDING[role]} replace />
  return <>{children}</>
}

/**
 * Bridges the auth and nav contexts: the nav needs the permission checker from
 * auth and the unread count from the API, and only exists once signed in.
 */
function AppShell() {
  const { can, hasRole, profile } = useAuth()
  // Fetched here, not in the layout, so the header badge and the nav render
  // from a single request rather than two racing ones.
  const unread = useAsync(async () => (await notificationsApi.unreadCount()).unread_count, {
    enabled: Boolean(profile),
  })
  return (
    <NavProvider can={can} hasRole={hasRole}>
      <AppLayout unreadCount={unread.data ?? 0} />
    </NavProvider>
  )
}

function Home() {
  const { role } = useAuth()
  return <Navigate to={role ? DEFAULT_LANDING[role] : '/login'} replace />
}

export default function App() {
  return (
    <I18nProvider>
      <ErrorBoundary>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route path="/" element={<Home />} />
              <Route path="/profile" element={<ProfilePage />} />

              <Route path="/dashboard" element={<DashboardRouter />} />
              <Route
                path="/admin"
                element={
                  <RequireRole roles={['ADMIN']}>
                    <AdminDashboardPage />
                  </RequireRole>
                }
              />

              <Route
                path="/lots"
                element={
                  <RequireRole roles={['BUYER', 'FPO', 'ADMIN']}>
                    <LotsPage scope="browse" />
                  </RequireRole>
                }
              />
              <Route
                path="/lots/:id"
                element={
                  <RequireRole roles={['BUYER', 'FPO', 'ADMIN', 'FARMER']}>
                    <LotDetailPage scope="browse" />
                  </RequireRole>
                }
              />
              <Route
                path="/my-lots"
                element={
                  <RequireRole roles={['FARMER', 'FPO']}>
                    <LotsPage scope="mine" />
                  </RequireRole>
                }
              />
              <Route
                path="/my-lots/new"
                element={
                  <RequireRole roles={['FARMER', 'FPO']}>
                    <LotFormPage />
                  </RequireRole>
                }
              />
              <Route
                path="/my-lots/:id/edit"
                element={
                  <RequireRole roles={['FARMER', 'FPO']}>
                    <LotFormPage />
                  </RequireRole>
                }
              />
              <Route
                path="/my-lots/:id"
                element={
                  <RequireRole roles={['FARMER', 'FPO']}>
                    <LotDetailPage scope="mine" />
                  </RequireRole>
                }
              />

              <Route
                path="/demands"
                element={
                  <RequireRole roles={['FARMER', 'FPO', 'ADMIN']}>
                    <DemandsPage scope="browse" />
                  </RequireRole>
                }
              />
              <Route
                path="/demands/:id"
                element={
                  <RequireRole roles={['FARMER', 'FPO', 'ADMIN', 'BUYER']}>
                    <DemandDetailPage />
                  </RequireRole>
                }
              />
              <Route
                path="/my-demands"
                element={
                  <RequireRole roles={['BUYER']}>
                    <DemandsPage scope="mine" />
                  </RequireRole>
                }
              />
              <Route
                path="/my-demands/new"
                element={
                  <RequireRole roles={['BUYER']}>
                    <DemandFormPage />
                  </RequireRole>
                }
              />
              <Route
                path="/my-demands/:id"
                element={
                  <RequireRole roles={['BUYER']}>
                    <DemandFormPage />
                  </RequireRole>
                }
              />

              <Route path="/offers" element={<OffersPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/orders/:id" element={<OrderDetailPage />} />
              <Route path="/market" element={<MarketPage />} />
              <Route
                path="/storage"
                element={
                  <RequireRole roles={['FARMER', 'FPO']}>
                    <StoragePage scope="options" />
                  </RequireRole>
                }
              />
              <Route path="/payments" element={<PaymentsPage />} />
              <Route path="/logistics" element={<LogisticsPage />} />
              <Route
                path="/inspections"
                element={
                  <RequireRole roles={['QUALITY_INSPECTOR', 'ADMIN', 'FARMER', 'FPO', 'BUYER']}>
                    <InspectionsPage />
                  </RequireRole>
                }
              />
              <Route
                path="/grievances"
                element={
                  <RequireRole roles={['FARMER', 'FPO', 'BUYER', 'LOGISTICS_PARTNER']}>
                    <GrievancesPage />
                  </RequireRole>
                }
              />
              <Route path="/notifications" element={<NotificationsPage />} />
              <Route
                path="/users"
                element={
                  <RequireRole roles={['ADMIN']}>
                    <AdminUsersPage />
                  </RequireRole>
                }
              />
            </Route>

            <Route path="*" element={<Home />} />
          </Routes>
        </AuthProvider>
      </ErrorBoundary>
    </I18nProvider>
  )
}

/** Sends each role to the dashboard it actually has. */
function DashboardRouter() {
  const { role } = useAuth()
  if (role === 'BUYER') return <BuyerDashboardPage />
  if (role === 'ADMIN') return <AdminDashboardPage />
  if (role === 'FARMER' || role === 'FPO') return <FarmerDashboardPage />
  return <Navigate to={role ? DEFAULT_LANDING[role] : '/login'} replace />
}
