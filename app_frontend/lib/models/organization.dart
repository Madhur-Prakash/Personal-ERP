import 'json.dart';

/// Organization, member, role, and audit contracts.
class Organization {
  const Organization({
    required this.id,
    required this.name,
    required this.slug,
    this.gstin,
    required this.currency,
    required this.timezone,
    required this.fiscalYearStartMonth,
    required this.plan,
    required this.country,
  });

  final String id;
  final String name;
  final String slug;
  final String? gstin;
  final String currency;
  final String timezone;
  final int fiscalYearStartMonth;
  final String plan;
  final String country;

  factory Organization.fromJson(Json json) => Organization(
    id: str(json, 'id'),
    name: str(json, 'name'),
    slug: str(json, 'slug'),
    gstin: strOrNull(json, 'gstin'),
    currency: strOrNull(json, 'currency') ?? 'INR',
    timezone: strOrNull(json, 'timezone') ?? 'Asia/Kolkata',
    fiscalYearStartMonth: intOf(json, 'fiscal_year_start_month', 4),
    plan: strOrNull(json, 'plan') ?? 'free',
    country: strOrNull(json, 'country') ?? 'IN',
  );
}

class OrganizationListItem {
  const OrganizationListItem({
    required this.id,
    required this.name,
    required this.plan,
    required this.roleName,
    required this.isOwner,
    required this.memberCount,
  });

  final String id;
  final String name;
  final String plan;
  final String roleName;
  final bool isOwner;
  final int memberCount;

  factory OrganizationListItem.fromJson(Json json) => OrganizationListItem(
    id: str(json, 'id'),
    name: str(json, 'name'),
    plan: strOrNull(json, 'plan') ?? 'free',
    roleName: strOrNull(json, 'role_name') ?? '',
    isOwner: boolOf(json, 'is_owner'),
    memberCount: intOf(json, 'member_count'),
  );
}

class RoleSummary {
  const RoleSummary({
    required this.id,
    required this.name,
    required this.slug,
    required this.isSystem,
  });

  final String id;
  final String name;
  final String slug;
  final bool isSystem;

  factory RoleSummary.fromJson(Json json) => RoleSummary(
    id: str(json, 'id'),
    name: str(json, 'name'),
    slug: strOrNull(json, 'slug') ?? '',
    isSystem: boolOf(json, 'is_system'),
  );
}

class MemberUser {
  const MemberUser({
    required this.id,
    required this.email,
    required this.fullName,
    this.avatarUrl,
    required this.initials,
    this.lastLoginAt,
  });

  final String id;
  final String email;
  final String fullName;
  final String? avatarUrl;
  final String initials;
  final String? lastLoginAt;

  factory MemberUser.fromJson(Json json) => MemberUser(
    id: str(json, 'id'),
    email: str(json, 'email'),
    fullName: str(json, 'full_name'),
    avatarUrl: strOrNull(json, 'avatar_url'),
    initials: strOrNull(json, 'initials') ?? '',
    lastLoginAt: strOrNull(json, 'last_login_at'),
  );
}

class Member {
  const Member({
    required this.id,
    required this.user,
    required this.role,
    required this.status,
    required this.isOwner,
    this.lastActiveAt,
  });

  final String id;
  final MemberUser user;
  final RoleSummary role;

  /// `active` or `suspended`.
  final String status;
  final bool isOwner;
  final String? lastActiveAt;

  bool get isActive => status == 'active';

  factory Member.fromJson(Json json) => Member(
    id: str(json, 'id'),
    user: MemberUser.fromJson(mapOf(json, 'user')),
    role: RoleSummary.fromJson(mapOf(json, 'role')),
    status: strOrNull(json, 'status') ?? 'active',
    isOwner: boolOf(json, 'is_owner'),
    lastActiveAt: strOrNull(json, 'last_active_at'),
  );
}

class Invitation {
  const Invitation({
    required this.id,
    required this.email,
    required this.role,
    required this.status,
    required this.createdAt,
    required this.isExpired,
  });

  final String id;
  final String email;
  final RoleSummary role;

  /// `pending`, `accepted`, `revoked`, or `expired`.
  final String status;
  final String createdAt;
  final bool isExpired;

  factory Invitation.fromJson(Json json) => Invitation(
    id: str(json, 'id'),
    email: str(json, 'email'),
    role: RoleSummary.fromJson(mapOf(json, 'role')),
    status: strOrNull(json, 'status') ?? 'pending',
    createdAt: str(json, 'created_at'),
    isExpired: boolOf(json, 'is_expired'),
  );
}

class InvitationPreview {
  const InvitationPreview({
    required this.organizationName,
    required this.roleName,
    this.invitedByName,
    required this.email,
    required this.expiresAt,
    required this.requiresRegistration,
  });

  final String organizationName;
  final String roleName;
  final String? invitedByName;
  final String email;
  final String expiresAt;

  /// True when the recipient has no account yet, so the page can send them to
  /// registration instead of offering an Accept button that would 401.
  final bool requiresRegistration;

  factory InvitationPreview.fromJson(Json json) => InvitationPreview(
    organizationName: str(json, 'organization_name'),
    roleName: str(json, 'role_name'),
    invitedByName: strOrNull(json, 'invited_by_name'),
    email: str(json, 'email'),
    expiresAt: str(json, 'expires_at'),
    requiresRegistration: boolOf(json, 'requires_registration'),
  );
}

class Role {
  const Role({
    required this.id,
    required this.name,
    this.description,
    required this.permissions,
    required this.isSystem,
    required this.isDefault,
    required this.memberCount,
  });

  final String id;
  final String name;
  final String? description;

  /// As stored - may contain wildcards such as `invoice:*` or `*:*`.
  final List<String> permissions;
  final bool isSystem;
  final bool isDefault;
  final int memberCount;

  factory Role.fromJson(Json json) => Role(
    id: str(json, 'id'),
    name: str(json, 'name'),
    description: strOrNull(json, 'description'),
    permissions: stringList(json, 'permissions'),
    isSystem: boolOf(json, 'is_system'),
    isDefault: boolOf(json, 'is_default'),
    memberCount: intOf(json, 'member_count'),
  );
}

class PermissionInfo {
  const PermissionInfo({
    required this.slug,
    required this.resource,
    required this.action,
  });

  final String slug;
  final String resource;
  final String action;

  factory PermissionInfo.fromJson(Json json) => PermissionInfo(
    slug: str(json, 'slug'),
    resource: str(json, 'resource'),
    action: str(json, 'action'),
  );
}

class PermissionGroup {
  const PermissionGroup({
    required this.key,
    required this.label,
    required this.description,
    required this.permissions,
  });

  final String key;
  final String label;
  final String description;
  final List<PermissionInfo> permissions;

  factory PermissionGroup.fromJson(Json json) => PermissionGroup(
    key: str(json, 'key'),
    label: str(json, 'label'),
    description: strOrNull(json, 'description') ?? '',
    permissions: listOf(json, 'permissions', PermissionInfo.fromJson),
  );
}

class PermissionCatalogue {
  const PermissionCatalogue({required this.groups, required this.total});

  final List<PermissionGroup> groups;
  final int total;

  factory PermissionCatalogue.fromJson(Json json) => PermissionCatalogue(
    groups: listOf(json, 'groups', PermissionGroup.fromJson),
    total: intOf(json, 'total'),
  );
}

class AuditActor {
  const AuditActor({this.email, this.name});

  final String? email;
  final String? name;

  /// What to print for whoever did this. `System` when the actor is null, which is
  /// how a scheduled or internal action is recorded.
  String get display => name ?? email ?? 'System';

  factory AuditActor.fromJson(Json json) => AuditActor(
    email: strOrNull(json, 'email'),
    name: strOrNull(json, 'name'),
  );
}

class AuditChange {
  const AuditChange({this.before, this.after});

  final Object? before;
  final Object? after;
}

class AuditEntry {
  const AuditEntry({
    required this.id,
    required this.action,
    required this.severity,
    this.summary,
    required this.actor,
    this.ipAddress,
    required this.changes,
    required this.createdAt,
  });

  final String id;
  final String action;

  /// `info`, `warning`, or `critical`.
  final String severity;
  final String? summary;
  final AuditActor actor;
  final String? ipAddress;

  /// The field-level diff. Values are `dynamic` because a diff can hold a string,
  /// number, boolean, null, or a nested JSONB object.
  final Map<String, AuditChange> changes;
  final String createdAt;

  factory AuditEntry.fromJson(Json json) {
    final Json raw = mapOf(json, 'changes');
    return AuditEntry(
      id: str(json, 'id'),
      action: str(json, 'action'),
      severity: strOrNull(json, 'severity') ?? 'info',
      summary: strOrNull(json, 'summary'),
      actor: AuditActor.fromJson(mapOf(json, 'actor')),
      ipAddress: strOrNull(json, 'ip_address'),
      changes: <String, AuditChange>{
        for (final MapEntry<String, dynamic> entry in raw.entries)
          if (entry.value is Map)
            entry.key: AuditChange(
              before: (entry.value as Map<dynamic, dynamic>)['before'],
              after: (entry.value as Map<dynamic, dynamic>)['after'],
            ),
      },
      createdAt: str(json, 'created_at'),
    );
  }
}
