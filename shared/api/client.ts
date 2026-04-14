import { Platform } from 'react-native';
import { auth } from '../config/firebaseConfig';
import SpinrConfig from '../config/spinr.config';

const isFirebaseConfigured = typeof auth.onAuthStateChanged === 'function';

const API_URL = SpinrConfig.backendUrl;

if (__DEV__) console.log('API Client configured with URL:', API_URL);

// Request timeout in milliseconds
const REQUEST_TIMEOUT = 15000;

// Helper function to wrap fetch with timeout
const fetchWithTimeout = async (
  url: string,
  options: RequestInit & { timeout?: number } = {}
): Promise<Response> => {
  const { timeout = REQUEST_TIMEOUT, ...fetchOptions } = options;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      const timeoutError: any = new Error('Network request timed out');
      timeoutError.name = 'TimeoutError';
      throw timeoutError;
    }
    throw error;
  }
};

// ── In-memory token ──
// SecureStore can be unreliable on some devices/emulators (writes succeed but
// reads return null in the same session). We keep a module-level copy so that
// all API calls within the current app session have instant access to the
// token regardless of SecureStore's state.
let _inMemoryToken: string | null = null;

export function setInMemoryToken(token: string | null) {
  _inMemoryToken = token;
  if (__DEV__) console.log('[API] In-memory token:', token ? 'SET' : 'CLEARED');
}

// Helper to get stored token
const getStoredToken = async (): Promise<string | null> => {
  try {
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      return sessionStorage.getItem('auth_token');
    } else {
      const SecureStore = require('expo-secure-store');
      const token = await SecureStore.getItemAsync('auth_token');
      return token;
    }
  } catch (e: any) {
    console.error('[API] SecureStore error:', e?.message || e);
    return null;
  }
};

// Helper to get auth header — checks in-memory first, then SecureStore
const getAuthHeader = async (): Promise<string | null> => {
  try {
    // 1. In-memory token (most reliable — set during current session)
    if (_inMemoryToken) {
      return _inMemoryToken;
    }
    // 2. Firebase token
    if (isFirebaseConfigured && auth.currentUser) {
      return await auth.currentUser.getIdToken();
    }
    // 3. SecureStore fallback (for cold starts where in-memory is empty)
    return await getStoredToken();
  } catch (error: any) {
    console.error('[API] Error getting auth token:', error?.message || error);
    return null;
  }
};

// ─── Error extraction + debug log ring buffer ────────────────────────
// The backend returns errors in a few shapes depending on the handler:
//   - HTTPException (via http_exception_handler): { detail, error:{message} }
//   - Unhandled Exception (via general_exception_handler): { error:{message,detail,request_id,exception_type} }
//   - FastAPI RequestValidationError: { detail: [...] }  (array of field errors)
//   - Plain text "Internal Server Error" (pre-handler-register crash): body not JSON
// This helper returns a human-readable message from any of them.
const extractErrorMessage = (data: any): string => {
  if (!data) return 'Request failed';
  // Plain FastAPI HTTPException shape: detail is a string
  if (typeof data.detail === 'string') return data.detail;
  // RequestValidationError: detail is an array of {loc, msg, type}
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d: any) => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
      .join('; ');
  }
  // Our custom handlers: structured error object
  if (data.error?.message) return data.error.message;
  if (data.error?.detail) return data.error.detail;
  return 'Request failed';
};

// In-memory ring buffer of recent API errors so we can surface them in a
// debug screen (or just logcat them) without the user having to reproduce
// on-device with Metro attached. Capped at 50 entries.
export interface ApiErrorLogEntry {
  ts: string;
  method: string;
  url: string;
  status: number;
  message: string;
  request_id?: string;
  exception_type?: string;
  data?: any;
}
const _errorLog: ApiErrorLogEntry[] = [];
const MAX_ERROR_LOG = 50;
export const getApiErrorLog = (): ApiErrorLogEntry[] => [..._errorLog];
export const clearApiErrorLog = (): void => { _errorLog.length = 0; };
const recordApiError = (entry: ApiErrorLogEntry) => {
  _errorLog.push(entry);
  if (_errorLog.length > MAX_ERROR_LOG) _errorLog.shift();
  // Also console.log so it shows up in Metro / Railway mirror. Tagged so
  // it's easy to grep. Keep this concise — full data is in the buffer.
  console.log(
    `[API-ERR] ${entry.method} ${entry.url} → ${entry.status} | ${entry.message}` +
    (entry.request_id ? ` | req=${entry.request_id}` : ''),
  );
};

const handleApiError = async (response: Response, method: string, url: string): Promise<never> => {
  const errorData = await response.json().catch(() => ({}));
  const message = extractErrorMessage(errorData);
  const requestId = response.headers.get('x-request-id') || errorData?.error?.request_id;
  const exceptionType = errorData?.error?.exception_type;
  recordApiError({
    ts: new Date().toISOString(),
    method,
    url,
    status: response.status,
    message,
    request_id: requestId || undefined,
    exception_type: exceptionType,
    data: errorData,
  });

  // Session teardown on 401 is now driven from the verb-specific
  // wrappers (get/post/put/patch/delete) so that they can first attempt
  // a refresh-token exchange + retry before giving up.  This function
  // stays a dumb error thrower.
  const error: any = new Error(message);
  error.response = { data: errorData, status: response.status };
  error.requestId = requestId;
  throw error;
};

// ── On-401 refresh: single-flight guard ──
// Many concurrent in-flight requests will all see the same 401 when the
// access token expires.  Without a shared promise, every one of them
// kicks off its own POST /auth/refresh; the first succeeds and rotates
// the refresh token, and the rest fail with "refresh token revoked"
// because the chain only keeps the newest in `refresh_tokens.replaced_by`.
// We cache the in-flight refresh promise so a single exchange services
// every concurrent 401.
let _refreshInFlight: Promise<string | null> | null = null;

async function _runRefresh(): Promise<string | null> {
  try {
    const { useAuthStore } = require('../store/authStore');
    return await useAuthStore.getState().refreshAccessToken();
  } catch (e) {
    if (__DEV__) console.log('[API] refresh path threw:', e);
    return null;
  }
}

async function refreshAccessTokenSingleFlight(): Promise<string | null> {
  if (_refreshInFlight) return _refreshInFlight;
  _refreshInFlight = _runRefresh().finally(() => {
    _refreshInFlight = null;
  });
  return _refreshInFlight;
}

async function clearSessionAndLogout(): Promise<void> {
  // Used when refresh is unavailable or has failed — we can't talk to
  // the API as this user any more, so tear down the session and let the
  // layout effects bounce to /login.
  console.log('[API] 401 Unauthorized — clearing session');
  setInMemoryToken(null);
  try {
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
      sessionStorage.removeItem('auth_token');
      sessionStorage.removeItem('auth_refresh_token');
      sessionStorage.removeItem('auth_access_expires_at');
    } else {
      const SecureStore = require('expo-secure-store');
      await SecureStore.deleteItemAsync('auth_token');
      await SecureStore.deleteItemAsync('auth_refresh_token');
      await SecureStore.deleteItemAsync('auth_access_expires_at');
    }
  } catch { /* best-effort clear */ }

  try {
    const { useAuthStore } = require('../store/authStore');
    useAuthStore.getState().logout();
  } catch { /* store may not be initialized yet on cold start */ }
}

// Build a retry-able request executor.  Each verb wrapper (get/post/...)
// calls `doRequest(token)` once to build and send the request.  If that
// returns a 401, we try exactly ONE refresh-token exchange; on success
// we re-run doRequest(newToken); on failure we tear down the session
// and throw the original 401 error.
async function withRefreshRetry<T>(
  method: string,
  url: string,
  doRequest: (token: string | null) => Promise<Response>,
): Promise<{ data: T; status: number }> {
  let token = await getAuthHeader();
  let response = await doRequest(token);
  if (response.status === 401) {
    // Skip refresh for the refresh endpoint itself — otherwise a bad
    // refresh token triggers an infinite loop.  `/auth/logout` also
    // shouldn't retry: the server revokes on the first call regardless
    // of whether the access token is still valid.
    const isAuthEndpoint = url.startsWith('/auth/refresh') || url.startsWith('/auth/logout');
    if (!isAuthEndpoint) {
      const refreshed = await refreshAccessTokenSingleFlight();
      if (refreshed) {
        if (__DEV__) console.log('[API] 401 → refresh → retry', method, url);
        response = await doRequest(refreshed);
      }
    }
  }
  if (!response.ok) {
    if (response.status === 401) {
      // Refresh either wasn't attempted, returned null, or the retry
      // still failed.  Wipe the session so the UI redirects to login.
      await clearSessionAndLogout();
    }
    await handleApiError(response, method, url);
  }
  const parsed = method === 'DELETE'
    ? await response.json().catch(() => ({} as T))
    : await response.json();
  return { data: parsed as T, status: response.status };
}

// Build the Authorization header for `token` (null → no header).  When
// the caller passed explicit headers (e.g. initialize() sending a
// stored token before the store has hydrated), those win — we only
// inject Authorization when it isn't already set.
function buildHeaders(
  token: string | null,
  overrides?: Record<string, string>,
  contentType: string | null = 'application/json',
): Record<string, string> {
  const headers: Record<string, string> = {};
  if (contentType) headers['Content-Type'] = contentType;
  if (overrides) Object.assign(headers, overrides);
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// Custom API client using fetch
const client = {
  async get<T = any>(url: string, config?: { headers?: Record<string, string> }): Promise<{ data: T; status: number }> {
    return withRefreshRetry<T>('GET', url, (token) =>
      fetchWithTimeout(`${API_URL}/api/v1${url}`, {
        method: 'GET',
        headers: buildHeaders(token, config?.headers),
      }),
    );
  },

  async post<T = any>(url: string, body?: any, config?: { headers?: Record<string, string> }): Promise<{ data: T; status: number }> {
    return withRefreshRetry<T>('POST', url, (token) =>
      fetchWithTimeout(`${API_URL}/api/v1${url}`, {
        method: 'POST',
        headers: buildHeaders(token, config?.headers),
        body: body ? JSON.stringify(body) : undefined,
      }),
    );
  },

  async put<T = any>(url: string, body?: any, config?: { headers?: Record<string, string> }): Promise<{ data: T; status: number }> {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    return withRefreshRetry<T>('PUT', url, (token) =>
      fetchWithTimeout(`${API_URL}/api/v1${url}`, {
        method: 'PUT',
        // FormData: let fetch set the multipart boundary — pass null contentType.
        headers: buildHeaders(token, config?.headers, isFormData ? null : 'application/json'),
        body: body === undefined || body === null ? undefined : (isFormData ? body : JSON.stringify(body)),
      }),
    );
  },

  async patch<T = any>(url: string, body?: any, config?: { headers?: Record<string, string> }): Promise<{ data: T; status: number }> {
    return withRefreshRetry<T>('PATCH', url, (token) =>
      fetchWithTimeout(`${API_URL}/api/v1${url}`, {
        method: 'PATCH',
        headers: buildHeaders(token, config?.headers),
        body: body ? JSON.stringify(body) : undefined,
      }),
    );
  },

  async delete<T = any>(url: string, config?: { headers?: Record<string, string> }): Promise<{ data: T; status: number }> {
    return withRefreshRetry<T>('DELETE', url, (token) =>
      fetchWithTimeout(`${API_URL}/api/v1${url}`, {
        method: 'DELETE',
        headers: buildHeaders(token, config?.headers),
      }),
    );
  },
};

export default client;
