'use client';

import { useEffect } from 'react';
import { startSessionTimer, useAuthStore } from '@/store/authStore';

export function SessionManager() {
  useEffect(() => {
    const cleanup = startSessionTimer();
    return cleanup;
  }, []);

  const updateActivity = () => useAuthStore.getState().updateActivity();

  return (
    <div
      className="contents"
      onClick={updateActivity}
      onMouseMove={updateActivity}
      onKeyDown={updateActivity}
    />
  );
}
