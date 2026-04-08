import { apiFetch } from "./client";
import type {
  Role,
  ToolPermission,
  AIProfile,
  UserRoleAssignment,
  CollectionACL,
} from "@/types/roles";

export async function fetchRoles(): Promise<{
  roles: Role[];
}> {
  return apiFetch("/api/roles");
}

export async function createRole(
  name: string,
  level: number,
  description: string,
): Promise<void> {
  await apiFetch("/api/roles/create", {
    method: "POST",
    body: JSON.stringify({ name, level, description }),
  });
}

export async function updateRole(
  name: string,
  level: number,
  description: string,
): Promise<void> {
  await apiFetch(`/api/roles/${name}/update`, {
    method: "POST",
    body: JSON.stringify({ level, description }),
  });
}

export async function deleteRole(name: string): Promise<void> {
  await apiFetch(`/api/roles/${name}/delete`, { method: "POST" });
}

export async function fetchToolPermissions(): Promise<{
  tools: ToolPermission[];
  role_names: string[];
}> {
  return apiFetch("/api/roles/tools");
}

export async function setToolRole(
  toolName: string,
  role: string,
): Promise<void> {
  await apiFetch(`/api/roles/tools/${encodeURIComponent(toolName)}/set`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export async function clearToolRole(toolName: string): Promise<void> {
  await apiFetch(`/api/roles/tools/${encodeURIComponent(toolName)}/clear`, {
    method: "POST",
  });
}

export async function fetchProfiles(): Promise<{
  profiles: AIProfile[];
  declared_calls: string[];
  profile_names: string[];
  all_tool_names: string[];
}> {
  return apiFetch("/api/roles/profiles");
}

export async function saveProfile(profile: {
  name: string;
  description: string;
  tool_mode: string;
  tools: string[];
  tool_roles: Record<string, string>;
}): Promise<void> {
  await apiFetch("/api/roles/profiles/save", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export async function deleteProfile(name: string): Promise<void> {
  await apiFetch(`/api/roles/profiles/${name}/delete`, { method: "POST" });
}

export async function assignProfile(
  aiCall: string,
  profileName: string,
): Promise<void> {
  await apiFetch("/api/roles/profiles/assign", {
    method: "POST",
    body: JSON.stringify({ ai_call: aiCall, profile_name: profileName }),
  });
}

export async function fetchUserRoles(): Promise<{
  users: UserRoleAssignment[];
  role_names: string[];
}> {
  return apiFetch("/api/roles/users");
}

export async function setUserRoles(
  userId: string,
  roles: string[],
): Promise<void> {
  await apiFetch(`/api/roles/users/${userId}/roles`, {
    method: "POST",
    body: JSON.stringify({ roles }),
  });
}

export async function fetchCollectionACLs(): Promise<{
  collections: CollectionACL[];
  role_names: string[];
}> {
  return apiFetch("/api/roles/collections");
}

export async function setCollectionACL(
  collection: string,
  readRole: string,
  writeRole: string,
): Promise<void> {
  await apiFetch(
    `/api/roles/collections/${encodeURIComponent(collection)}/set`,
    {
      method: "POST",
      body: JSON.stringify({ read_role: readRole, write_role: writeRole }),
    },
  );
}

export async function clearCollectionACL(collection: string): Promise<void> {
  await apiFetch(
    `/api/roles/collections/${encodeURIComponent(collection)}/clear`,
    {
      method: "POST",
    },
  );
}
