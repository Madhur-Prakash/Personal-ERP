import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { useMemo } from 'react';
import { Toaster } from 'sonner';
import { AuthProvider, useAuth } from '@/features/auth/AuthProvider';
import { ThemeProvider, useTheme } from '@/features/theme/ThemeProvider';
import { ApiError } from '@/lib/api';
import { router } from '@/routes/router';

/**
 * The query client.
 *
 * Built once at module scope, not inside a component - a client recreated on
 * render would discard the whole cache on every state change.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data is considered fresh for 30s. Long enough to make navigating back to
      // a page instant, short enough that an ERP does not show stale figures.
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      // Refetching on every window focus is jarring in a data-entry app, where
      // the user alt-tabs to a spreadsheet constantly.
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry a client error: a 403 or 404 will not resolve itself, and
        // retrying an auth failure just burns the rate limit.
        if (error instanceof ApiError && !error.isRetryable) return false;
        return failureCount < 2;
      },
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
    mutations: {
      // Mutations are never retried automatically. A retried POST can duplicate
      // an invoice, and no accounting system should risk that silently.
      retry: false,
    },
  },
});

/**
 * Bridges auth state into the router's context.
 *
 * The router needs auth state in `beforeLoad` so guards run *before* a protected
 * component mounts, and React context is not reachable from there. Passing it as
 * router context is the supported way to close that gap.
 */
function RouterBridge() {
  const { isAuthenticated, isLoading, can } = useAuth();

  const context = useMemo(
    () => ({ isAuthenticated, isLoading, hasPermission: can }),
    [isAuthenticated, isLoading, can],
  );

  return <RouterProvider router={router} context={context} />;
}

/** Toasts, themed to match the app rather than fighting it. */
function AppToaster() {
  const { resolvedTheme } = useTheme();

  return (
    <Toaster
      theme={resolvedTheme}
      position="bottom-right"
      closeButton
      richColors={false}
      toastOptions={{
        style: {
          background: 'var(--surface-raised)',
          border: '1px solid var(--border)',
          color: 'var(--content)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          fontSize: '13px',
        },
      }}
    />
  );
}

export function App() {
  return (
    // Order matters: QueryClientProvider is outermost because AuthProvider uses
    // `useQueryClient` to clear the cache on sign-out. ThemeProvider wraps the
    // toaster so it can read the resolved theme.
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <RouterBridge />
          <AppToaster />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
