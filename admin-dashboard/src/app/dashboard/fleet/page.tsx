"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, RefreshCw, Car, Radio, Navigation } from "lucide-react";

// Dynamic import — Leaflet must be client-side only
const DriverMap = dynamic(() => import("@/components/driver-map"), {
    ssr: false,
    loading: () => (
        <div className="w-full h-[600px] bg-muted animate-pulse rounded-lg flex items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
    ),
});

const POLL_INTERVAL_MS = 10_000; // 10 seconds

async function fetchOnlineDrivers(): Promise<any[]> {
    const { useAuthStore } = await import("@/store/authStore");
    const token = useAuthStore.getState().token;
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

    const res = await fetch(`${API_BASE}/api/v1/admin/drivers?is_online=true&limit=500`, {
        headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
    });

    if (!res.ok) throw new Error(`Failed to fetch drivers: ${res.status}`);
    const data = await res.json();
    // API returns { drivers: [...] } or array directly
    return Array.isArray(data) ? data : (data.drivers ?? data.items ?? []);
}

export default function FleetMapPage() {
    const [drivers, setDrivers] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [error, setError] = useState<string | null>(null);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const load = useCallback(async (isManual = false) => {
        if (isManual) setRefreshing(true);
        setError(null);
        try {
            const data = await fetchOnlineDrivers();
            setDrivers(data);
            setLastUpdated(new Date());
        } catch (err: any) {
            setError(err.message || "Failed to load drivers");
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, []);

    // Initial load + polling
    useEffect(() => {
        load();
        intervalRef.current = setInterval(() => load(), POLL_INTERVAL_MS);
        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
        };
    }, [load]);

    // Derived stats
    const onTrip = drivers.filter((d) => d.current_ride_id || d.status === "on_trip").length;
    const idle = drivers.filter((d) => !d.current_ride_id && d.status !== "on_trip").length;

    const formatTime = (date: Date) =>
        date.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Fleet Map</h1>
                    <p className="text-muted-foreground mt-1">
                        Live positions of all online drivers — refreshes every 10 seconds.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground hidden sm:inline">
                            Updated {formatTime(lastUpdated)}
                        </span>
                    )}
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => load(true)}
                        disabled={refreshing || loading}
                    >
                        <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                        Refresh
                    </Button>
                </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Online Drivers</CardTitle>
                        <Radio className="h-4 w-4 text-green-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{drivers.length}</div>
                        <p className="text-xs text-muted-foreground">Currently broadcasting location</p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">On Trip</CardTitle>
                        <Car className="h-4 w-4 text-blue-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{onTrip}</div>
                        <p className="text-xs text-muted-foreground">
                            {drivers.length > 0
                                ? `${((onTrip / drivers.length) * 100).toFixed(0)}% utilisation`
                                : "No drivers online"}
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Idle</CardTitle>
                        <Navigation className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{idle}</div>
                        <p className="text-xs text-muted-foreground">Available for dispatch</p>
                    </CardContent>
                </Card>
            </div>

            {/* Map */}
            <Card>
                <CardContent className="p-0 overflow-hidden rounded-lg">
                    {error ? (
                        <div className="h-[600px] flex flex-col items-center justify-center gap-3 text-destructive">
                            <p className="font-medium">{error}</p>
                            <Button variant="outline" size="sm" onClick={() => load(true)}>
                                Retry
                            </Button>
                        </div>
                    ) : loading ? (
                        <div className="h-[600px] flex items-center justify-center bg-muted animate-pulse">
                            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                        </div>
                    ) : (
                        <DriverMap drivers={drivers} />
                    )}
                </CardContent>
            </Card>

            {/* Live indicator */}
            <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
                <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                </span>
                Live — auto-refreshes every 10 seconds
            </div>
        </div>
    );
}
