let csrfToken = ''

export function setCsrf(token: string) {
  csrfToken = token || ''
}

export function getCsrf() {
  return csrfToken
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function parseJson(res: Response) {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
  }
  if (options.method && !['GET', 'HEAD', 'OPTIONS'].includes(options.method.toUpperCase())) {
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  }
  const res = await fetch(path, {
    ...options,
    headers,
    credentials: 'include',
    body: options.json !== undefined ? JSON.stringify(options.json) : options.body,
  })
  const data = await parseJson(res)
  if (!res.ok) {
    const detail =
      (data && typeof data === 'object' && ('detail' in data || 'error' in data)
        ? String((data as { detail?: string; error?: string }).detail || (data as { error?: string }).error)
        : null) || res.statusText
    throw new ApiError(res.status, detail, data)
  }
  return data as T
}

export type Me = {
  admin: boolean
  csrf_token: string
  blocked?: boolean
  block_message?: string | null
}

export type Profile = { id: string; name: string; color: string; count?: number }

export type LinkRow = {
  id: string
  slug: string
  destination_url: string
  title: string | null
  label: string | null
  platform: string | null
  platform_label: string
  platform_color: string
  platform_icon_url: string | null
  destination_icon_url: string | null
  destination_icon_fallback_url?: string | null
  destination_icon_fallbacks?: string[]
  profile_id: string | null
  profile: { id: string; name: string; color: string } | null
  account_avatar_url: string | null
  account_display: string
  display_name: string
  avatar_mode: string
  total?: number
  today?: number
  period_clicks?: number
  period_uniques?: number
  created_at: string | null
}

export type ChartItem = { label: string; count: number; pct: number; color?: string }

export type Dashboard = {
  links: LinkRow[]
  profiles: Profile[]
  profile_filters: { id: string; name: string; color: string | null; count: number }[]
  destination_filters: {
    id: string
    name: string
    count: number
    icon_url?: string | null
    platform_icon_url?: string | null
    icon_fallbacks?: string[]
  }[]
  platform_filters: { id: string; label: string; color: string | null; count: number }[]
  filter_profile: string
  filter_platform: string
  filter_account: string
  filter_destination: string
  sort_by: string | null
  sort_order: string | null
  active_preset: string
  period_from: string
  period_to: string
  period_label: string
  period_total: number
  period_uniques: number
  platform_stats: { platform: string; label: string; color: string; clicks: number; uniques: number }[]
  filter_qs: string
  base_url: string
}

export type LinkStats = {
  link: LinkRow
  short_url: string
  total: number
  uniques: number
  active_preset: string
  period_from: string
  period_to: string
  charts: {
    clicks_by_day: ChartItem[]
    countries: ChartItem[]
    os: ChartItem[]
    devices: ChartItem[]
  }
  countries_missing_code: boolean
  geoip_db_present: boolean
}

export type Indicators = {
  filter_profile: string
  filter_platform: string
  active_preset: string
  period_from: string
  period_to: string
  period_label: string
  period_total: number
  period_uniques: number
  profile_filters: { id: string; name: string; color: string | null; count: number }[]
  platform_filters: { id: string; label: string; color: string | null }[]
  platform_stats: { platform: string; label: string; color: string; clicks: number; uniques: number }[]
  charts: {
    os: ChartItem[]
    devices: ChartItem[]
    profiles: ChartItem[]
    platforms: ChartItem[]
  }
}
