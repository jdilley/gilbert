import { Routes, Route, Link, useLocation, Navigate } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RolesList } from "./RolesList";
import { ToolPermissions } from "./ToolPermissions";
import { AIProfiles } from "./AIProfiles";
import { UserRoles } from "./UserRoles";
import { CollectionACLs } from "./CollectionACLs";
import { EventVisibility } from "./EventVisibility";
import { RpcPermissions } from "./RpcPermissions";

const TABS = [
  { value: "users", label: "Users", path: "/security/users" },
  { value: "roles", label: "Roles", path: "/security/roles" },
  { value: "tools", label: "Tools", path: "/security/tools" },
  { value: "profiles", label: "AI Profiles", path: "/security/profiles" },
  { value: "collections", label: "Collections", path: "/security/collections" },
  { value: "events", label: "Events", path: "/security/events" },
  { value: "rpc", label: "RPC", path: "/security/rpc" },
];

export function RolesPage() {
  const location = useLocation();
  const currentTab =
    TABS.find((t) => t.path === location.pathname)?.value || "users";

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-4xl mx-auto">
      <h1 className="text-xl sm:text-2xl font-semibold text-center">Security</h1>

      <Tabs value={currentTab}>
        <div className="-mx-4 overflow-x-auto sm:mx-0">
          <TabsList className="mx-4 w-max sm:mx-0">
            {TABS.map((tab) => (
              <Link key={tab.value} to={tab.path}>
                <TabsTrigger value={tab.value}>{tab.label}</TabsTrigger>
              </Link>
            ))}
          </TabsList>
        </div>
      </Tabs>

      <Routes>
        <Route index element={<Navigate to="/security/users" replace />} />
        <Route path="users" element={<UserRoles />} />
        <Route path="roles" element={<RolesList />} />
        <Route path="tools" element={<ToolPermissions />} />
        <Route path="profiles" element={<AIProfiles />} />
        <Route path="collections" element={<CollectionACLs />} />
        <Route path="events" element={<EventVisibility />} />
        <Route path="rpc" element={<RpcPermissions />} />
      </Routes>
    </div>
  );
}
