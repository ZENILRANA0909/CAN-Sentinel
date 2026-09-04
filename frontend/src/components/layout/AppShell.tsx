import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'

/** Persistent chrome: navigation, status bar, and the routed page body. */
export function AppShell() {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <div className="flex min-h-screen">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenNav={() => setNavOpen(true)} />
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 focus:outline-none lg:p-6">
          <Outlet />
        </main>
        <footer className="border-t border-base-800 px-4 py-3 text-2xs text-ink-faint lg:px-6">
          CAN-Sentinel — demonstration and research platform. Detection thresholds are illustrative
          and are not vehicle safety limits.
        </footer>
      </div>
    </div>
  )
}
