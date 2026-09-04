import '@testing-library/jest-dom/vitest'

// Recharts measures its container; jsdom reports zero, which would make every
// chart render empty. A fixed size keeps chart-bearing components testable.
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 })
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 400 })

globalThis.ResizeObserver =
  globalThis.ResizeObserver ??
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
