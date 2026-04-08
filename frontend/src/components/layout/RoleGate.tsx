import type { ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { hasRole } from "@/types/auth";

interface RoleGateProps {
  role: string;
  children: ReactNode;
}

export function RoleGate({ role, children }: RoleGateProps) {
  const { user } = useAuth();
  if (!hasRole(user, role)) return null;
  return <>{children}</>;
}
