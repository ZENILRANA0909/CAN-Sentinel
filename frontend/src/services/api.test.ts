import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError, api, streamUrl } from './api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API client', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed body on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'healthy' }))
    await expect(api.health()).resolves.toEqual({ status: 'healthy' })
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('builds query strings and omits empty parameters', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]))
    await api.recentMessages({ limit: 25, can_id: '0x300', search: '', flagged_only: false })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('limit=25')
    expect(url).toContain('can_id=0x300')
    expect(url).toContain('flagged_only=false')
    expect(url).not.toContain('search=')
  })

  it('surfaces the backend error envelope', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: 'invalid_can_message', message: 'bad frame', details: { field: 'can_id' } },
        422,
      ),
    )
    await expect(api.injectFrame({ can_id: 2304, data: '00' })).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 422,
      code: 'invalid_can_message',
      message: 'bad frame',
      details: { field: 'can_id' },
    })
  })

  it('reports a network failure as offline', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const error = await api.status().catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiRequestError)
    expect((error as ApiRequestError).isOffline).toBe(true)
    expect((error as ApiRequestError).code).toBe('network_error')
  })

  it('reports an aborted request as a timeout', async () => {
    fetchMock.mockRejectedValue(new DOMException('aborted', 'AbortError'))
    const error = (await api.status().catch((caught: unknown) => caught)) as ApiRequestError
    expect(error.code).toBe('timeout')
  })

  it('handles a non-JSON error body', async () => {
    fetchMock.mockResolvedValue(new Response('gateway exploded', { status: 502 }))
    const error = (await api.health().catch((caught: unknown) => caught)) as ApiRequestError
    expect(error.status).toBe(502)
    expect(error.code).toBe('http_error')
  })

  it('handles an empty 204 response', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(api.stopSimulation()).resolves.toBeUndefined()
  })

  it('sends a JSON content type only when there is a body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await api.stopMonitor()
    expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty('Content-Type')

    fetchMock.mockResolvedValue(jsonResponse({}))
    await api.updateConfig({ detection: { flood_threshold: 500 } })
    expect(fetchMock.mock.calls[1][1].headers).toHaveProperty('Content-Type', 'application/json')
  })

  it('uses PATCH for triage', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, status: 'RESOLVED' }))
    await api.updateAttackStatus(1, 'RESOLVED')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/attacks/1')
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH')
  })
})

describe('streamUrl', () => {
  it('derives a ws:// URL from an http origin', () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:5173' } })
    expect(streamUrl()).toBe('ws://localhost:5173/ws/traffic')
    vi.unstubAllGlobals()
  })

  it('derives a wss:// URL from an https origin', () => {
    vi.stubGlobal('window', { location: { protocol: 'https:', host: 'sentinel.test' } })
    expect(streamUrl()).toBe('wss://sentinel.test/ws/traffic')
    vi.unstubAllGlobals()
  })
})
