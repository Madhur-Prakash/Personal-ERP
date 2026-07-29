import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from '@tanstack/react-router';

import { AppShell, StagePlaceholder } from '@/components/layout/AppShell';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { LoginPage } from '@/features/auth/LoginPage';
import {
  ForgotPasswordPage,
  ResetPasswordPage,
  VerifyEmailPage,
} from '@/features/auth/PasswordPages';
import { MagicLinkPage, MagicLinkVerifyPage, OtpPage } from '@/features/auth/PasswordlessPages';
import { RegisterPage } from '@/features/auth/RegisterPage';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { AcceptInvitePage } from '@/features/organizations/AcceptInvitePage';
import { AuditPage } from '@/features/organizations/AuditPage';
import { MembersPage } from '@/features/organizations/MembersPage';
import { RolesPage } from '@/features/organizations/RolesPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { NotFoundPage } from '@/routes/NotFoundPage';
import { RouteErrorPage } from '@/routes/RouteErrorPage';

/**
 * Routing.
 *
 * Code-based rather than file-based: the route tree is small, and having it in
 * one file makes the auth boundary — which routes are public and which are
 * guarded — reviewable at a glance instead of inferred from a directory layout.
 *
 * Auth state is threaded through the router `context` so guards can run in
 * `beforeLoad`, before a protected component mounts. Reading it from a hook
 * inside the component would render the page first and redirect after, briefly
 * flashing content the user is not entitled to.
 */

/*
 * `throw redirect(...)` is TanStack Router's documented way to redirect from a
 * `beforeLoad` guard — the router catches the thrown descriptor as control flow.
 * It is not an Error subclass, so `only-throw-error` is disabled for this file
 * rather than working around the framework's intended API.
 */
/* eslint-disable @typescript-eslint/only-throw-error */

export interface RouterContext {
  isAuthenticated: boolean;
  /** True while the initial session restore is in flight. */
  isLoading: boolean;
  hasPermission: (permission: string) => boolean;
}

// `createRootRouteWithContext` is curried: the first call fixes the context
// type so every child route's `beforeLoad` sees it, which a plain
// `createRootRoute` generic does not do.
const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
  errorComponent: RouteErrorPage,
  notFoundComponent: NotFoundPage,
});

// ---------------------------------------------------------------------------
// Public routes
// ---------------------------------------------------------------------------
/**
 * Guard for the sign-in screens: an already-authenticated user is sent to the
 * dashboard rather than shown a login form they do not need.
 *
 * The `isLoading` check matters. During the initial refresh we do not yet know
 * whether there is a session, and redirecting on `!isAuthenticated` would bounce
 * a signed-in user to `/login` on every reload.
 */
function redirectIfAuthenticated({ context }: { context: RouterContext }) {
  if (!context.isLoading && context.isAuthenticated) {
    throw redirect({ to: '/' });
  }
}

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  beforeLoad: redirectIfAuthenticated,
  component: LoginPage,
  // Return type uses `?`, not `| undefined`. A required key whose type includes
  // undefined still counts as required, which would force every `<Link to="/login">`
  // in the app to pass an explicit `search` prop.
  validateSearch: (search: Record<string, unknown>): { redirect?: string } =>
    typeof search['redirect'] === 'string' ? { redirect: search['redirect'] } : {},
});

const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/register',
  beforeLoad: redirectIfAuthenticated,
  component: RegisterPage,
  validateSearch: (search: Record<string, unknown>): { invitation?: string } =>
    typeof search['invitation'] === 'string' ? { invitation: search['invitation'] } : {},
});

const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/forgot-password',
  beforeLoad: redirectIfAuthenticated,
  component: ForgotPasswordPage,
});

const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/reset-password',
  component: ResetPasswordPage,
  validateSearch: (search: Record<string, unknown>): { token?: string } =>
    typeof search['token'] === 'string' ? { token: search['token'] } : {},
});

const verifyEmailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/verify-email',
  component: VerifyEmailPage,
  validateSearch: (search: Record<string, unknown>): { token?: string } =>
    typeof search['token'] === 'string' ? { token: search['token'] } : {},
});

const magicLinkRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/magic-link',
  beforeLoad: redirectIfAuthenticated,
  component: MagicLinkPage,
});

const magicLinkVerifyRoute = createRoute({
  getParentRoute: () => rootRoute,
  // A separate path from the request page so the emailed link cannot be
  // confused with the form, and so this one is never guarded.
  path: '/magic-link/verify',
  component: MagicLinkVerifyPage,
  validateSearch: (search: Record<string, unknown>): { token?: string } =>
    typeof search['token'] === 'string' ? { token: search['token'] } : {},
});

const otpRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/otp',
  beforeLoad: redirectIfAuthenticated,
  component: OtpPage,
});

const acceptInviteRoute = createRoute({
  getParentRoute: () => rootRoute,
  // Deliberately unguarded: the recipient may or may not have an account, and
  // the page handles both.
  path: '/accept-invite',
  component: AcceptInvitePage,
  validateSearch: (search: Record<string, unknown>): { token?: string } =>
    typeof search['token'] === 'string' ? { token: search['token'] } : {},
});

// ---------------------------------------------------------------------------
// Authenticated routes
// ---------------------------------------------------------------------------
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  beforeLoad: ({ context, location }) => {
    // Do nothing until the session restore settles — see the note above.
    if (context.isLoading) return;

    if (!context.isAuthenticated) {
      throw redirect({
        to: '/login',
        // Preserve the intended destination so sign-in returns the user there
        // rather than dumping them on the dashboard.
        search: { redirect: location.href },
        replace: true,
      });
    }
  },
  component: AppShell,
  pendingComponent: PageSkeleton,
});

const dashboardRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/',
  component: DashboardPage,
});

const membersRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/members',
  component: MembersPage,
});

const rolesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/roles',
  component: RolesPage,
});

const auditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/audit',
  component: AuditPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/settings',
  component: SettingsPage,
});

// Placeholders for later stages. Registered so the navigation links resolve
// instead of 404-ing, and so the delivery plan is visible in the product.
const accountingRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/accounting',
  component: () => (
    <StagePlaceholder
      title="Accounting"
      description="Chart of accounts, journals, ledgers, and financial statements."
      stage={2}
    />
  ),
});

const invoicesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/invoices',
  component: () => (
    <StagePlaceholder
      title="Invoices"
      description="Quotations, sales orders, invoices, and payments."
      stage={3}
    />
  ),
});

const inventoryRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/inventory',
  component: () => (
    <StagePlaceholder
      title="Inventory"
      description="Warehouses, stock movements, and barcode support."
      stage={4}
    />
  ),
});

const assistantRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/assistant',
  component: () => (
    <StagePlaceholder
      title="AI Assistant"
      description="Ask questions about your business in plain language."
      stage={6}
    />
  ),
});

// ---------------------------------------------------------------------------
// Tree
// ---------------------------------------------------------------------------
const routeTree = rootRoute.addChildren([
  loginRoute,
  registerRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  verifyEmailRoute,
  magicLinkRoute,
  magicLinkVerifyRoute,
  otpRoute,
  acceptInviteRoute,
  appRoute.addChildren([
    dashboardRoute,
    membersRoute,
    rolesRoute,
    auditRoute,
    settingsRoute,
    accountingRoute,
    invoicesRoute,
    inventoryRoute,
    assistantRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  // Real values are injected by <RouterProvider> in App.tsx; these are only
  // placeholders so the type checks before the provider mounts.
  context: {
    isAuthenticated: false,
    isLoading: true,
    hasPermission: () => false,
  } satisfies RouterContext,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
});

// Gives `<Link to="...">` autocompletion and compile-time checking of paths.
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
