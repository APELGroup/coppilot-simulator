import { useEffect, useState } from "react";
import { getCurrentRole, type Role } from "@/lib/auth";

export function useRole(): { role: Role | null; ready: boolean } {
  // Always start as null/false to match SSR; read storage after mount.
  const [role, setRole] = useState<Role | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setRole(getCurrentRole());
    setReady(true);
    // "dtlab-auth-change" fires on setToken() and clearToken()
    const update = () => setRole(getCurrentRole());
    window.addEventListener("dtlab-auth-change", update);
    return () => {
      window.removeEventListener("dtlab-auth-change", update);
    };
  }, []);

  return { role, ready };
}
