import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react'
import { Link, Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { ErrorState, LoadingState } from '@/components/ui/States'
import { LiveDataProvider } from '@/providers/LiveDataProvider'
import { AnalyticsPage } from '@/pages/Analytics'
import { DashboardPage } from '@/pages/Dashboard'
import { SecurityPage } from '@/pages/Security'
import { SettingsPage } from '@/pages/Settings'
import { SimulatorPage } from '@/pages/Simulator'
import { SystemPage } from '@/pages/System'
import { TrafficPage } from '@/pages/Traffic'

interface BoundaryState {
  error: Error | null
}

/**
 * Last line of defence.
 *
 * A rendering bug in one panel must not leave the operator staring at a blank
 * page with no way forward, so the boundary shows what failed and offers a
 * reload.
 */
class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('CAN-Sentinel UI error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="grid min-h-screen place-items-center p-6">
          <div className="w-full max-w-lg rounded-xl border border-base-700 bg-base-850 p-6 shadow-panel">
            <ErrorState
              error={this.state.error}
              onRetry={() => {
                this.setState({ error: null })
                window.location.reload()
              }}
            />
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function NotFound() {
  return (
    <div className="grid place-items-center py-20 text-center">
      <p className="mono text-3xl font-semibold text-ink-faint">404</p>
      <p className="mt-2 text-sm text-ink">That page does not exist.</p>
      <Link
        to="/"
        className="mt-4 rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-xs font-medium text-sky-200 transition hover:bg-accent/25"
      >
        Back to the dashboard
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <LiveDataProvider>
        <Router>
          <Suspense fallback={<LoadingState label="Loading CAN-Sentinel…" />}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/traffic" element={<TrafficPage />} />
                <Route path="/security" element={<SecurityPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/simulator" element={<SimulatorPage />} />
                <Route path="/system" element={<SystemPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/dashboard" element={<Navigate to="/" replace />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </Suspense>
        </Router>
      </LiveDataProvider>
    </ErrorBoundary>
  )
}
