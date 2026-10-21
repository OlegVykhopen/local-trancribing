import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { motion } from 'motion/react'

const NAV_ITEMS = [
  { to: '/download', label: 'Download' },
  { to: '/transcribe', label: 'Transcribe' },
  { to: '/files', label: 'Files' },
]

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100">
      <nav className="flex w-48 shrink-0 flex-col gap-1 border-r border-zinc-800 p-3">
        <div className="mb-3 px-2 text-sm font-semibold tracking-wide text-zinc-300">Transcribing Studio</div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `relative rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive ? 'text-white' : 'text-zinc-400 hover:text-zinc-200'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="nav-active-indicator"
                    className="absolute inset-0 rounded-md bg-indigo-600/90"
                    transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                  />
                )}
                <span className="relative z-10">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
    </div>
  )
}
