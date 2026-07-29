import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthProvider';
import { organizationsApi } from '@/features/organizations/api';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';

/**
 * Role editor.
 *
 * The permission picker is built from the server's catalogue
 * (`/roles/permissions`) rather than a hard-coded list, so it can never offer a
 * permission the backend does not enforce, or omit one it does.
 */
export function RolesPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string>();

  const { data: roles, isLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: organizationsApi.listRoles,
  });

  const { data: catalogue } = useQuery({
    queryKey: ['permission-catalogue'],
    queryFn: organizationsApi.permissionCatalogue,
    staleTime: 60 * 60 * 1000, // the catalogue only changes on deploy
  });

  const create = useMutation({
    mutationFn: () =>
      organizationsApi.createRole({
        name: name.trim(),
        permissions: [...selected],
      }),
    onSuccess: (role) => {
      toast.success(`Role "${role.name}" created`);
      setCreating(false);
      setName('');
      setSelected(new Set());
      setError(undefined);
      void queryClient.invalidateQueries({ queryKey: ['roles'] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : 'Could not create the role');
    },
  });

  const remove = useMutation({
    mutationFn: organizationsApi.deleteRole,
    onSuccess: () => {
      toast.success('Role deleted');
      void queryClient.invalidateQueries({ queryKey: ['roles'] });
    },
    onError: (err) => {
      // The server refuses to delete a role people still hold, and its message
      // names the count - surface it verbatim rather than paraphrasing.
      toast.error(err instanceof ApiError ? err.message : 'Could not delete the role');
    },
  });

  function togglePermission(slug: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  function toggleGroup(slugs: string[], allSelected: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const slug of slugs) {
        if (allSelected) next.delete(slug);
        else next.add(slug);
      }
      return next;
    });
  }

  return (
    <div>
      <PageHeader
        title="Roles and permissions"
        description="Roles bundle permissions. Built-in roles cannot be renamed or deleted, but their permissions can be adjusted."
        action={
          can('role:create') && !creating ? (
            <Button leftIcon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              New role
            </Button>
          ) : undefined
        }
      />

      {/* ---- Create ---- */}
      {creating && (
        <Card className="mb-4">
          <CardHeader
            title="Create a role"
            description="Pick a name, then choose exactly what it can do."
            action={
              <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            }
          />
          <CardBody className="space-y-5">
            <div className="max-w-sm">
              <Input
                label="Role name"
                placeholder="e.g. Invoice Clerk"
                value={name}
                onChange={(event) => setName(event.target.value)}
                error={error}
                autoFocus
              />
            </div>

            {catalogue ? (
              <div className="space-y-4">
                {catalogue.groups.map((group) => {
                  const slugs = group.permissions.map((p) => p.slug);
                  const allSelected = slugs.every((slug) => selected.has(slug));

                  return (
                    <fieldset key={group.key} className="border-border rounded-lg border p-4">
                      <legend className="flex items-center gap-2 px-1.5">
                        <span className="text-content text-[13px] font-semibold">
                          {group.label}
                        </span>
                        <button
                          type="button"
                          className="text-primary text-[11px] hover:underline"
                          onClick={() => toggleGroup(slugs, allSelected)}
                        >
                          {allSelected ? 'Clear' : 'Select all'}
                        </button>
                      </legend>
                      <p className="text-content-muted mb-3 text-[12px]">{group.description}</p>

                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {group.permissions.map((permission) => (
                          <label
                            key={permission.slug}
                            className="hover:bg-surface-hover flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[12px]"
                          >
                            <input
                              type="checkbox"
                              checked={selected.has(permission.slug)}
                              onChange={() => togglePermission(permission.slug)}
                              className="border-border text-primary focus:ring-ring/30 h-3.5 w-3.5 rounded"
                            />
                            <span className="text-content-secondary flex-1 truncate">
                              {permission.action}
                            </span>
                            <code className="text-content-muted text-[10px]">
                              {permission.resource}
                            </code>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  );
                })}
              </div>
            ) : (
              <Skeleton className="h-48 rounded-lg" />
            )}

            <div className="flex items-center gap-3">
              <Button
                loading={create.isPending}
                disabled={!name.trim() || selected.size === 0}
                onClick={() => {
                  if (!name.trim()) {
                    setError('Give the role a name');
                    return;
                  }
                  create.mutate();
                }}
              >
                Create role
              </Button>
              <span className="text-content-muted text-[12px]">
                {selected.size} permission{selected.size === 1 ? '' : 's'} selected
              </span>
            </div>
          </CardBody>
        </Card>
      )}

      {/* ---- List ---- */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(roles ?? []).map((role) => (
            <Card key={role.id} className="flex flex-col">
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    {role.name}
                    {role.is_system && (
                      <Lock className="text-content-muted h-3 w-3" aria-label="Built-in role" />
                    )}
                  </span>
                }
                description={role.description ?? undefined}
              />
              <CardBody className="flex-1">
                <div className="flex flex-wrap gap-1.5">
                  {role.permissions.slice(0, 6).map((permission) => (
                    <Badge
                      key={permission}
                      tone={permission === '*:*' ? 'primary' : 'neutral'}
                      className="font-mono"
                    >
                      {permission}
                    </Badge>
                  ))}
                  {role.permissions.length > 6 && (
                    <Badge tone="neutral">+{role.permissions.length - 6} more</Badge>
                  )}
                </div>

                <div className="border-border mt-4 flex items-center justify-between border-t pt-3">
                  <span className="text-content-muted text-[12px]">
                    {role.member_count} member{role.member_count === 1 ? '' : 's'}
                    {role.is_default && ' · default'}
                  </span>

                  {can('role:delete') && !role.is_system && (
                    <Button
                      variant="ghost"
                      size="icon"
                      title={`Delete ${role.name}`}
                      aria-label={`Delete ${role.name}`}
                      disabled={role.member_count > 0}
                      onClick={() => {
                        if (window.confirm(`Delete the "${role.name}" role?`)) {
                          remove.mutate(role.id);
                        }
                      }}
                    >
                      <Trash2
                        className={cn(
                          'h-3.5 w-3.5',
                          role.member_count > 0 ? 'text-content-muted' : 'text-danger',
                        )}
                      />
                    </Button>
                  )}
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {catalogue && (
        <p className="text-content-muted mt-6 flex items-center gap-1.5 text-[12px]">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          {catalogue.total} permissions across {catalogue.groups.length} groups. The server enforces
          every one of them on every request.
        </p>
      )}
    </div>
  );
}
