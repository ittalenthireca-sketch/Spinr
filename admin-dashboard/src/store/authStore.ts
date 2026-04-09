import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

interface User {
    id: string;
    phone?: string;
    email?: string;
    first_name?: string;
    last_name?: string;
    role: string;
    modules?: string[];
    profile_complete?: boolean;
}

interface AuthState {
    user: User | null;
    token: string | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    lastActivity: number;
    setUser: (user: User | null) => void;
    setToken: (token: string | null) => void;
    setLoading: (loading: boolean) => void;
    logout: () => void;
    checkAuth: () => Promise<void>;
    updateActivity: () => void;
    checkSessionTimeout: () => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => ({
            user: null,
            token: null,
            isAuthenticated: false,
            isLoading: true,
            lastActivity: Date.now(),

            setUser: (user) => {
                set({
                    user,
                    isAuthenticated: !!user,
                    isLoading: false
                });
            },

            setToken: (token) => {
                set({ token });
            },

            setLoading: (loading) => {
                set({ isLoading: loading });
            },

            logout: () => {
                set({
                    user: null,
                    token: null,
                    isAuthenticated: false,
                    isLoading: false
                });
            },

            updateActivity: () => set({ lastActivity: Date.now() }),

            checkSessionTimeout: () => {
                const { lastActivity, logout } = get();
                if (Date.now() - lastActivity > SESSION_TIMEOUT_MS) {
                    logout();
                }
            },

            checkAuth: async () => {
                const token = get().token;
                if (!token) {
                    set({ isLoading: false });
                    return;
                }

                try {
                    const res = await fetch(`${API_BASE}/api/admin/auth/session`, {
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json',
                        },
                    });

                    if (res.ok) {
                        const data = await res.json();
                        if (data.authenticated && data.user) {
                            set({
                                user: data.user,
                                isAuthenticated: true,
                                isLoading: false
                            });
                        } else {
                            get().logout();
                        }
                    } else {
                        get().logout();
                    }
                } catch (error) {
                    console.error('Auth check failed:', error);
                    get().logout();
                }
            },
        }),
        {
            name: 'auth-storage',
            storage: createJSONStorage(() => localStorage),
            partialize: (state) => ({
                token: state.token,
                user: state.user,
                isAuthenticated: state.isAuthenticated,
            }),
            onRehydrateStorage: () => (state) => {
                // Check auth when store is rehydrated from localStorage
                if (state) {
                    state.checkAuth();
                }
            },
        }
    )
);

export const startSessionTimer = (): (() => void) => {
    const interval = setInterval(() => {
        useAuthStore.getState().checkSessionTimeout();
    }, 60_000);
    return () => clearInterval(interval);
};