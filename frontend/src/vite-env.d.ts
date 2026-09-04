/// <reference types="vite/client" />

/** Environment variables the dashboard understands. All are optional. */
interface ImportMetaEnv {
  /** REST base path. Defaults to `/api` (same origin, proxied in development). */
  readonly VITE_API_BASE_URL?: string
  /** Absolute WebSocket URL. Defaults to `<origin>/ws/traffic`. */
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
