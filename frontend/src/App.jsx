import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { useAuthStore } from './store/auth'
import Login from './pages/Login'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import IOSInstallBanner from './components/IOSInstallBanner'

const ChangePassword = lazy(() => import('./pages/ChangePassword'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const AdminUsers = lazy(() => import('./pages/admin/AdminUsers'))
const AdminKB = lazy(() => import('./pages/admin/AdminKB'))

function RequireAuth({ children }) {
  const { isAuthenticated } = useAuthStore()
  return isAuthenticated ? children : <Navigate to="/login" replace />
}

function RequirePasswordChange({ children }) {
  const { user } = useAuthStore()
  if (user?.must_change_password) return <Navigate to="/change-password" replace />
  return children
}

function LazyFallback() {
  return <div className="spinner" style={{ marginTop: '3rem' }} />
}

function AppRoutes() {
  return (
    <Suspense fallback={<LazyFallback />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<RequireAuth><ChangePassword /></RequireAuth>} />

        <Route path="/" element={<RequireAuth><RequirePasswordChange><Layout /></RequirePasswordChange></RequireAuth>}>
          <Route index element={<ChatPage />} />
          <Route path="chat/:chatId" element={<ChatPage />} />
          <Route path="admin/users" element={<AdminUsers />} />
          <Route path="admin/kb" element={<AdminKB />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <IOSInstallBanner />
        <Toaster
          position="top-center"
          toastOptions={{ duration: 4000 }}
          containerStyle={{ top: 'calc(env(safe-area-inset-top) + 1rem)' }}
        />
        <AppRoutes />
      </BrowserRouter>
    </ErrorBoundary>
  )
}
