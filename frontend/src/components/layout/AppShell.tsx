import { Outlet } from "react-router-dom";
import { NavBar } from "./NavBar";
import { useMcpBridge } from "@/hooks/useMcpBridge";

export function AppShell() {
  // Mount the MCP browser-bridge here so it lives for the full
  // authenticated session but never runs on the login page.
  useMcpBridge();
  return (
    <div className="flex h-[100svh] flex-col overflow-hidden">
      <NavBar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
