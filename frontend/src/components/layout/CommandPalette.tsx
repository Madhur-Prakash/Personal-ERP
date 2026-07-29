import { useNavigate } from '@tanstack/react-router';
import { Command } from 'cmdk';
import {
  Building2,
  FileText,
  LayoutDashboard,
  LogOut,
  Moon,
  Monitor,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Users,
} from 'lucide-react';
import { useEffect } from 'react';

import { useAuth } from '@/features/auth/AuthProvider';
import { useTheme } from '@/features/theme/ThemeProvider';

/**
 * The command palette.
 *
 * A keyboard-driven launcher is core navigation here, not a power-user extra: the
 * people running this are in their books all day, and reaching for a mouse to
 * change screens is the slowest part of that. It is wired up in Stage 1 with
 * navigation, theme, and organization switching; Stage 6 adds natural-language
 * actions to the same surface, which is why it is built as an extensible list of
 * groups rather than a fixed menu.
 *
 * Permission-gated entries are filtered out, not disabled - offering a command
 * that will 403 is worse than not offering it.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { user, signOut, switchOrganization, can } = useAuth();
  const { setTheme } = useTheme();

  // Lock body scroll while open, or the page scrolls behind the dialog.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  function run(action: () => void) {
    onOpenChange(false);
    // Deferred a frame so the dialog unmounts before navigation, avoiding a
    // visible flash of the palette over the new route.
    requestAnimationFrame(action);
  }

  if (!open) return null;

  const otherOrganizations = (user?.organizations ?? []).filter(
    (organization) => organization.id !== user?.active_organization?.id,
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div
        className="animate-fade-in absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
        aria-hidden
      />

      <Command
        label="Command palette"
        className="bg-surface-raised border-border animate-slide-up relative w-full max-w-lg overflow-hidden rounded-xl border shadow-xl"
        loop
      >
        <div className="border-border flex items-center gap-2.5 border-b px-4">
          <Search className="text-content-muted h-4 w-4 shrink-0" aria-hidden />
          <Command.Input
            autoFocus
            placeholder="Search or run a command…"
            className="text-content placeholder:text-content-muted h-12 flex-1 bg-transparent text-sm outline-none"
          />
          <kbd className="border-border text-content-muted rounded border px-1.5 py-0.5 text-[10px] font-medium">
            ESC
          </kbd>
        </div>

        <Command.List className="max-h-[52vh] overflow-y-auto p-2">
          <Command.Empty className="text-content-muted py-8 text-center text-[13px]">
            No results found.
          </Command.Empty>

          <Group heading="Navigate">
            <Item
              icon={LayoutDashboard}
              label="Dashboard"
              onSelect={() => run(() => void navigate({ to: '/' }))}
            />
            {can('member:read') && (
              <Item
                icon={Users}
                label="Members"
                onSelect={() => run(() => void navigate({ to: '/members' }))}
              />
            )}
            {can('role:read') && (
              <Item
                icon={ShieldCheck}
                label="Roles and permissions"
                onSelect={() => run(() => void navigate({ to: '/roles' }))}
              />
            )}
            {can('audit:read') && (
              <Item
                icon={FileText}
                label="Audit log"
                onSelect={() => run(() => void navigate({ to: '/audit' }))}
              />
            )}
            <Item
              icon={Settings}
              label="Settings"
              onSelect={() => run(() => void navigate({ to: '/settings' }))}
            />
          </Group>

          {otherOrganizations.length > 0 && (
            <Group heading="Switch organization">
              {otherOrganizations.map((organization) => (
                <Item
                  key={organization.id}
                  icon={Building2}
                  label={organization.name}
                  hint={organization.role_name}
                  onSelect={() => run(() => void switchOrganization(organization.id))}
                />
              ))}
            </Group>
          )}

          <Group heading="Appearance">
            <Item icon={Sun} label="Light theme" onSelect={() => run(() => setTheme('light'))} />
            <Item icon={Moon} label="Dark theme" onSelect={() => run(() => setTheme('dark'))} />
            <Item
              icon={Monitor}
              label="Match system theme"
              onSelect={() => run(() => setTheme('system'))}
            />
          </Group>

          <Group heading="Account">
            <Item icon={LogOut} label="Sign out" onSelect={() => run(() => void signOut())} />
          </Group>
        </Command.List>
      </Command>
    </div>
  );
}

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:text-content-muted mb-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:uppercase"
    >
      {children}
    </Command.Group>
  );
}

function Item({
  icon: Icon,
  label,
  hint,
  onSelect,
}: {
  icon: typeof LayoutDashboard;
  label: string;
  hint?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="text-content-secondary data-[selected=true]:bg-surface-hover data-[selected=true]:text-content flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px]"
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="flex-1">{label}</span>
      {hint && <span className="text-content-muted text-[11px]">{hint}</span>}
    </Command.Item>
  );
}
