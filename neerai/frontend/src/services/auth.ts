/**
 * Amazon Cognito Hosted UI sign-in (OAuth 2.0 authorization-code flow with PKCE; no client secret exists or is needed).
 * Enabled only when VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID are set at build time (public identifiers, not secrets).
 * Without them the app runs unauthenticated, as in local demo mode.
 *
 * Tokens live in sessionStorage (cleared when the tab closes). The trade-off: script running on the page could read
 * them, so the hosting layer must send a strict Content-Security-Policy (see frontend/customHttp.yml) and the app
 * renders no untrusted HTML.
 */
const DOMAIN = (import.meta.env.VITE_COGNITO_DOMAIN as string | undefined)?.replace(/^https?:\/\//, '')
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined

export const authEnabled = Boolean(DOMAIN && CLIENT_ID)

interface Tokens {
  access: string
  refresh?: string
  expiresAt: number // epoch ms
}

const KEY = 'neerai.tokens'
const PKCE = 'neerai.pkce'

const redirectUri = () => `${window.location.origin}/`

function read(): Tokens | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Tokens) : null
  } catch {
    return null
  }
}
function write(t: Tokens | null) {
  try {
    if (t) sessionStorage.setItem(KEY, JSON.stringify(t))
    else sessionStorage.removeItem(KEY)
  } catch { /* storage unavailable: user will simply sign in again */ }
}

const b64url = (buf: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

function randomString(bytes = 32): string {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)))
}

export async function login(): Promise<void> {
  if (!authEnabled) return
  const verifier = randomString(48)
  const state = randomString(16)
  const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))
  try { sessionStorage.setItem(PKCE, JSON.stringify({ verifier, state })) } catch { /* ignore */ }
  const q = new URLSearchParams({
    response_type: 'code', client_id: CLIENT_ID!, redirect_uri: redirectUri(), scope: 'openid email',
    code_challenge: challenge, code_challenge_method: 'S256', state,
  })
  window.location.assign(`https://${DOMAIN}/oauth2/authorize?${q}`)
}

async function tokenRequest(body: Record<string, string>): Promise<Tokens | null> {
  const res = await fetch(`https://${DOMAIN}/oauth2/token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: CLIENT_ID!, ...body }),
  })
  if (!res.ok) return null
  const j = await res.json()
  return { access: j.access_token, refresh: j.refresh_token ?? body.refresh_token, expiresAt: Date.now() + (j.expires_in ?? 3600) * 1000 }
}

/** Completes the redirect from the hosted UI (?code=...&state=...). Returns true when a session was established. */
export async function handleCallback(): Promise<boolean> {
  if (!authEnabled) return false
  const p = new URLSearchParams(window.location.search)
  const code = p.get('code')
  if (!code) return false
  let saved: { verifier: string; state: string } | null = null
  try { saved = JSON.parse(sessionStorage.getItem(PKCE) ?? 'null'); sessionStorage.removeItem(PKCE) } catch { /* ignore */ }
  window.history.replaceState({}, '', window.location.pathname) // drop the one-time code from the address bar
  if (!saved || saved.state !== p.get('state')) return false // CSRF / stale-tab protection
  const t = await tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: redirectUri(), code_verifier: saved.verifier })
  write(t)
  return Boolean(t)
}

export function isSignedIn(): boolean {
  const t = read()
  return Boolean(t && (t.expiresAt > Date.now() || t.refresh))
}

let refreshing: Promise<Tokens | null> | null = null

/** A valid access token, refreshing it shortly before expiry; null if the session is gone (caller should sign in again). */
export async function getAccessToken(): Promise<string | null> {
  if (!authEnabled) return null
  const t = read()
  if (!t) return null
  if (t.expiresAt - Date.now() > 60_000) return t.access
  if (!t.refresh) { write(null); return null }
  refreshing ??= tokenRequest({ grant_type: 'refresh_token', refresh_token: t.refresh }).finally(() => { refreshing = null })
  const fresh = await refreshing
  write(fresh)
  return fresh?.access ?? null
}

export function logout(): void {
  write(null)
  if (!authEnabled) return
  const q = new URLSearchParams({ client_id: CLIENT_ID!, logout_uri: redirectUri() })
  window.location.assign(`https://${DOMAIN}/logout?${q}`)
}
