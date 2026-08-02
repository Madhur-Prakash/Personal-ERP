import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../models/organization.dart';
import '../../state/auth_controller.dart';
import '../../state/data_providers.dart';
import '../../state/providers.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/app_badge.dart';
import '../../widgets/app_button.dart';
import '../../widgets/app_card.dart';
import '../../widgets/app_input.dart';
import '../../widgets/app_modal.dart';
import '../../widgets/primitives.dart';
import '../../widgets/toast.dart';
import 'permission_summary.dart';

/// Roles and permissions.
///
/// The permission picker is built from the server's catalogue (`/roles/permissions`) rather
/// than a hard-coded list, so it can never offer a permission the backend does not enforce,
/// or omit one it does. The cards read from the same catalogue, which is what lets them name
/// capabilities instead of printing slugs.
class RolesScreen extends ConsumerStatefulWidget {
  const RolesScreen({super.key});

  @override
  ConsumerState<RolesScreen> createState() => _RolesScreenState();
}

class _RolesScreenState extends ConsumerState<RolesScreen> {
  bool _creating = false;
  final TextEditingController _name = TextEditingController();
  final Set<String> _selected = <String>{};
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _reset() {
    setState(() {
      _creating = false;
      _name.clear();
      _selected.clear();
      _error = null;
    });
  }

  Future<void> _create() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Give the role a name');
      return;
    }

    setState(() => _saving = true);
    try {
      final Role role = await ref
          .read(organizationsApiProvider)
          .createRole(name: _name.text.trim(), permissions: _selected.toList());
      ref.invalidate(rolesProvider);
      if (!mounted) return;
      context.toastSuccess('Role "${role.name}" created');
      _reset();
    } catch (error) {
      if (mounted) {
        setState(() => _error = 'Could not create the role');
        context.toastApiError(error, 'Could not create the role');
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete(Role role) async {
    final bool confirmed = await confirmAction(
      context,
      title: 'Delete the "${role.name}" role?',
      message: 'Nobody holds it, so nothing loses access.',
      confirmLabel: 'Delete role',
    );
    if (!confirmed) return;

    try {
      await ref.read(organizationsApiProvider).deleteRole(role.id);
      ref.invalidate(rolesProvider);
      if (mounted) context.toastSuccess('Role deleted');
    } catch (error) {
      // The server refuses to delete a role people still hold, and its message names the
      // count - surface it verbatim rather than paraphrasing.
      if (mounted) context.toastApiError(error, 'Could not delete the role');
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final AuthState auth = ref.watch(authControllerProvider);
    final AsyncValue<List<Role>> roles = ref.watch(rolesProvider);
    final PermissionCatalogue? catalogue = ref
        .watch(permissionCatalogueProvider)
        .valueOrNull;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        PageHeader(
          title: 'Roles and permissions',
          description:
              'Roles bundle permissions. Built-in roles cannot be renamed or deleted, but '
              'their permissions can be adjusted.',
          action: auth.can('role:create') && !_creating
              ? AppButton(
                  onPressed: () => setState(() => _creating = true),
                  leftIcon: LucideIcons.plus,
                  label: 'New role',
                )
              : null,
        ),

        // ---- Create ----
        if (_creating) ...<Widget>[
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                CardHeader(
                  title: 'Create a role',
                  description:
                      'Pick a name, then choose exactly what it can do.',
                  action: AppButton(
                    onPressed: _reset,
                    variant: AppButtonVariant.ghost,
                    size: AppButtonSize.sm,
                    label: 'Cancel',
                  ),
                ),
                CardBody(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    spacing: 20,
                    children: <Widget>[
                      AppInput(
                        label: 'Role name',
                        controller: _name,
                        placeholder: 'e.g. Invoice Clerk',
                        error: _error,
                        autofocus: true,
                        width: 384,
                        onChanged: (_) => setState(() {}),
                      ),
                      if (catalogue == null)
                        const Skeleton(height: 192, radius: Radii.lg)
                      else
                        Column(
                          spacing: 16,
                          children: <Widget>[
                            for (final PermissionGroup group
                                in catalogue.groups)
                              _PermissionGroupBox(
                                group: group,
                                selected: _selected,
                                onToggle: (String slug) => setState(() {
                                  if (!_selected.remove(slug)) {
                                    _selected.add(slug);
                                  }
                                }),
                                onToggleGroup: (List<String> slugs, bool all) =>
                                    setState(() {
                                      if (all) {
                                        _selected.removeAll(slugs);
                                      } else {
                                        _selected.addAll(slugs);
                                      }
                                    }),
                              ),
                          ],
                        ),
                      Row(
                        spacing: 12,
                        children: <Widget>[
                          AppButton(
                            onPressed:
                                _name.text.trim().isEmpty ||
                                    _selected.isEmpty ||
                                    _saving
                                ? null
                                : _create,
                            loading: _saving,
                            label: 'Create role',
                          ),
                          Text(
                            '${_selected.length} '
                            'permission${_selected.length == 1 ? '' : 's'} selected',
                            style: TextStyle(
                              fontSize: 12,
                              color: t.contentMuted,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
        ],

        // ---- List ----
        if (roles.isLoading)
          _RoleGrid(
            children: <Widget>[
              for (int index = 0; index < 5; index++)
                const Skeleton(height: 144, radius: Radii.xl),
            ],
          )
        else
          _RoleGrid(
            children: <Widget>[
              for (final Role role in roles.valueOrNull ?? const <Role>[])
                _RoleCard(
                  role: role,
                  groups: catalogue?.groups,
                  canDelete: auth.can('role:delete'),
                  onDelete: () => _delete(role),
                ),
            ],
          ),

        if (catalogue != null) ...<Widget>[
          const SizedBox(height: 24),
          Row(
            spacing: 6,
            children: <Widget>[
              Icon(LucideIcons.shieldCheck, size: 14, color: t.contentMuted),
              Expanded(
                child: Text(
                  '${catalogue.total} permissions across ${catalogue.groups.length} '
                  'groups. The server enforces every one of them on every request.',
                  style: TextStyle(fontSize: 12, color: t.contentMuted),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _RoleGrid extends StatelessWidget {
  const _RoleGrid({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final double width = constraints.maxWidth;
        final int columns = width >= 1180 ? 3 : (width >= 760 ? 2 : 1);
        const double gap = 16;
        final double cardWidth = (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: <Widget>[
            for (final Widget child in children)
              SizedBox(width: cardWidth, child: child),
          ],
        );
      },
    );
  }
}

class _RoleCard extends StatelessWidget {
  const _RoleCard({
    required this.role,
    required this.groups,
    required this.canDelete,
    required this.onDelete,
  });

  final Role role;
  final List<PermissionGroup>? groups;
  final bool canDelete;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            titleWidget: Row(
              mainAxisSize: MainAxisSize.min,
              spacing: 8,
              children: <Widget>[
                Text(
                  role.name,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: t.content,
                  ),
                ),
                if (role.isSystem)
                  Tooltip(
                    message: 'Built-in role',
                    child: Icon(
                      LucideIcons.lock,
                      size: 12,
                      color: t.contentMuted,
                    ),
                  ),
              ],
            ),
            description: role.description,
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                _RoleCapabilities(
                  permissions: role.permissions,
                  groups: groups,
                ),
                Container(
                  margin: const EdgeInsets.only(top: 16),
                  padding: const EdgeInsets.only(top: 12),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: t.border)),
                  ),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          '${role.memberCount} '
                          'member${role.memberCount == 1 ? '' : 's'}'
                          '${role.isDefault ? ' · default' : ''}',
                          style: TextStyle(fontSize: 12, color: t.contentMuted),
                        ),
                      ),
                      if (canDelete && !role.isSystem)
                        AppIconButton(
                          icon: LucideIcons.trash2,
                          tooltip: role.memberCount > 0
                              ? 'People still hold this role'
                              : 'Delete ${role.name}',
                          size: 14,
                          colour: role.memberCount > 0
                              ? t.contentMuted
                              : t.danger,
                          onPressed: role.memberCount > 0 ? null : onDelete,
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// What a role can do, as tags.
///
/// Falls back to the raw slugs while the catalogue is loading rather than rendering nothing:
/// a card that shows its permissions a beat late is fine, a card that appears to have none
/// is alarming.
class _RoleCapabilities extends StatelessWidget {
  const _RoleCapabilities({required this.permissions, required this.groups});

  final List<String> permissions;
  final List<PermissionGroup>? groups;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    if (groups == null) {
      return Wrap(
        spacing: 6,
        runSpacing: 6,
        children: <Widget>[
          for (final String permission in permissions.take(4))
            AppBadge(permission),
        ],
      );
    }

    final RoleCapabilities summary = summariseRole(permissions, groups!);

    if (summary.everything) {
      return Row(
        spacing: 8,
        children: <Widget>[
          const AppBadge('Everything', tone: BadgeTone.primary),
          Expanded(
            child: Text(
              'all ${summary.total} permissions, including ones added in future updates',
              style: TextStyle(fontSize: 12, color: t.contentMuted),
            ),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: <Widget>[
            for (final Capability capability in summary.capabilities)
              AppBadge(
                capability.detail == null
                    ? capability.label
                    : '${capability.label} · ${capability.detail}',
                // Full access to an area reads as a stronger grant than a partial one, so it
                // is toned differently rather than being distinguishable only by the suffix.
                tone: capability.complete
                    ? BadgeTone.primary
                    : BadgeTone.neutral,
                // The slugs are still here for anyone who wants them - moved out of the way
                // rather than removed.
                tooltip: capability.slugs.join('\n'),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          '${summary.held} of ${summary.total} permissions',
          style: TextStyle(fontSize: 12, color: t.contentMuted),
        ),
      ],
    );
  }
}

class _PermissionGroupBox extends StatelessWidget {
  const _PermissionGroupBox({
    required this.group,
    required this.selected,
    required this.onToggle,
    required this.onToggleGroup,
  });

  final PermissionGroup group;
  final Set<String> selected;
  final ValueChanged<String> onToggle;
  final void Function(List<String> slugs, bool allSelected) onToggleGroup;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final List<String> slugs = group.permissions
        .map((PermissionInfo p) => p.slug)
        .toList(growable: false);
    final bool allSelected = slugs.every(selected.contains);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: t.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            spacing: 8,
            children: <Widget>[
              Text(
                group.label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: t.content,
                ),
              ),
              AppTextLink(
                label: allSelected ? 'Clear' : 'Select all',
                fontSize: 11,
                onTap: () => onToggleGroup(slugs, allSelected),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            group.description,
            style: TextStyle(fontSize: 12, color: t.contentMuted),
          ),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              final int columns = constraints.maxWidth >= 900
                  ? 3
                  : constraints.maxWidth >= 600
                  ? 2
                  : 1;
              const double gap = 8;
              final double itemWidth =
                  (constraints.maxWidth - gap * (columns - 1)) / columns;
              return Wrap(
                spacing: gap,
                runSpacing: gap,
                children: <Widget>[
                  for (final PermissionInfo permission in group.permissions)
                    SizedBox(
                      width: itemWidth,
                      child: _PermissionRow(
                        permission: permission,
                        checked: selected.contains(permission.slug),
                        onToggle: () => onToggle(permission.slug),
                      ),
                    ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _PermissionRow extends StatefulWidget {
  const _PermissionRow({
    required this.permission,
    required this.checked,
    required this.onToggle,
  });

  final PermissionInfo permission;
  final bool checked;
  final VoidCallback onToggle;

  @override
  State<_PermissionRow> createState() => _PermissionRowState();
}

class _PermissionRowState extends State<_PermissionRow> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        onTap: widget.onToggle,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: _hovered ? t.surfaceHover : Colors.transparent,
            borderRadius: BorderRadius.circular(Radii.md),
          ),
          child: Row(
            spacing: 8,
            children: <Widget>[
              SizedBox(
                width: 16,
                height: 16,
                child: Transform.scale(
                  scale: 0.8,
                  child: Checkbox(
                    value: widget.checked,
                    onChanged: (_) => widget.onToggle(),
                  ),
                ),
              ),
              Expanded(
                child: Text(
                  widget.permission.action,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12, color: t.contentSecondary),
                ),
              ),
              Text(
                widget.permission.resource,
                style: monoStyle(fontSize: 10, color: t.contentMuted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
