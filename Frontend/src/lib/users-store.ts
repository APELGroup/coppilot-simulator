import type { Role } from "./auth";
import { fetchUsers, createUserApi, updateUserRoleApi, deleteUserApi } from "./api";

export interface ManagedUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  initials: string;
  isSelf?: boolean;
}

const EVENT = "dtlab-users-change";

const _seed: ManagedUser[] = [
  { id: "u-1", name: "Marco Rossi",         email: "marco.rossi@dtlab.io",     role: "admin",      initials: "MR", isSelf: true },
  { id: "u-2", name: "Dr. Elena Marchetti", email: "elena.marchetti@dtlab.io", role: "researcher", initials: "EM" },
  { id: "u-3", name: "Sofia Bianchi",        email: "sofia.bianchi@dtlab.io",  role: "student",    initials: "SB" },
  { id: "u-4", name: "Luca Conti",           email: "luca.conti@dtlab.io",     role: "student",    initials: "LC" },
  { id: "u-5", name: "Giulia Ferrari",       email: "giulia.ferrari@dtlab.io", role: "researcher", initials: "GF" },
];

let _users: ManagedUser[] = [..._seed];

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function emit() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT));
}

export function getUsers(): ManagedUser[] {
  return _users;
}

export async function loadUsersFromBackend(): Promise<void> {
  try {
    const data = await fetchUsers();
    if (data.length > 0) {
      _users = data as ManagedUser[];
      emit();
    }
  } catch {
    // DB unavailable — keep seed data
  }
}

export async function addUser(input: { name: string; email: string; role: Role }): Promise<ManagedUser> {
  const existing = _users.find((u) => u.email.toLowerCase() === input.email.toLowerCase());
  if (existing) return existing;

  const localUser: ManagedUser = {
    id: `u-${Date.now()}`,
    name: input.name,
    email: input.email,
    role: input.role,
    initials: getInitials(input.name),
  };

  try {
    const data = await createUserApi(input);
    _users = data as ManagedUser[];
    emit();
    return _users.find((u) => u.email.toLowerCase() === input.email.toLowerCase()) ?? localUser;
  } catch {
    _users = [..._users, localUser];
    emit();
    return localUser;
  }
}

export async function removeUser(id: string): Promise<void> {
  try {
    await deleteUserApi(id);
  } catch {
    // DB unavailable — remove from memory anyway
  }
  _users = _users.filter((u) => u.id !== id);
  emit();
}

export async function updateUserRole(id: string, role: Role): Promise<void> {
  try {
    const data = await updateUserRoleApi(id, role);
    _users = data as ManagedUser[];
  } catch {
    _users = _users.map((u) => (u.id === id ? { ...u, role } : u));
  }
  emit();
}

export function subscribeUsers(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = () => cb();
  window.addEventListener(EVENT, handler);
  return () => { window.removeEventListener(EVENT, handler); };
}
