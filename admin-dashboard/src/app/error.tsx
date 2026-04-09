'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Application error:', error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 text-center">
      <div>
        <h2 className="text-2xl font-bold text-destructive mb-2">Something went wrong</h2>
        <p className="text-muted-foreground mb-4">
          An unexpected error occurred. Our team has been notified.
        </p>
        {error.digest && (
          <p className="text-xs text-muted-foreground font-mono bg-muted px-2 py-1 rounded">
            Error ID: {error.digest}
          </p>
        )}
      </div>
      <div className="flex gap-3">
        <Button onClick={reset} variant="outline">Try again</Button>
        <Button onClick={() => window.location.href = '/dashboard'}>Go to Dashboard</Button>
      </div>
    </div>
  );
}
