import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Users as UsersIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { getCurrentUserInfo } from "@/lib/auth";
import type { Role } from "@/lib/auth";
import {
  getUsers,
  loadUsersFromBackend,
  removeUser,
  subscribeUsers,
  updateUserRole,
  type ManagedUser,
} from "@/lib/users-store";

export const Route = createFileRoute("/users")({
  head: () => ({
    meta: [
      { title: "Users — DT Lab" },
      { name: "description", content: "Manage users and roles for the Digital Twin Lab workspace." },
    ],
  }),
  component: UsersPage,
});

const roles: Role[] = ["admin", "researcher", "student"];

function UsersPage() {
  const [users, setUsers] = useState<ManagedUser[]>(() => getUsers());
  const [pendingDelete, setPendingDelete] = useState<ManagedUser | null>(null);
  const currentEmail = getCurrentUserInfo()?.email ?? null;

  useEffect(() => {
    // Always fetch fresh from the backend when this page mounts
    loadUsersFromBackend();
    setUsers(getUsers());
    return subscribeUsers(() => setUsers(getUsers()));
  }, []);

  const handleRoleChange = async (id: string, newRole: Role) => {
    try {
      await updateUserRole(id, newRole);
      toast.success("User role updated");
    } catch {
      toast.error("Failed to update user role");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await removeUser(pendingDelete.id);
      toast.success(`${pendingDelete.name} removed`);
    } catch {
      toast.error("Failed to remove user");
    }
    setPendingDelete(null);
  };

  return (
    <AppShell>
      <PageHeader
        title="Users"
        description="Manage workspace members and their access roles."
      />
      <Card className="p-0 overflow-hidden">
        <div className="border-b border-border bg-muted/40 px-5 py-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <UsersIcon className="h-4 w-4" />
          {users.length} {users.length === 1 ? "member" : "members"}
        </div>
        <table className="w-full text-sm">
          <thead className="bg-muted/20 text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="text-left py-3 px-5 font-medium">User</th>
              <th className="text-left py-3 px-5 font-medium">Email</th>
              <th className="text-left py-3 px-5 font-medium w-44">Role</th>
              <th className="text-right py-3 px-5 font-medium w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-border hover:bg-muted/20">
                <td className="py-3 px-5">
                  <div className="flex items-center gap-3">
                    <Avatar className="h-8 w-8">
                      <AvatarFallback className="bg-primary text-primary-foreground text-xs font-semibold">
                        {u.initials}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <div className="font-medium flex items-center gap-2">
                        {u.name}
                        {u.email === currentEmail && (
                          <span className="text-[10px] uppercase tracking-wider text-primary font-semibold">
                            You
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="py-3 px-5 text-muted-foreground">{u.email}</td>
                <td className="py-3 px-5">
                  <Select
                    value={u.role}
                    onValueChange={(v) => handleRoleChange(u.id, v as Role)}
                    disabled={u.email === currentEmail}
                  >
                    <SelectTrigger className="h-9 w-36 capitalize">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {roles.map((r) => (
                        <SelectItem key={r} value={r} className="capitalize">
                          {r}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
                <td className="py-3 px-5 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
                    onClick={() => setPendingDelete(u)}
                    disabled={u.email === currentEmail}
                    title={u.email === currentEmail ? "You cannot delete your own account" : "Delete user"}
                  >
                    <Trash2 className="h-4 w-4 mr-1.5" />
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <AlertDialog open={!!pendingDelete} onOpenChange={(o) => !o && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure you want to delete this user?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `${pendingDelete.name} (${pendingDelete.email}) will be permanently removed from the workspace.`
                : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}
