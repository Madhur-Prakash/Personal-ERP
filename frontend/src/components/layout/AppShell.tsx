import { Link, Outlet } from '@tanstack/react-router';
import {
  Bell,
  Boxes,
  Building2,
  ChevronDown,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  BarChart3,
  IndianRupee,
  ScanLine,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

import { CommandPalette } from '@/components/layout/CommandPalette';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/features/auth/AuthProvider';
import { cn } from '@/lib/cn';

interface NavItem {
  label: string;
  to: string;
  icon: typeof LayoutDashboard;
  /** Rendered but disabled until the owning stage lands. */
  stage?: number;
  /** Hidden entirely unless the caller holds this permission. */
  permission?: string;
}

/**
 * Navigation.
 *
 * Later-stage modules are listed but visibly disabled rather than omitted. It
 * sets the expectation of what this product is, and prevents the sidebar
 * lurching as stages ship. Each carries the stage that unlocks it.
 */
const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Overview',
    items: [{ label: 'Dashboard', to: '/', icon: LayoutDashboard }],
  },
  {
    title: 'Finance',
    items: [
      // First: for most users this is the only screen they open.
      { label: 'Billing', to: '/billing', icon: IndianRupee, permission: 'journal:read' },
      { label: 'Accounting', to: '/accounting', icon: Wallet, permission: 'account:read' },
      { label: 'Sales', to: '/invoices', icon: FileText, permission: 'invoice:read' },
      { label: 'Inventory', to: '/inventory', icon: Boxes, permission: 'inventory:read' },
      { label: 'Documents', to: '/documents', icon: ScanLine, permission: 'document:read' },
      { label: 'Analytics', to: '/analytics', icon: BarChart3, permission: 'report:read' },
    ],
  },
  {
    title: 'Intelligence',
    items: [{ label: 'AI Assistant', to: '/assistant', icon: Sparkles, stage: 6 }],
  },
  {
    title: 'Organization',
    items: [
      { label: 'Members', to: '/members', icon: Users, permission: 'member:read' },
      { label: 'Roles', to: '/roles', icon: ShieldCheck, permission: 'role:read' },
      { label: 'Audit log', to: '/audit', icon: FileText, permission: 'audit:read' },
      { label: 'Settings', to: '/settings', icon: Settings },
    ],
  },
];

export function AppShell() {
  const { user, signOut, can } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Cmd/Ctrl+K opens the palette from anywhere.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const organization = user?.active_organization;

  return (
    <div className="bg-canvas min-h-dvh">
      {/* Keyboard users land here first; it lets them jump the whole sidebar. */}
      <a
        href="#main-content"
        className="sr-only-focusable bg-primary text-primary-content fixed top-3 left-3 z-[60] rounded-md px-3 py-2 text-sm font-medium"
      >
        Skip to content
      </a>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />

      {/* ---- Sidebar ---- */}
      <aside
        className={cn(
          'border-border bg-surface fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r',
          'transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-quart)]',
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
        )}
        aria-label="Main navigation"
      >
        <div className="flex h-14 items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2">
            <span
              className="bg-primary text-primary-content flex h-7 w-7 items-center justify-center rounded-lg text-sm font-bold"
              aria-hidden
            >
              N
            </span>
            <span className="text-content text-[15px] font-semibold tracking-tight">
              Personal ERP
            </span>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Organization switcher */}
        {organization && (
          <div className="px-3 pb-3">
            <Link
              to="/settings"
              className="hover:bg-surface-hover border-border flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors"
            >
              <span
                className="bg-primary/12 text-primary flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[11px] font-bold"
                aria-hidden
              >
                {organization.name.slice(0, 2).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="text-content block truncate text-[13px] font-medium">
                  {organization.name}
                </span>
                <span className="text-content-muted block truncate text-[11px]">
                  {organization.role_name}
                </span>
              </span>
              <ChevronDown className="text-content-muted h-3.5 w-3.5 shrink-0" aria-hidden />
            </Link>
          </div>
        )}

        {/* Any click inside the nav closes the mobile drawer, which otherwise
            covers the page just navigated to. Handled here by delegation rather
            than in an effect on the pathname: setting state in an effect after
            render is an extra paint, and React flags it. */}
        <nav
          className="flex-1 space-y-5 overflow-y-auto px-3 pb-4"
          onClick={() => setMobileOpen(false)}
        >
          {NAV_SECTIONS.map((section) => {
            const visible = section.items.filter(
              (item) => !item.permission || can(item.permission),
            );
            if (visible.length === 0) return null;

            return (
              <div key={section.title}>
                <p className="text-content-muted px-2.5 pb-1.5 text-[10px] font-semibold tracking-wider uppercase">
                  {section.title}
                </p>
                <ul className="space-y-0.5">
                  {visible.map((item) => (
                    <li key={item.to}>
                      {item.stage ? (
                        // Not yet built. A disabled row with its stage number is
                        // more honest than a link to a 404.
                        <span
                          className="text-content-muted flex cursor-not-allowed items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] opacity-55"
                          title={`Arrives in Stage ${item.stage}`}
                        >
                          <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                          <span className="flex-1">{item.label}</span>
                          <Badge tone="neutral" className="text-[9px]">
                            S{item.stage}
                          </Badge>
                        </span>
                      ) : (
                        <Link
                          to={item.to}
                          className="text-content-secondary hover:bg-surface-hover hover:text-content flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors"
                          activeProps={{
                            className: 'bg-primary/10 text-primary hover:bg-primary/10',
                          }}
                          activeOptions={{ exact: item.to === '/' }}
                        >
                          <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                          {item.label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>

        {/* User */}
        {user && (
          <div className="border-border border-t p-3">
            <div className="flex items-center gap-2.5">
              <Avatar src={user.avatar_url} name={user.full_name} initials={user.initials} />
              <div className="min-w-0 flex-1">
                <p className="text-content truncate text-[13px] font-medium">{user.full_name}</p>
                <p className="text-content-muted truncate text-[11px]">{user.email}</p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => void signOut()}
                aria-label="Sign out"
                title="Sign out"
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </aside>

      {/* Scrim behind the mobile drawer */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* ---- Content ---- */}
      <div className="lg:pl-[248px]">
        <header className="glass border-border sticky top-0 z-20 flex h-14 items-center gap-3 border-b px-4 lg:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-4 w-4" />
          </Button>

          {/* Opens the palette. A button rather than a real input: it is a
              launcher, and a focusable text field here would swallow keystrokes
              meant for the page. */}
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="border-border bg-surface-sunken text-content-muted hover:bg-surface-hover hover:text-content-secondary flex h-8 max-w-72 flex-1 items-center gap-2 rounded-lg border px-2.5 text-[13px] transition-colors"
          >
            <Search className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="flex-1 text-left">Search or jump to…</span>
            <kbd className="border-border bg-surface text-content-muted hidden rounded border px-1.5 py-0.5 font-sans text-[10px] font-medium sm:inline-block">
              ⌘K
            </kbd>
          </button>

          <div className="flex-1" />

          <Button variant="ghost" size="icon" aria-label="Notifications" title="Notifications">
            <Bell className="h-4 w-4" />
          </Button>
          <ThemeToggle />
        </header>

        <main id="main-content" className="animate-fade-in">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/** Consistent page heading, used by every route inside the shell. */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-content text-[22px] leading-tight font-semibold tracking-[-0.025em]">
          {title}
        </h1>
        {description && <p className="text-content-muted mt-1 text-[13px]">{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Placeholder for a module that a later stage delivers. */
export function StagePlaceholder({
  title,
  description,
  stage,
}: {
  title: string;
  description: string;
  stage: number;
}) {
  return (
    <div className="p-6 lg:p-8">
      <PageHeader title={title} description={description} />
      <div className="border-border flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-20 text-center">
        <div
          className="bg-surface-sunken text-content-muted mb-4 flex h-12 w-12 items-center justify-center rounded-xl"
          aria-hidden
        >
          <Building2 className="h-5 w-5" />
        </div>
        <h2 className="text-content text-[15px] font-semibold">Arriving in Stage {stage}</h2>
        <p className="text-content-muted mt-1.5 max-w-md text-[13px] leading-relaxed">
          This module is part of the staged delivery plan. Stage 1 ships the foundation -
          authentication, organizations, roles, and the audit trail.
        </p>
      </div>
    </div>
  );
}
